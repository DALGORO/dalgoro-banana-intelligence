"""Selección explícita de almacén privado DBI sin fallback inseguro.

La configuración de S3 es opt-in. Ausencia de DBI_STORAGE_PROVIDER
conserva el proveedor local heredado. Configuración S3 incompleta falla
cerrada y no cambia silenciosamente a disco local.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import urlparse

from app.dbi.storage_contracts import DBIPrivateObjectStore
from app.dbi.storage_s3 import DBIS3ObjectStore, DBIS3ObjectStoreConfig

_S3_REQUIRED = (
    "DBI_S3_ENDPOINT_URL",
    "DBI_S3_BUCKET",
    "DBI_S3_REGION",
    "DBI_S3_ACCESS_KEY_ID",
    "DBI_S3_SECRET_ACCESS_KEY",
)
_LOCAL_ENVS = frozenset({"development", "local", "test"})


class DBIStorageBootstrapError(ValueError):
    """Configuración inválida; nunca expone secretos ni usa fallback local."""


def resolve_dbi_object_store(
    env: Mapping[str, str],
    local_provider: Callable[[], DBIPrivateObjectStore | None],
    *,
    s3_provider: Callable[[DBIS3ObjectStoreConfig], DBIPrivateObjectStore] = DBIS3ObjectStore,
) -> DBIPrivateObjectStore | None:
    """Inyecta dependencias para probar la selección sin abrir conexiones."""
    mode = env.get("DBI_STORAGE_PROVIDER", "").strip().lower()
    environment = env.get("DBI_ENVIRONMENT", "").strip().lower()
    if not mode:
        return local_provider()  # Compatibilidad explícita con DBI local existente.
    if mode == "disabled":
        return None
    if mode == "local":
        if environment not in _LOCAL_ENVS:
            raise DBIStorageBootstrapError(
                "DBI_STORAGE_PROVIDER=local solo admite ambientes locales/de prueba."
            )
        return local_provider()
    if mode != "s3":
        raise DBIStorageBootstrapError("DBI_STORAGE_PROVIDER no es un proveedor admitido.")

    if environment not in _LOCAL_ENVS and environment not in {"staging", "production"}:
        raise DBIStorageBootstrapError("Declara DBI_ENVIRONMENT antes de habilitar S3.")

    missing = [
        key for key in _S3_REQUIRED
        if not isinstance(env.get(key), str) or not env[key].strip()
    ]
    if missing:
        raise DBIStorageBootstrapError(
            "Faltan parámetros del almacenamiento privado S3: " + ", ".join(missing)
        )
    if not env.get("DBI_DATABASE_URL", "").strip():
        raise DBIStorageBootstrapError("S3 requiere DBI_DATABASE_URL configurado.")

    endpoint = env["DBI_S3_ENDPOINT_URL"]
    parsed = urlparse(endpoint)
    if environment in {"staging", "production"} and parsed.scheme != "https":
        raise DBIStorageBootstrapError("S3 de staging/producción exige endpoint HTTPS.")

    token = env.get("DBI_S3_SESSION_TOKEN") or None
    try:
        config = DBIS3ObjectStoreConfig(
            endpoint_url=endpoint,
            bucket=env["DBI_S3_BUCKET"],
            region=env["DBI_S3_REGION"],
            access_key_id=env["DBI_S3_ACCESS_KEY_ID"],
            secret_access_key=env["DBI_S3_SECRET_ACCESS_KEY"],
            session_token=token,
            verify_tls=True,
            max_object_size_bytes=64 * 1024 * 1024,
        )
    except ValueError as error:
        # Los errores del proveedor son de política/campos; no imprimir env.
        raise DBIStorageBootstrapError("Configuración S3 DBI rechazada por la política privada.") from error
    return s3_provider(config)
