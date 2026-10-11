"""Selección explícita de storage privado DBI, sin credenciales implícitas.

El almacén heredado local sigue igual en desarrollo. Para Render/staging/producción
solo se permite S3 opt-in, bajo HTTPS, sin fallbacks a disco efímero.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Mapping

from app.dbi.storage_local import DBILocalObjectStore
from app.dbi.storage_s3 import DBIS3ObjectStore, DBIS3ObjectStoreConfig


class DBIStorageBootstrapError(RuntimeError):
    """No incluye nunca URLs, llaves, credenciales ni tokens en el mensaje."""


def s3_config_from_environment(values: Mapping[str, str] | None = None) -> DBIS3ObjectStoreConfig:
    source = os.environ if values is None else values
    required = {
        "DBI_S3_ENDPOINT_URL": "endpoint_url",
        "DBI_S3_BUCKET": "bucket",
        "DBI_S3_REGION": "region",
        "DBI_S3_ACCESS_KEY_ID": "access_key_id",
        "DBI_S3_SECRET_ACCESS_KEY": "secret_access_key",
    }
    if any(not source.get(env, "").strip() for env in required):
        raise DBIStorageBootstrapError("Faltan variables de configuración S3 privadas DBI.")
    if source.get("DBI_LOCAL_STORAGE_ROOT", "").strip():
        raise DBIStorageBootstrapError("No mezcles almacenamiento S3 y local DBI.")
    endpoint = source["DBI_S3_ENDPOINT_URL"].strip()
    # En producción nunca se usan los permisos de excepción loopback del
    # proveedor de pruebas: el endpoint debe ser HTTPS incluso en redes internas.
    if not endpoint.startswith("https://"):
        raise DBIStorageBootstrapError("El almacenamiento privado S3 exige HTTPS.")
    try:
        return DBIS3ObjectStoreConfig(
            endpoint_url=endpoint,
            bucket=source["DBI_S3_BUCKET"].strip(),
            region=source["DBI_S3_REGION"].strip(),
            access_key_id=source["DBI_S3_ACCESS_KEY_ID"],
            secret_access_key=source["DBI_S3_SECRET_ACCESS_KEY"],
            session_token=source.get("DBI_S3_SESSION_TOKEN") or None,
            verify_tls=True,
            max_object_size_bytes=64 * 1024 * 1024,
        )
    except (ValueError, TypeError) as error:
        # No filtrar el input incorrecto: puede contener secretos.
        raise DBIStorageBootstrapError("La configuración privada S3 DBI es inválida.") from None


def create_configured_object_store(
    values: Mapping[str, str] | None = None,
    *,
    s3_factory: Callable[[DBIS3ObjectStoreConfig], object] = DBIS3ObjectStore,
    local_factory: Callable[[Path], object] = DBILocalObjectStore,
) -> object | None:
    source = os.environ if values is None else values
    environment = source.get("DBI_ENVIRONMENT", "").strip().lower()
    backend = source.get("DBI_STORAGE_BACKEND", "").strip().lower()
    local_root = source.get("DBI_LOCAL_STORAGE_ROOT", "").strip()

    if backend not in {"", "local", "s3"}:
        raise DBIStorageBootstrapError("DBI_STORAGE_BACKEND debe ser local o s3.")
    if backend == "s3":
        if environment not in {"development", "test", "staging", "production"}:
            raise DBIStorageBootstrapError("Declara el ambiente DBI antes de habilitar S3.")
        return s3_factory(s3_config_from_environment(source))

    if backend == "local" and environment not in {"development", "test", "local"}:
        raise DBIStorageBootstrapError("El backend local está prohibido fuera de desarrollo.")
    if environment in {"production", "staging"}:
        if local_root:
            raise DBIStorageBootstrapError("No se admite storage efímero/local en despliegues DBI.")
        # Sin opt-in el portal solo responde 503 a operaciones de objetos privados.
        return None
    if local_root:
        path = Path(local_root).expanduser()
        if not path.is_absolute():
            raise DBIStorageBootstrapError("DBI_LOCAL_STORAGE_ROOT debe ser absoluta.")
        return local_factory(path)
    if environment in {"development", "local"}:
        appdata = source.get("LOCALAPPDATA", "").strip()
        if appdata:
            return local_factory(Path(appdata) / "DALGORO" / "DBI" / "storage")
    if backend == "local":
        raise DBIStorageBootstrapError("No existe raíz persistente de almacenamiento DBI.")
    return None
