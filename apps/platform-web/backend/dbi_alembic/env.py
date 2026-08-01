"""Entorno Alembic independiente para DALGORO Banana Intelligence."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.db.dbi_base import DBIBase
from app.db.dbi_config import load_dbi_database_config
from app.dbi import models as dbi_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = DBIBase.metadata
VERSION_TABLE = "alembic_version_dbi"


def run_migrations_offline() -> None:
    """Genera SQL sin abrir una conexión."""

    dbi_config = load_dbi_database_config()
    config.set_main_option(
        "sqlalchemy.url",
        dbi_config.render_url().replace("%", "%%"),
    )
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        version_table=VERSION_TABLE,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Ejecuta migraciones únicamente sobre una conexión externa controlada."""

    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError(
            "Las migraciones DBI online requieren una conexión externa controlada."
        )

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        version_table=VERSION_TABLE,
    )

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
