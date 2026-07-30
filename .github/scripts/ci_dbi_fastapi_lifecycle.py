"""Valida el ciclo de vida DBI en FastAPI completamente offline."""

from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# La dependencia de autenticación heredada valida estas variables al importarse.
# Se fijan valores locales antes de importar la aplicación; no se usan para abrir
# conexiones y no sustituyen la configuración DBI aislada que valida este script.
os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_fastapi_lifecycle.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-fastapi-lifecycle-secret")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.dependencies import (  # noqa: E402
    DBI_UNAVAILABLE_DETAIL,
    get_dbi_session,
)
from app.dbi.runtime import DBIRuntime  # noqa: E402
from app.main import app  # noqa: E402


class RecordingEngine:
    """Motor doble que permite comprobar su disposición sin conexión."""

    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


class RecordingSession:
    """Sesión doble para validar rollback y cierre."""

    def __init__(self) -> None:
        self.rollback_calls = 0
        self.close_calls = 0

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class RecordingFactory:
    """Fábrica doble que registra las sesiones creadas."""

    def __init__(self) -> None:
        self.sessions: list[RecordingSession] = []

    def __call__(self) -> RecordingSession:
        session = RecordingSession()
        self.sessions.append(session)
        return session


def _request(runtime: DBIRuntime) -> Request:
    application = SimpleNamespace(state=SimpleNamespace(dbi_runtime=runtime))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "app": application,
        }
    )


def validate_import_and_unconfigured_healthcheck() -> None:
    """La importación y el healthcheck no exigen configuración DBI."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DBI_ENVIRONMENT", "DBI_DATABASE_URL"}
    }
    with patch.dict(os.environ, environment, clear=True):
        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200
            assert "funcionando correctamente" in response.json()["message"]
            runtime = client.app.state.dbi_runtime
            assert runtime.engine is None
            assert runtime.session_factory is None


def validate_configured_lifecycle_without_connection() -> None:
    """El lifespan crea y dispone recursos usando fábricas inyectadas."""

    engine = RecordingEngine()
    factory = RecordingFactory()
    environment = {
        "DBI_ENVIRONMENT": "test",
        "DBI_DATABASE_URL": (
            "postgresql+psycopg://dbi_user:dbi-password"
            "@example.internal:5432/dbi_test"
        ),
    }
    with patch.dict(os.environ, environment, clear=True):
        with patch(
            "app.dbi.runtime.create_dbi_engine",
            return_value=engine,
        ) as create_engine:
            with patch(
                "app.dbi.runtime.create_dbi_session_factory",
                return_value=factory,
            ) as create_factory:
                with TestClient(app) as client:
                    runtime = client.app.state.dbi_runtime
                    assert runtime.engine is engine
                    assert runtime.session_factory is factory
                    assert create_engine.call_count == 1
                    assert create_factory.call_count == 1
                assert engine.dispose_calls == 1
                assert runtime.engine is None
                assert runtime.session_factory is None


def validate_session_dependency_cleanup() -> None:
    """La dependencia cierra siempre y revierte ante excepción."""

    factory = RecordingFactory()
    runtime = DBIRuntime(
        engine=RecordingEngine(),
        session_factory=factory,  # type: ignore[arg-type]
    )

    successful = get_dbi_session(_request(runtime))
    session = next(successful)
    assert session is factory.sessions[0]
    try:
        next(successful)
    except StopIteration:
        pass
    else:
        raise AssertionError("La dependencia debía finalizar.")
    assert factory.sessions[0].rollback_calls == 0
    assert factory.sessions[0].close_calls == 1

    failing = get_dbi_session(_request(runtime))
    next(failing)
    try:
        failing.throw(RuntimeError("fallo controlado"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("La excepción debía propagarse.")
    assert factory.sessions[1].rollback_calls == 1
    assert factory.sessions[1].close_calls == 1


def validate_unavailable_dependency() -> None:
    """Un runtime no configurado falla cerrado y sin crear sesiones."""

    generator = get_dbi_session(_request(DBIRuntime()))
    try:
        next(generator)
    except HTTPException as error:
        assert error.status_code == 503
        assert error.detail == DBI_UNAVAILABLE_DETAIL
    else:
        raise AssertionError("DBI no configurado debía responder 503.")


def validate_static_boundaries() -> None:
    """Confirma separación estática respecto del dominio heredado."""

    dependencies_source = inspect.getsource(
        sys.modules["app.dbi.dependencies"]
    )
    runtime_source = inspect.getsource(sys.modules["app.dbi.runtime"])
    main_source = inspect.getsource(sys.modules["app.main"])

    for forbidden_import in (
        "app.models.user",
        "app.models.company",
        "from app.db.session",
    ):
        assert forbidden_import not in dependencies_source
        assert forbidden_import not in runtime_source

    legacy_database_url = re.compile(
        r"(?<![A-Z0-9_])DATABASE_URL(?![A-Z0-9_])"
    )
    assert legacy_database_url.search(dependencies_source) is None
    assert legacy_database_url.search(runtime_source) is None
    assert "DBI_DATABASE_URL_ENV_VAR" in runtime_source

    assert "lifespan=lifespan" in main_source
    assert "DBIRuntime()" in main_source
    assert "include_router" in main_source
    assert "SessionLocal" in main_source


if __name__ == "__main__":
    validate_import_and_unconfigured_healthcheck()
    validate_configured_lifecycle_without_connection()
    validate_session_dependency_cleanup()
    validate_unavailable_dependency()
    validate_static_boundaries()
    print("Ciclo de vida DBI en FastAPI validado offline.")
