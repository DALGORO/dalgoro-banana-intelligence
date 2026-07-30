"""Orquestación cerrada para una futura aplicación de migraciones DBI.

Este módulo no crea motores ni invoca Alembic directamente. Recibe una conexión ya
abierta y una operación ``upgrade_head`` inyectada. La operación solo puede
intentarse en CI, contra ``test`` y mediante un host local o loopback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Collection, Protocol

from app.db.dbi_config import DBIDatabaseConfig
from app.dbi.migration_control import (
    DBIMigrationControlError,
    DBIMigrationTarget,
    require_apply_confirmation,
    validate_migration_target,
)
from app.dbi.migration_lock import migration_lock
from app.dbi.migration_plan import DBIMigrationPlan, generate_offline_plan
from app.dbi.migration_preflight import (
    DBIMigrationPreflight,
    run_migration_preflight,
)

DBI_LOCAL_APPLY_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class DBIMigrationApplyConnection(Protocol):
    """Contrato mínimo compartido por preflight y advisory lock."""

    def execute(self, statement, parameters=None): ...


UpgradeHeadOperation = Callable[[DBIMigrationApplyConnection], None]


@dataclass(frozen=True)
class DBIMigrationApplyResult:
    """Evidencia no sensible de una operación controlada."""

    target: DBIMigrationTarget
    plan: DBIMigrationPlan
    before: DBIMigrationPreflight
    after: DBIMigrationPreflight
    applied: bool


def _validate_apply_scope(
    config: DBIDatabaseConfig,
    *,
    running_in_ci: bool,
) -> DBIMigrationTarget:
    """Restringe ``apply`` a CI, ambiente test y host local."""

    if not running_in_ci:
        raise DBIMigrationControlError(
            "Apply DBI solo está habilitado dentro de CI controlada."
        )

    target = validate_migration_target(config, running_in_ci=True)
    host = (config.url.host or "").strip().lower()
    if host not in DBI_LOCAL_APPLY_HOSTS:
        raise DBIMigrationControlError(
            "Apply DBI solo puede usar una instancia PostgreSQL local o loopback."
        )
    return target


def apply_migrations_controlled(
    config: DBIDatabaseConfig,
    connection: DBIMigrationApplyConnection,
    *,
    confirmation: str | None,
    running_in_ci: bool,
    known_revisions: Collection[str],
    head_revision: str,
    upgrade_head: UpgradeHeadOperation,
) -> DBIMigrationApplyResult:
    """Orquesta plan, preflight, lock, operación única y postflight.

    La operación externa se omite cuando la base ya está en la cabeza aprobada.
    Cuando se ejecuta, el postflight debe confirmar exactamente ``head_revision``.
    """

    target = _validate_apply_scope(config, running_in_ci=running_in_ci)
    require_apply_confirmation(target, confirmation)
    plan = generate_offline_plan(config, running_in_ci=True)
    if plan.head_revision != head_revision:
        raise DBIMigrationControlError(
            "La cabeza del plan offline no coincide con la cabeza autorizada."
        )

    before = run_migration_preflight(
        connection,
        target=target,
        known_revisions=known_revisions,
        head_revision=head_revision,
    )

    with migration_lock(connection):
        locked_before = run_migration_preflight(
            connection,
            target=target,
            known_revisions=known_revisions,
            head_revision=head_revision,
        )
        if locked_before.is_at_head:
            return DBIMigrationApplyResult(
                target=target,
                plan=plan,
                before=before,
                after=locked_before,
                applied=False,
            )

        upgrade_head(connection)

        after = run_migration_preflight(
            connection,
            target=target,
            known_revisions=known_revisions,
            head_revision=head_revision,
        )
        if not after.is_at_head:
            raise DBIMigrationControlError(
                "El postflight DBI no confirmó la cabeza Alembic autorizada."
            )

        return DBIMigrationApplyResult(
            target=target,
            plan=plan,
            before=before,
            after=after,
            applied=True,
        )
