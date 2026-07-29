"""Valida la fábrica DBI sin abrir conexiones ni ejecutar migraciones."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.dbi_config import (  # noqa: E402
    DBIDatabaseConfigurationError,
    load_dbi_database_config,
)

VALID_ENVIRONMENT = {
    "DBI_ENVIRONMENT": "test",
    "DBI_DATABASE_URL": (
        "postgresql+psycopg://dbi_app:dbi-password"
        "@example.internal:5432/dbi_test"
    ),
}


class ExpectedTransactionError(RuntimeError):
    """Excepción controlada para probar rollback y propagación."""


class FakeSession:
    """Doble mínimo que registra el orden del ciclo transaccional."""

    def __init__(self, *, fail_commit: bool = False) -> None:
        self.events: list[str] = []
        self.fail_commit = fail_commit

    def commit(self) -> None:
        """Registra commit y permite simular un fallo al confirmar."""

        self.events.append("commit")
        if self.fail_commit:
            raise ExpectedTransactionError("commit rechazado")

    def rollback(self) -> None:
        """Registra rollback."""

        self.events.append("rollback")

    def close(self) -> None:
        """Registra cierre."""

        self.events.append("close")


def import_session_module():
    """Importa el módulo real después de verificar su carga diferida."""

    sys.modules.pop("app.db.dbi_session", None)
    return importlib.import_module("app.db.dbi_session")


def validate_lazy_import() -> None:
    """Comprueba que importar no cree motor, fábrica o conexión."""

    sys.modules.pop("app.db.dbi_session", None)
    with (
        patch("sqlalchemy.create_engine") as engine_constructor,
        patch("sqlalchemy.orm.sessionmaker") as session_constructor,
    ):
        importlib.import_module("app.db.dbi_session")

    engine_constructor.assert_not_called()
    session_constructor.assert_not_called()


def validate_engine_factory() -> None:
    """Comprueba URL validada y construcción sin solicitar conexión."""

    session_module = import_session_module()
    config = load_dbi_database_config(VALID_ENVIRONMENT)
    engine_sentinel = object()

    with patch.object(
        session_module,
        "create_engine",
        return_value=engine_sentinel,
    ) as engine_constructor:
        engine = session_module.create_dbi_engine(config)

    assert engine is engine_sentinel
    engine_constructor.assert_called_once_with(
        config.url,
        pool_pre_ping=True,
    )

    with (
        patch.object(
            session_module,
            "load_dbi_database_config",
            return_value=config,
        ) as config_loader,
        patch.object(
            session_module,
            "create_engine",
            return_value=engine_sentinel,
        ),
    ):
        assert session_module.create_dbi_engine() is engine_sentinel

    config_loader.assert_called_once_with()


def validate_invalid_configuration_stops_engine() -> None:
    """Impide crear el motor cuando la configuración no es DBI."""

    session_module = import_session_module()
    with (
        patch.dict(
            "os.environ",
            {"DATABASE_URL": "sqlite+pysqlite:///:memory:"},
            clear=True,
        ),
        patch.object(session_module, "create_engine") as engine_constructor,
    ):
        try:
            session_module.create_dbi_engine()
        except DBIDatabaseConfigurationError:
            pass
        else:
            raise AssertionError("La configuración heredada fue aceptada.")

    engine_constructor.assert_not_called()


def validate_session_factory() -> None:
    """Comprueba enlace explícito y opciones transaccionales."""

    session_module = import_session_module()
    engine_sentinel = object()
    factory_sentinel = object()

    with patch.object(
        session_module,
        "sessionmaker",
        return_value=factory_sentinel,
    ) as session_constructor:
        result = session_module.create_dbi_session_factory(engine_sentinel)

    assert result is factory_sentinel
    session_constructor.assert_called_once_with(
        bind=engine_sentinel,
        autoflush=False,
        expire_on_commit=False,
    )


def validate_successful_scope() -> None:
    """Confirma una sola vez y cierra después de un bloque exitoso."""

    session_module = import_session_module()
    session = FakeSession()

    with session_module.dbi_session_scope(lambda: session) as yielded:
        assert yielded is session
        assert session.events == []

    assert session.events == ["commit", "close"]


def validate_failed_scope() -> None:
    """Revierte, cierra y propaga una excepción del bloque."""

    session_module = import_session_module()
    session = FakeSession()

    try:
        with session_module.dbi_session_scope(lambda: session):
            raise ExpectedTransactionError("operación rechazada")
    except ExpectedTransactionError as error:
        assert str(error) == "operación rechazada"
    else:
        raise AssertionError("La excepción transaccional no se propagó.")

    assert session.events == ["rollback", "close"]


def validate_failed_commit() -> None:
    """Revierte y cierra cuando la propia confirmación falla."""

    session_module = import_session_module()
    session = FakeSession(fail_commit=True)

    try:
        with session_module.dbi_session_scope(lambda: session):
            pass
    except ExpectedTransactionError as error:
        assert str(error) == "commit rechazado"
    else:
        raise AssertionError("El fallo de commit no se propagó.")

    assert session.events == ["commit", "rollback", "close"]


def validate_source_boundaries() -> None:
    """Bloquea sesión heredada, conexión directa e infraestructura."""

    source = (
        BACKEND_ROOT / "app" / "db" / "dbi_session.py"
    ).read_text(encoding="utf-8").lower()

    for forbidden in (
        "app.db.session",
        "app.core.config",
        "database_url",
        "sessionlocal",
        ".connect(",
        "celery",
        "redis",
        "rabbit",
        "boto",
        "google.cloud.storage",
        "pipeline_orchestrator",
        "run_full_pipeline",
    ):
        assert forbidden not in source


def main() -> None:
    """Ejecuta todas las barreras de acceso transaccional offline."""

    validate_lazy_import()
    validate_engine_factory()
    validate_invalid_configuration_stops_engine()
    validate_session_factory()
    validate_successful_scope()
    validate_failed_scope()
    validate_failed_commit()
    validate_source_boundaries()
    print("Fábrica de sesiones DBI: validación offline aprobada.")


if __name__ == "__main__":
    main()
