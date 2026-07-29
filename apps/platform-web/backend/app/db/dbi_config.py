"""Configuración aislada de la base de datos de DALGORO Banana Intelligence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from sqlalchemy.engine import URL, make_url

DBI_DATABASE_URL_ENV_VAR = "DBI_DATABASE_URL"
DBI_ENVIRONMENT_ENV_VAR = "DBI_ENVIRONMENT"

DBI_DATABASE_NAMES = {
    "development": "dbi_development",
    "test": "dbi_test",
    "staging": "dbi_staging",
    "production": "dbi_production",
}

DBI_POSTGRESQL_DRIVERS = {
    "postgresql",
    "postgresql+psycopg",
    "postgresql+psycopg2",
}


class DBIDatabaseConfigurationError(RuntimeError):
    """Indica una configuración DBI ausente o no autorizada."""


@dataclass(frozen=True)
class DBIDatabaseConfig:
    """Configuración DBI validada, sin abrir conexiones."""

    environment: str
    url: URL

    @property
    def database_name(self) -> str:
        """Devuelve el nombre de base ya validado."""

        assert self.url.database is not None
        return self.url.database

    def render_url(self) -> str:
        """Renderiza la URL completa solo para SQLAlchemy/Alembic."""

        return self.url.render_as_string(hide_password=False)


def load_dbi_database_config(
    values: Mapping[str, str] | None = None,
) -> DBIDatabaseConfig:
    """Lee y valida exclusivamente las variables de conexión DBI.

    La función no crea motores ni intenta conectarse. ``DATABASE_URL`` se
    ignora de forma deliberada para impedir que el historial DBI reutilice la
    base heredada.
    """

    source = os.environ if values is None else values
    environment = source.get(DBI_ENVIRONMENT_ENV_VAR, "").strip().lower()

    if environment not in DBI_DATABASE_NAMES:
        allowed = ", ".join(DBI_DATABASE_NAMES)
        raise DBIDatabaseConfigurationError(
            f"{DBI_ENVIRONMENT_ENV_VAR} debe ser uno de: {allowed}."
        )

    raw_url = source.get(DBI_DATABASE_URL_ENV_VAR, "").strip()
    if not raw_url:
        raise DBIDatabaseConfigurationError(
            f"{DBI_DATABASE_URL_ENV_VAR} es obligatoria para operaciones DBI."
        )

    try:
        url = make_url(raw_url)
    except (TypeError, ValueError):
        raise DBIDatabaseConfigurationError(
            f"{DBI_DATABASE_URL_ENV_VAR} no tiene un formato válido."
        ) from None

    if url.drivername not in DBI_POSTGRESQL_DRIVERS:
        raise DBIDatabaseConfigurationError(
            f"{DBI_DATABASE_URL_ENV_VAR} debe usar PostgreSQL."
        )

    if not url.username or not url.host:
        raise DBIDatabaseConfigurationError(
            f"{DBI_DATABASE_URL_ENV_VAR} debe declarar usuario y host."
        )

    expected_database = DBI_DATABASE_NAMES[environment]
    if url.database != expected_database:
        raise DBIDatabaseConfigurationError(
            "El nombre de la base DBI no está autorizado para el ambiente."
        )

    return DBIDatabaseConfig(environment=environment, url=url)
