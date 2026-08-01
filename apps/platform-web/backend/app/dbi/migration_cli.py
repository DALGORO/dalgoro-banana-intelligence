"""Interfaz operativa conservadora para migraciones DALGORO Banana Intelligence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from typing import Sequence

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.db.dbi_config import (
    DBIDatabaseConfigurationError,
    DBIDatabaseConfig,
    load_dbi_database_config,
)
from app.dbi.migration_apply import (
    DBI_LOCAL_APPLY_HOSTS,
    apply_migrations_controlled,
)
from app.dbi.migration_control import (
    DBIMigrationControlError,
    require_apply_confirmation,
    require_authorized_github_actions_runtime,
    validate_migration_target,
)
from app.dbi.migration_plan import generate_offline_plan
from app.dbi.migration_preflight import run_migration_preflight
from app.dbi.migration_runner import upgrade_head_on_connection

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DBI_ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "dbi_alembic.ini"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dbi-migrations",
        description=(
            "Planifica, verifica o aplica el historial Alembic DBI con barreras "
            "de ambiente, rol y destino."
        ),
    )
    parser.add_argument(
        "operation",
        nargs="?",
        default="plan",
        choices=("plan", "verify", "apply"),
        help="Operación; el valor predeterminado es plan.",
    )
    parser.add_argument(
        "--confirm",
        help="Confirmación exacta requerida por apply: APPLY <database_name>.",
    )
    parser.add_argument(
        "--sql-output",
        type=Path,
        help=(
            "Archivo nuevo donde plan escribirá el SQL offline. No se "
            "sobrescriben archivos existentes."
        ),
    )
    return parser


def _running_in_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _migration_graph() -> tuple[set[str], str]:
    alembic_config = Config(str(DBI_ALEMBIC_CONFIG_PATH))
    scripts = ScriptDirectory.from_config(alembic_config)
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise DBIMigrationControlError(
            "El historial DBI debe tener exactamente una cabeza Alembic."
        )
    head_revision = heads[0]
    known_revisions = {
        revision.revision for revision in scripts.walk_revisions()
    }
    if head_revision not in known_revisions:
        raise DBIMigrationControlError(
            "La cabeza DBI no pertenece al linaje Alembic reconocido."
        )
    return known_revisions, head_revision


def _safe_evidence(**values) -> str:
    return json.dumps(values, sort_keys=True, ensure_ascii=False)


def _write_sql_plan(path: Path, sql_text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(sql_text)


def _plan(
    config: DBIDatabaseConfig,
    *,
    running_in_ci: bool,
    sql_output: Path | None,
) -> int:
    # Alembic puede emitir mensajes INFO por stderr aunque el plan sea válido.
    # La CLI reserva stderr para errores y mantiene la evidencia JSON en stdout.
    with redirect_stderr(StringIO()):
        plan = generate_offline_plan(config, running_in_ci=running_in_ci)
    if sql_output is not None:
        _write_sql_plan(sql_output, plan.sql)

    print(
        _safe_evidence(
            operation="plan",
            environment=plan.target.environment,
            database=plan.target.database_name,
            expected_migrator_role=plan.target.expected_migrator_role,
            head_revision=plan.head_revision,
            plan_sha256=plan.fingerprint,
            sql_output=str(sql_output) if sql_output is not None else None,
        )
    )
    return 0


def _validate_connected_scope(
    config: DBIDatabaseConfig,
    *,
    running_in_ci: bool,
):
    target = validate_migration_target(
        config,
        running_in_ci=running_in_ci,
    )
    host = (config.url.host or "").strip().lower()
    if host not in DBI_LOCAL_APPLY_HOSTS:
        raise DBIMigrationControlError(
            "Las operaciones conectadas DBI solo admiten host local o loopback."
        )

    if running_in_ci:
        if target.environment != "test":
            raise DBIMigrationControlError(
                "GitHub Actions solo puede verificar el ambiente DBI test."
            )
    elif target.environment != "development":
        raise DBIMigrationControlError(
            "Fuera de CI, verify solo está habilitado para development local."
        )
    return target


def _verify(
    config: DBIDatabaseConfig,
    *,
    running_in_ci: bool,
    known_revisions: set[str],
    head_revision: str,
) -> int:
    target = _validate_connected_scope(
        config,
        running_in_ci=running_in_ci,
    )
    engine = create_engine(config.url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            evidence = run_migration_preflight(
                connection,
                target=target,
                known_revisions=known_revisions,
                head_revision=head_revision,
            )
        print(
            _safe_evidence(
                operation="verify",
                environment=target.environment,
                database=target.database_name,
                expected_migrator_role=target.expected_migrator_role,
                head_revision=head_revision,
                current_revision=evidence.current_revision,
                database_is_empty=evidence.database_is_empty,
                is_at_head=evidence.is_at_head,
                search_path=list(evidence.search_path),
                postgis_available=evidence.postgis_available,
                dbi_schema_available=evidence.dbi_schema_available,
            )
        )
        return 0
    finally:
        engine.dispose()


def _apply(
    config: DBIDatabaseConfig,
    *,
    confirmation: str | None,
    running_in_ci: bool,
    known_revisions: set[str],
    head_revision: str,
) -> int:
    if not running_in_ci:
        raise DBIMigrationControlError(
            "Apply DBI solo está habilitado dentro de CI controlada."
        )
    require_authorized_github_actions_runtime()

    target = validate_migration_target(config, running_in_ci=True)
    host = (config.url.host or "").strip().lower()
    if host not in DBI_LOCAL_APPLY_HOSTS:
        raise DBIMigrationControlError(
            "Apply DBI solo puede usar PostgreSQL local o loopback."
        )
    require_apply_confirmation(target, confirmation)

    engine = create_engine(config.url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            result = apply_migrations_controlled(
                config,
                connection,
                confirmation=confirmation,
                running_in_ci=True,
                known_revisions=known_revisions,
                head_revision=head_revision,
                upgrade_head=upgrade_head_on_connection,
            )
        print(
            _safe_evidence(
                operation="apply",
                environment=result.target.environment,
                database=result.target.database_name,
                expected_migrator_role=result.target.expected_migrator_role,
                head_revision=result.after.head_revision,
                before_revision=result.before.current_revision,
                after_revision=result.after.current_revision,
                applied=result.applied,
                plan_sha256=result.plan.fingerprint,
            )
        )
        return 0
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_dbi_database_config()
        running_in_ci = _running_in_ci()

        if args.operation == "plan":
            if args.confirm is not None:
                raise DBIMigrationControlError(
                    "--confirm solo está permitido con la operación apply."
                )
            return _plan(
                config,
                running_in_ci=running_in_ci,
                sql_output=args.sql_output,
            )

        if args.sql_output is not None:
            raise DBIMigrationControlError(
                "--sql-output solo está permitido con la operación plan."
            )

        known_revisions, head_revision = _migration_graph()
        if args.operation == "verify":
            if args.confirm is not None:
                raise DBIMigrationControlError(
                    "--confirm solo está permitido con la operación apply."
                )
            return _verify(
                config,
                running_in_ci=running_in_ci,
                known_revisions=known_revisions,
                head_revision=head_revision,
            )

        return _apply(
            config,
            confirmation=args.confirm,
            running_in_ci=running_in_ci,
            known_revisions=known_revisions,
            head_revision=head_revision,
        )
    except (DBIDatabaseConfigurationError, DBIMigrationControlError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, SQLAlchemyError):
        print(
            "ERROR: la operación DBI no pudo completarse sin exponer detalles "
            "de conexión.",
            file=sys.stderr,
        )
        return 3
    except Exception:
        print(
            "ERROR: fallo interno de la herramienta DBI; no se muestran datos "
            "de conexión.",
            file=sys.stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
