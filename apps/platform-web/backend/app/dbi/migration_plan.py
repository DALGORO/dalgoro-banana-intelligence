"""Generación segura del plan Alembic DBI en modo estrictamente offline."""

from __future__ import annotations

import os
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Iterator, Mapping

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.dbi_config import (
    DBI_DATABASE_URL_ENV_VAR,
    DBI_ENVIRONMENT_ENV_VAR,
    DBIDatabaseConfig,
)
from app.dbi.migration_control import (
    DBIMigrationControlError,
    DBIMigrationTarget,
    plan_fingerprint,
    validate_migration_target,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DBI_ALEMBIC_INI = BACKEND_ROOT / "dbi_alembic.ini"


@dataclass(frozen=True)
class DBIMigrationPlan:
    """Evidencia reproducible de un plan que todavía no fue aplicado."""

    target: DBIMigrationTarget
    head_revision: str
    fingerprint: str
    sql: str


@contextmanager
def _temporary_environment(values: Mapping[str, str]) -> Iterator[None]:
    """Aplica variables DBI temporalmente y restaura el proceso al terminar."""

    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def generate_offline_plan(
    config: DBIDatabaseConfig,
    *,
    running_in_ci: bool,
    alembic_ini: Path = DBI_ALEMBIC_INI,
) -> DBIMigrationPlan:
    """Genera ``upgrade head --sql`` sin abrir conexiones ni ejecutar sentencias."""

    target = validate_migration_target(config, running_in_ci=running_in_ci)
    alembic_config = Config(str(alembic_ini))
    scripts = ScriptDirectory.from_config(alembic_config)
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise DBIMigrationControlError(
            "El historial Alembic DBI debe tener exactamente una cabeza."
        )

    output = StringIO()
    environment = {
        DBI_ENVIRONMENT_ENV_VAR: config.environment,
        DBI_DATABASE_URL_ENV_VAR: config.render_url(),
    }
    with _temporary_environment(environment), redirect_stdout(output):
        command.upgrade(alembic_config, "head", sql=True)

    sql = output.getvalue().replace("\r\n", "\n").replace("\r", "\n")
    if not sql.strip():
        raise DBIMigrationControlError("Alembic no generó SQL para el plan DBI.")

    rendered_url = config.render_url()
    password = config.url.password
    if rendered_url in sql or (password and password in sql):
        raise DBIMigrationControlError(
            "El plan offline contiene información sensible de conexión."
        )

    return DBIMigrationPlan(
        target=target,
        head_revision=heads[0],
        fingerprint=plan_fingerprint(sql),
        sql=sql,
    )
