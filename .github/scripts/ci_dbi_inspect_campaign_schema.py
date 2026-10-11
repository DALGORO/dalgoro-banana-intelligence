"""Prueba del contrato de persistencia Campaign↔INSPECT↔doble firma, sin red/DB."""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "platform-web" / "backend"))

from app.db.dbi_base import DBIBase  # noqa: E402
from app.dbi import models as _models  # noqa: E402,F401

TABLES = DBIBase.metadata.tables


def named(table, kind):
    return {item.name: item for item in table.constraints if isinstance(item, kind)}


def expect_fk(table, name, local, remote):
    foreign_key = named(table, ForeignKeyConstraint)[name]
    assert tuple(x.parent.name for x in foreign_key.elements) == tuple(local)
    assert tuple(x.target_fullname for x in foreign_key.elements) == tuple(remote)
    assert foreign_key.ondelete == "RESTRICT"


def test_schema() -> None:
    links = TABLES["dbi_inspect_campaign_links"]
    events = TABLES["dbi_inspect_approval_events"]
    campaigns = TABLES["dbi_campaigns"]
    observations = TABLES["dbi_field_observations"]
    versions = TABLES["dbi_field_observation_versions"]

    for table in (links, events):
        for col in table.columns:
            assert col.name != "published"
        assert "tenant_id" not in table.columns

    assert "uq_dbi_campaigns_inspect_multispectral_scope" in named(campaigns, UniqueConstraint)
    assert "uq_dbi_field_observations_inspect_scope" in named(observations, UniqueConstraint)
    assert "uq_dbi_field_observation_versions_observation_id" in named(versions, UniqueConstraint)
    expect_fk(
        links, "fk_dbi_inspect_links_campaign_scope_multi",
        ("campaign_id", "tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_analysis_type"),
        ("dbi_campaigns.id", "dbi_campaigns.tenant_ref", "dbi_campaigns.organization_ref",
         "dbi_campaigns.farm_id", "dbi_campaigns.plot_id", "dbi_campaigns.analysis_type"),
    )
    expect_fk(
        links, "fk_dbi_inspect_links_observation_scope",
        ("observation_id", "tenant_ref", "organization_ref", "farm_id", "plot_id"),
        ("dbi_field_observations.id", "dbi_field_observations.tenant_ref",
         "dbi_field_observations.organization_ref", "dbi_field_observations.farm_id",
         "dbi_field_observations.plot_id"),
    )
    expect_fk(
        links, "fk_dbi_inspect_links_version_identity",
        ("observation_id", "observation_version_id"),
        ("dbi_field_observation_versions.observation_id",
         "dbi_field_observation_versions.id"),
    )
    assert "uq_dbi_inspect_links_one_campaign_per_version" in named(links, UniqueConstraint)
    assert "ck_dbi_inspect_links_multispectral_only" in named(links, CheckConstraint)
    assert "uq_dbi_inspect_approval_event_step" in named(events, UniqueConstraint)
    assert "ck_dbi_inspect_approval_event_kind" in named(events, CheckConstraint)
    expect_fk(
        events, "fk_dbi_inspect_approval_events_link",
        ("link_id",), ("dbi_inspect_campaign_links.id",),
    )
    assert not any(
        "casCADE".lower() in (fk.ondelete or "").lower()
        for table in (links, events)
        for fk in named(table, ForeignKeyConstraint).values()
    )

    for table in (links, events):
        compiled = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "FOREIGN KEY" in compiled
        assert "CHECK" in compiled
        assert "UNIQUE" in compiled

    migration = (
        ROOT / "apps" / "platform-web" / "backend" / "dbi_alembic" /
        "versions" / "20261011_27_inspect_campaign_signatures.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "dbi_0027_inspect_dual_sign"' in migration
    assert 'down_revision: str | None = "dbi_0026_gpkg_layer_choice"' in migration
    assert "UPDATE dbi_field_observations" not in migration
    assert "UPDATE dbi_campaigns" not in migration
    assert "op.create_table(" in migration
    assert "op.drop_table(" in migration

    # Prueba estática para no cargar runtime web ni secretos del entorno CI.
    # Esta migración no abre endpoints cliente ni activa visibilidad.
    api = (ROOT / "apps" / "platform-web" / "backend" /
           "app" / "api" / "v1" / "dbi_inspection.py").read_text(encoding="utf-8")
    service = (ROOT / "apps" / "platform-web" / "backend" /
               "app" / "dbi" / "inspection" / "service.py").read_text(encoding="utf-8")
    assert "approve_inspection_for_client" not in api
    assert "approve_for_publication" not in service
    assert "permission=DBIPermission.WRITE" in api
    assert "def _require_internal_read(" in service


if __name__ == "__main__":
    test_schema()
    print("OK: vínculos Campaign-MULTI↔INSPECT con scope DB y eventos auditables, sin publicación.")
