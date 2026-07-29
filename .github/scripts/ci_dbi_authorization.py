"""Valida la política de autorización DBI completamente offline."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.authorization import (  # noqa: E402
    DENIED_MESSAGE,
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)


def _context() -> tuple[DBIAccessContext, UUID, UUID]:
    farm_id = uuid4()
    plot_id = uuid4()
    context = DBIAccessContext(
        principal_ref="user-001",
        tenant_ref="tenant-001",
        organization_refs=frozenset({"organization-001"}),
        farm_scopes=frozenset(
            {
                DBIFarmScope(
                    organization_ref="organization-001",
                    farm_id=farm_id,
                )
            }
        ),
        plot_scopes=frozenset(
            {
                DBIPlotScope(
                    organization_ref="organization-001",
                    farm_id=farm_id,
                    plot_id=plot_id,
                )
            }
        ),
        permissions=frozenset(
            {
                DBIPermission.READ,
                DBIPermission.SUBMIT_ANALYSIS,
            }
        ),
    )
    return context, farm_id, plot_id


def validate_allowed_chain() -> None:
    """Comprueba los cuatro niveles autorizados."""

    context, farm_id, plot_id = _context()

    assert (
        DBIAuthorizationPolicy.require_tenant(
            context,
            tenant_ref="tenant-001",
            permission=DBIPermission.READ,
        )
        is None
    )
    assert (
        DBIAuthorizationPolicy.require_organization(
            context,
            tenant_ref="tenant-001",
            organization_ref="organization-001",
            permission=DBIPermission.READ,
        )
        is None
    )
    assert (
        DBIAuthorizationPolicy.require_farm(
            context,
            tenant_ref="tenant-001",
            organization_ref="organization-001",
            farm_id=farm_id,
            permission=DBIPermission.READ,
        )
        is None
    )
    assert (
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref="tenant-001",
            organization_ref="organization-001",
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.SUBMIT_ANALYSIS,
        )
        is None
    )


def _assert_denied(operation: Callable[[], None]) -> None:
    try:
        operation()
    except DBIAccessDenied as error:
        assert type(error) is DBIAccessDenied
        assert str(error) == DENIED_MESSAGE
    else:
        raise AssertionError("La política permitió un ámbito no autorizado.")


def validate_default_denials() -> None:
    """Comprueba permiso y ámbitos ajenos con el mismo error."""

    context, farm_id, plot_id = _context()
    denied_operations = (
        lambda: DBIAuthorizationPolicy.require_tenant(
            context,
            tenant_ref="tenant-001",
            permission=DBIPermission.WRITE,
        ),
        lambda: DBIAuthorizationPolicy.require_tenant(
            context,
            tenant_ref="tenant-other",
            permission=DBIPermission.READ,
        ),
        lambda: DBIAuthorizationPolicy.require_organization(
            context,
            tenant_ref="tenant-001",
            organization_ref="organization-other",
            permission=DBIPermission.READ,
        ),
        lambda: DBIAuthorizationPolicy.require_farm(
            context,
            tenant_ref="tenant-001",
            organization_ref="organization-001",
            farm_id=uuid4(),
            permission=DBIPermission.READ,
        ),
        lambda: DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref="tenant-001",
            organization_ref="organization-001",
            farm_id=farm_id,
            plot_id=uuid4(),
            permission=DBIPermission.READ,
        ),
        lambda: DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref="tenant-001",
            organization_ref="organization-other",
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.READ,
        ),
        lambda: DBIAuthorizationPolicy.require_tenant(
            context,
            tenant_ref="*",
            permission=DBIPermission.READ,
        ),
        lambda: DBIAuthorizationPolicy.require_tenant(
            context,
            tenant_ref="tenant-001",
            permission="read",  # type: ignore[arg-type]
        ),
    )

    for operation in denied_operations:
        _assert_denied(operation)


def _assert_invalid(factory: Callable[[], object]) -> None:
    try:
        factory()
    except (TypeError, ValueError):
        return
    raise AssertionError("El contexto aceptó un valor inválido.")


def validate_context_invariants() -> None:
    """Comprueba identidad, comodines, tipos y cadena de pertenencia."""

    farm_id = uuid4()
    plot_id = uuid4()
    invalid_factories = (
        lambda: DBIAccessContext(
            principal_ref="",
            tenant_ref="tenant-001",
        ),
        lambda: DBIAccessContext(
            principal_ref="user-001",
            tenant_ref=" ",
        ),
        lambda: DBIAccessContext(
            principal_ref="user-001",
            tenant_ref="*",
        ),
        lambda: DBIAccessContext(
            principal_ref="user-001",
            tenant_ref="tenant-001",
            organization_refs=frozenset({"ANY"}),
        ),
        lambda: DBIAccessContext(
            principal_ref="user-001",
            tenant_ref="tenant-001",
            permissions=frozenset({"read"}),  # type: ignore[arg-type]
        ),
        lambda: DBIAccessContext(
            principal_ref="user-001",
            tenant_ref="tenant-001",
            organization_refs=frozenset({"organization-001"}),
            farm_scopes=frozenset(
                {
                    DBIFarmScope(
                        organization_ref="organization-other",
                        farm_id=farm_id,
                    )
                }
            ),
        ),
        lambda: DBIAccessContext(
            principal_ref="user-001",
            tenant_ref="tenant-001",
            organization_refs=frozenset({"organization-001"}),
            plot_scopes=frozenset(
                {
                    DBIPlotScope(
                        organization_ref="organization-001",
                        farm_id=farm_id,
                        plot_id=plot_id,
                    )
                }
            ),
        ),
        lambda: DBIFarmScope(
            organization_ref="organization-001",
            farm_id="not-a-uuid",  # type: ignore[arg-type]
        ),
    )

    for factory in invalid_factories:
        _assert_invalid(factory)


def validate_immutability() -> None:
    """Comprueba copia defensiva e inmutabilidad del contexto."""

    organizations = {"organization-001"}
    permissions = {DBIPermission.READ}
    context = DBIAccessContext(
        principal_ref="user-001",
        tenant_ref="tenant-001",
        organization_refs=organizations,  # type: ignore[arg-type]
        permissions=permissions,  # type: ignore[arg-type]
    )

    organizations.add("organization-other")
    permissions.add(DBIPermission.MANAGE)
    assert context.organization_refs == frozenset({"organization-001"})
    assert context.permissions == frozenset({DBIPermission.READ})

    try:
        context.tenant_ref = "tenant-other"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("El contexto DBI no es inmutable.")


def validate_source_boundaries() -> None:
    """Bloquea integración, sesiones, infraestructura y efectos laterales."""

    source = (
        BACKEND_ROOT / "app" / "dbi" / "authorization.py"
    ).read_text(encoding="utf-8").lower()

    for forbidden in (
        "fastapi",
        "sqlalchemy",
        "app.core.security",
        "app.models.user",
        "app.models.company",
        "app.db.session",
        "app.db.dbi_session",
        "app.dbi.repositories",
        "create_engine",
        "sessionmaker",
        ".connect(",
        ".execute(",
        ".commit(",
        ".rollback(",
        "depends(",
        "httpexception",
        "decode_token",
        "celery",
        "redis",
        "rabbit",
        "boto",
        "google.cloud.storage",
        "run_full_pipeline",
    ):
        assert forbidden not in source


def main() -> None:
    """Ejecuta todas las barreras de autorización DBI offline."""

    validate_allowed_chain()
    validate_default_denials()
    validate_context_invariants()
    validate_immutability()
    validate_source_boundaries()
    print("Autorización DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
