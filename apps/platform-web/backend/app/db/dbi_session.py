"""Fábrica explícita y aislada de sesiones DBI."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeAlias

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.dbi_config import (
    DBIDatabaseConfig,
    load_dbi_database_config,
)

DBISessionFactory: TypeAlias = sessionmaker[Session]


def create_dbi_engine(
    config: DBIDatabaseConfig | None = None,
) -> Engine:
    """Crea un motor DBI diferido a partir de configuración validada.

    Construir el motor no abre una conexión. El llamador conserva la
    responsabilidad de disponerlo cuando termine el ciclo de vida autorizado.
    """

    validated_config = config or load_dbi_database_config()
    return create_engine(
        validated_config.url,
        pool_pre_ping=True,
    )


def create_dbi_session_factory(
    engine: Engine,
) -> DBISessionFactory:
    """Crea una fábrica ligada exclusivamente al motor DBI recibido."""

    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def dbi_session_scope(
    session_factory: DBISessionFactory,
) -> Iterator[Session]:
    """Gestiona una transacción DBI con cierre garantizado."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
