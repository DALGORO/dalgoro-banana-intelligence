"""Adaptador Alembic para ejecutar exclusivamente ``upgrade head`` en una conexión externa."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection

from app.dbi.migration_control import DBIMigrationControlError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DBI_ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "dbi_alembic.ini"


def upgrade_head_on_connection(connection: Connection) -> None:
    """Aplica la cabeza DBI usando exactamente la conexión recibida.

    El preflight y el advisory lock pueden haber iniciado una transacción de solo
    lectura. Se confirma esa transacción antes de entregar la misma sesión a
    Alembic; el advisory lock de sesión permanece activo a través del commit.
    """

    if connection.closed:
        raise DBIMigrationControlError(
            "La conexión DBI controlada está cerrada antes de ejecutar Alembic."
        )

    if connection.in_transaction():
        connection.commit()

    alembic_config = Config(str(DBI_ALEMBIC_CONFIG_PATH))
    alembic_config.attributes["connection"] = connection
    command.upgrade(alembic_config, "head")
