"""Regresión integrada: selección GPKG -> worker -> preview MANAGE -> publicación READ.

No necesita red, Render, S3 real ni archivos de clientes: verifica de manera
determinista las fronteras existentes y el aislamiento entre tenant/Campaign.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_gis_lifecycle.db")
os.environ.setdefault("JWT_SECRET", "ci-dbi-gis-lifecycle-only")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from app.api.v1.dbi_portal_gis_imports import (  # noqa: E402
    PortalGISLayerChoice, select_gis_import_layer, get_gis_import_preview,
    publish_reviewed_gis_import,
)
from app.api.v1.dbi_portal_vectors import list_vector_layers, get_vector_layer  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext, DBIFarmScope, DBIPlotScope, DBIPermission,
)
from app.dbi.models.portal_gis_imports import DBIPortalGISPreview  # noqa: E402
from app.dbi.models.portal_vectors import DBIPortalVectorLayer  # noqa: E402
from app.dbi.portal_gis_worker_service import DBIPortalGISPreparationWorker  # noqa: E402
from app.dbi.storage_memory import DBIInMemoryObjectStore  # noqa: E402
from ci_dbi_gis_preparation import make_receipt, converter, stage, manager  # noqa: E402


def _scoped(sql, table, values):
    """Compara valores, no solo presencia de nombres de predicados SQL."""
    for field, value in values.items():
        column = f"{table}.{field} ="
        if column in sql and f"{column} '{value}'" not in sql:
            return False
    return True


class State:
    def __init__(self, row):
        self.row = row
        self.campaign_id = row.campaign_id
        self.campaign_plot_id = row.plot_id
        self.preview = None
        self.layer = None
        self.commits = 0
        self.vector_inserts = 0


class Session:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        sql = str(statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))
        state = self.state
        row = state.row
        if "FROM dbi_portal_gis_imports" in sql:
            matched = _scoped(sql, "dbi_portal_gis_imports", {
                "id": row.id, "tenant_ref": row.tenant_ref,
                "organization_ref": row.organization_ref,
                "farm_id": row.farm_id, "plot_id": row.plot_id,
            })
            if "attempt_count <" in sql:
                assert "FOR UPDATE SKIP LOCKED" in sql
                matched = matched and row.attempt_count < 3 and (
                    row.status == "received"
                    or row.status == "processing"
                    or (row.status == "needs_selection" and row.source_format == "gpkg"
                        and row.selected_layer is not None)
                )
            if "FOR UPDATE" in sql:
                assert "dbi_portal_gis_imports.tenant_ref =" in sql
            found = row if matched else None
            return SimpleNamespace(
                scalar_one_or_none=lambda: found,
                scalars=lambda: SimpleNamespace(all=lambda: [found] if found else []),
            )
        if "FROM dbi_campaigns" in sql:
            matched = _scoped(sql, "dbi_campaigns", {
                "id": state.campaign_id, "tenant_ref": row.tenant_ref,
                "organization_ref": row.organization_ref,
                "farm_id": row.farm_id, "plot_id": state.campaign_plot_id,
            })
            # Debe existir el mismo identificador, no cualquier Campaign del lote.
            assert "dbi_campaigns.id =" in sql
            assert "dbi_campaigns.tenant_ref =" in sql
            assert "dbi_campaigns.plot_id =" in sql
            found = SimpleNamespace(id=state.campaign_id, status="FIELD_COMPLETED") if matched else None
            return SimpleNamespace(scalar_one_or_none=lambda: found)
        if "FROM dbi_portal_vector_layers" in sql:
            values = {
                "tenant_ref": row.tenant_ref, "organization_ref": row.organization_ref,
                "farm_id": row.farm_id, "plot_id": row.plot_id,
            }
            valid = _scoped(sql, "dbi_portal_vector_layers", values)
            if "dbi_portal_vector_layers.id =" in sql and state.layer is not None:
                valid = valid and _scoped(sql, "dbi_portal_vector_layers", {"id": state.layer.id})
            if "dbi_portal_vector_layers.campaign_id =" in sql:
                valid = valid and _scoped(sql, "dbi_portal_vector_layers", {"campaign_id": row.campaign_id})
            if "dbi_portal_vector_layers.source_sha256 =" in sql and state.preview is not None:
                valid = valid and _scoped(sql, "dbi_portal_vector_layers", {"source_sha256": state.preview.sha256})
            if "JOIN dbi_campaigns" in sql:
                valid = valid and _scoped(sql, "dbi_campaigns", {
                    "tenant_ref": row.tenant_ref, "organization_ref": row.organization_ref,
                    "farm_id": row.farm_id, "plot_id": state.campaign_plot_id,
                }) and state.campaign_id == row.campaign_id
            found = state.layer if valid else None
            return SimpleNamespace(
                scalar_one_or_none=lambda: found,
                scalars=lambda: SimpleNamespace(all=lambda: [found] if found else []),
            )
        raise AssertionError("Consulta inesperada " + sql[:200])

    def get(self, model, pk):
        assert model is DBIPortalGISPreview
        return self.state.preview if self.state.preview and self.state.preview.import_id == pk else None

    def add(self, instance):
        if isinstance(instance, DBIPortalGISPreview):
            assert self.state.preview is None
            self.state.preview = instance
        elif isinstance(instance, DBIPortalVectorLayer):
            assert self.state.layer is None
            self.state.layer = instance
            self.state.vector_inserts += 1
        else:
            raise AssertionError("Inserción no permitida")

    def flush(self):
        layer = self.state.layer
        if layer is not None and layer.created_at is None:
            layer.created_at = datetime.now(timezone.utc)

    def commit(self):
        self.state.commits += 1

    def rollback(self):
        raise AssertionError("No se esperaba rollback en recorrido válido")


def _reader(row, *, tenant=None):
    return DBIAccessContext(
        principal_ref="client-read", tenant_ref=tenant or row.tenant_ref,
        organization_refs=frozenset({row.organization_ref}),
        farm_scopes=frozenset({DBIFarmScope(row.organization_ref, row.farm_id)}),
        plot_scopes=frozenset({DBIPlotScope(row.organization_ref, row.farm_id, row.plot_id)}),
        permissions=frozenset({DBIPermission.READ}),
    )


def _denied(status_code, fn):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == status_code, (exc.status_code, status_code, exc.detail)
    else:
        raise AssertionError(f"Se esperaba HTTP {status_code}")


def run():
    payload = b"SQLite format 3\\x00" + b"selected-layer-integrated-fixture"
    store = DBIInMemoryObjectStore()
    row = make_receipt(payload)
    row.status, row.attempt_count = "needs_selection", 1
    row.available_layers = ["plantas", "limites"]
    row.selected_layer = None
    stage(store, row, payload)
    state = State(row)
    session = Session(state)
    writer, reader = manager(row), _reader(row)
    args = (row.organization_ref, row.farm_id, row.plot_id, row.id)
    worker = None
    with TemporaryDirectory(prefix="dbi-gis-e2e-") as root:
        worker = DBIPortalGISPreparationWorker(
            lambda: Session(state), store,
            converter(row.sha256, expected_layer="limites"),
            workspace_root=Path(root),
        )
        # Archivo multicapa sin selección: no se reclama ni publica.
        assert worker.process_one(tenant_ref=row.tenant_ref) is None
        assert state.preview is None and state.layer is None
        _denied(404, lambda: get_gis_import_preview(*args, session, writer))
        _denied(409, lambda: publish_reviewed_gis_import(*args, session, writer))
        assert list_vector_layers(row.organization_ref, row.farm_id, row.plot_id, session, reader) == []

        # Solo MANAGE del tenant/lote/campaign puede confirmar nombre exacto.
        _denied(404, lambda: select_gis_import_layer(
            *args, PortalGISLayerChoice(layer="limites"), session, reader,
        ))
        _denied(404, lambda: select_gis_import_layer(
            *args, PortalGISLayerChoice(layer="limites"), session,
            DBIAccessContext(
                principal_ref="tenant-b-staff", tenant_ref="tenant-b",
                organization_refs=frozenset({row.organization_ref}),
                farm_scopes=frozenset({DBIFarmScope(row.organization_ref, row.farm_id)}),
                plot_scopes=frozenset({DBIPlotScope(row.organization_ref, row.farm_id, row.plot_id)}),
                permissions=frozenset({DBIPermission.MANAGE}),
            ),
        ))
        selected = select_gis_import_layer(
            *args, PortalGISLayerChoice(layer="limites"), session, writer,
        )
        assert selected.selected_layer == "limites" and selected.campaign_id == row.campaign_id
        assert selected.status == "needs_selection" and state.layer is None
        before = state.commits
        select_gis_import_layer(*args, PortalGISLayerChoice(layer="limites"), session, writer)
        assert state.commits == before
        _denied(409, lambda: select_gis_import_layer(
            *args, PortalGISLayerChoice(layer="plantas"), session, writer,
        ))

        # Conversión verificada por worker: no publica sin revisión del gestor.
        assert worker.process_one(tenant_ref="another-tenant") is None
        assert worker.process_one(tenant_ref=row.tenant_ref) == "prepared"
        assert row.status == "prepared" and row.selected_layer == "limites"
        assert row.published_layer_id is None and state.layer is None
        assert worker.process_one(tenant_ref=row.tenant_ref) is None
        assert list(Path(root).iterdir()) == []

        # Preview solo MANAGE, siempre vinculada al tenant/plot/Campaign vigente.
        _denied(404, lambda: get_gis_import_preview(*args, session, reader))
        _denied(404, lambda: get_gis_import_preview(
            row.organization_ref, row.farm_id, uuid4(), row.id, session, writer,
        ))
        _denied(404, lambda: get_gis_import_preview(
            row.organization_ref, row.farm_id, row.plot_id, uuid4(), session, writer,
        ))
        state.campaign_id = uuid4()  # Otro levantamiento del mismo lote.
        _denied(404, lambda: get_gis_import_preview(*args, session, writer))
        _denied(404, lambda: publish_reviewed_gis_import(*args, session, writer))
        state.campaign_id = row.campaign_id
        state.campaign_plot_id = uuid4()  # Campaign original asociada a otro lote.
        _denied(404, lambda: get_gis_import_preview(*args, session, writer))
        _denied(404, lambda: publish_reviewed_gis_import(*args, session, writer))
        state.campaign_plot_id = row.plot_id

        detail = get_gis_import_preview(*args, session, writer)
        assert detail.receipt.campaign_id == row.campaign_id
        assert detail.receipt.selected_layer == "limites"
        assert detail.feature_count == 1
        assert detail.geojson["features"][0]["properties"] == {"plantas": 1500}
        assert state.layer is None
        assert list_vector_layers(row.organization_ref, row.farm_id, row.plot_id, session, reader) == []

        # Una preview adulterada se rechaza incluso con MANAGE.
        previous = state.preview.sha256
        state.preview.sha256 = "0" * 64
        _denied(409, lambda: publish_reviewed_gis_import(*args, session, writer))
        state.preview.sha256 = previous
        assert state.layer is None

        # Aprobación explícita, sin que el worker participe en la publicación.
        published = publish_reviewed_gis_import(*args, session, writer)
        assert row.status == "published" and row.published_layer_id == published.id
        assert row.approved_by_ref == writer.principal_ref and row.approved_at is not None
        assert state.vector_inserts == 1
        assert state.layer.tenant_ref == row.tenant_ref
        assert state.layer.organization_ref == row.organization_ref
        assert state.layer.farm_id == row.farm_id and state.layer.plot_id == row.plot_id
        assert state.layer.campaign_id == row.campaign_id
        assert state.layer.geojson_text == state.preview.geojson_text
        assert state.layer.source_sha256 == sha256(state.preview.geojson_text.encode()).hexdigest()
        assert state.layer.source_bytes == state.preview.geojson_text.encode()
        assert state.layer.created_by_ref == writer.principal_ref
        again = publish_reviewed_gis_import(*args, session, writer)
        assert again.id == published.id and state.vector_inserts == 1
        assert get_gis_import_preview(*args, session, writer).receipt.status == "published"

        # Publicado: visible a READ del lote, nunca como preview privada a READ.
        client_layers = list_vector_layers(row.organization_ref, row.farm_id, row.plot_id, session, reader)
        assert [entry.id for entry in client_layers] == [published.id]
        result = get_vector_layer(
            row.organization_ref, row.farm_id, row.plot_id, published.id, session, reader,
        )
        assert result.layer.campaign_id == row.campaign_id
        assert result.geojson == detail.geojson
        _denied(404, lambda: get_gis_import_preview(*args, session, reader))
        _denied(404, lambda: get_vector_layer(
            row.organization_ref, row.farm_id, uuid4(), published.id, session, reader,
        ))
        _denied(404, lambda: get_vector_layer(
            row.organization_ref, row.farm_id, row.plot_id, published.id, session,
            _reader(row, tenant="tenant-b"),
        ))
        state.campaign_id = uuid4()
        assert list_vector_layers(row.organization_ref, row.farm_id, row.plot_id, session, reader) == []
        state.campaign_id = row.campaign_id

    print("GIS multicapa: MANAGE -> worker -> preview privada -> aprobación -> READ scoped OK.")


if __name__ == "__main__":
    run()
