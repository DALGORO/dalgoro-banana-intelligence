"""Ciclo de vida explícito de recursos DBI para FastAPI."""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from app.db.dbi_config import (
    DBI_DATABASE_URL_ENV_VAR,
    DBI_ENVIRONMENT_ENV_VAR,
    DBIDatabaseConfigurationError,
    load_dbi_database_config,
)
from app.db.dbi_session import (
    DBISessionFactory,
    create_dbi_engine,
    create_dbi_session_factory,
)


class DBIRuntimeUnavailable(RuntimeError):
    """Indica que los recursos DBI no están habilitados en este proceso."""


@dataclass
class DBIRuntime:
    """Administra motor y fábrica DBI sin efectos laterales al importar."""

    engine: Engine | None = None
    session_factory: DBISessionFactory | None = None

    def start(self) -> None:
        """Inicializa recursos solo cuando el ambiente DBI está configurado."""

        if self.engine is not None or self.session_factory is not None:
            raise RuntimeError("El runtime DBI ya fue iniciado.")

        environment = os.environ.get(DBI_ENVIRONMENT_ENV_VAR, "").strip()
        database_url = os.environ.get(DBI_DATABASE_URL_ENV_VAR, "").strip()
        if not environment and not database_url:
            return
        if not environment or not database_url:
            raise DBIDatabaseConfigurationError(
                "La configuración DBI debe declarar ambiente y URL conjuntamente."
            )

        config = load_dbi_database_config()
        engine = create_dbi_engine(config)
        self.engine = engine
        self.session_factory = create_dbi_session_factory(engine)

    def stop(self) -> None:
        """Libera el motor sin afectar la sesión o motor heredados."""

        engine = self.engine
        self.session_factory = None
        self.engine = None
        if engine is not None:
            engine.dispose()

    def require_session_factory(self) -> DBISessionFactory:
        """Entrega la fábrica activa o falla de forma cerrada."""

        if self.session_factory is None:
            raise DBIRuntimeUnavailable(
                "Los recursos DBI no están disponibles en este ambiente."
            )
        return self.session_factory
