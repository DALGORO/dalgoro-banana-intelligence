from datetime import timedelta
from typing import BinaryIO
import mimetypes
import uuid

from google.cloud import storage
from google.oauth2 import service_account

from app.core.config import settings

from pathlib import Path
import os


def _get_gcs_client() -> storage.Client:
    if not settings.GCS_CREDENTIALS_JSON:
        raise RuntimeError("GCS_CREDENTIALS_JSON no está configurado en .env")
    creds = service_account.Credentials.from_service_account_file(settings.GCS_CREDENTIALS_JSON)
    return storage.Client(credentials=creds, project=creds.project_id)

def _get_bucket(client: storage.Client):
    if not settings.GCS_BUCKET:
        raise RuntimeError("GCS_BUCKET no está configurado en .env")
    return client.bucket(settings.GCS_BUCKET)

def generate_path(user_id: int, company_id: int, doc_type: str, filename: str) -> str:
    safe = filename.replace(" ", "_")
    return f"user_{user_id}/company_{company_id}/{doc_type}/{uuid.uuid4()}_{safe}"

def upload_file(file_data: BinaryIO, filename: str, user_id: int, company_id: int, doc_type: str) -> str:
    client = _get_gcs_client()
    bucket = _get_bucket(client)
    blob_path = generate_path(user_id, company_id, doc_type, filename)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    blob = bucket.blob(blob_path)
    blob.upload_from_file(file_data, content_type=content_type)
    # Mantener privado por defecto
    return blob_path

def get_signed_url(blob_path: str, hours: int | None = None) -> str:
    client = _get_gcs_client()
    bucket = _get_bucket(client)
    blob = bucket.blob(blob_path)
    expiration = timedelta(hours=hours or settings.GCS_SIGNED_URL_EXPIRATION_HOURS)
    return blob.generate_signed_url(expiration=expiration, version="v4")

def delete_file(blob_path: str) -> bool:
    client = _get_gcs_client()
    bucket = _get_bucket(client)
    blob = bucket.blob(blob_path)
    blob.delete()
    return True

# === NUEVO: helper para obtener bytes de un PDF desde storage ===
def get_pdf_bytes(path: str) -> bytes:
    """
    Descarga bytes del PDF desde:
    1) GCS (si el path es un blob key válido en el bucket configurado)
    2) HTTP(S), si path es URL (por ejemplo, firmada)
    3) Disco local, si path es ruta de archivo
    """
    # 1) Intento GCS (blob path relativo, p.ej. "user_1/company_2/PPRL/uuid_file.pdf")
    try:
        client = _get_gcs_client()
        bucket = _get_bucket(client)
        blob = bucket.blob(path)
        if blob.exists():
            return blob.download_as_bytes()
    except Exception:
        # Si GCS no está configurado o el blob no existe, seguimos a fallback
        pass

    # 2) HTTP(S)
    if path.startswith("http://") or path.startswith("https://"):
        import requests
        r = requests.get(path, timeout=10)
        r.raise_for_status()
        return r.content

    # 3) Local
    import os
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()

    # Si nada funcionó:
    raise FileNotFoundError(f"No se pudo obtener bytes del PDF desde '{path}'")

# al final del archivo (o dentro de StorageService si ya manejas rutas base)

def save_bytes(*, company_id: int, filename: str, content: bytes, user_id: int = 0, doc_type: str = "DOCS") -> str:
    """
    Guarda bytes en GCS si hay credenciales; si no, en disco local.
    Retorna la 'ruta lógica': blob path en GCS o ruta absoluta local.
    """
    import mimetypes, os

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    # 1) Intento GCS
    try:
        client = _get_gcs_client()
        bucket = _get_bucket(client)
        blob_path = generate_path(user_id, company_id, doc_type, filename)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(content, content_type=content_type)
        return blob_path
    except Exception:
        pass

    # 2) Fallback local
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage"))
    subpath = os.path.join(f"company_{company_id}", doc_type, filename)
    abs_path = os.path.join(base_dir, subpath)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(content)
    return abs_path

def save_text_bytes(base_dir: str, subpath: str, content: str) -> str:
    """
    Guarda contenido de texto en un archivo utf-8 y retorna la ruta absoluta.
    base_dir: carpeta base del storage (config)
    subpath: ruta relativa (p.ej. 'companies/4/INV-ACC-01-2025-001.txt')
    """
    import os
    os.makedirs(os.path.join(base_dir, os.path.dirname(subpath)), exist_ok=True)
    abs_path = os.path.join(base_dir, subpath)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return abs_path

def delete_storage_path(storage_path: str) -> bool:
    """
    Borra el binario indicado por storage_path.
    - Si hay GCS y el path es un blob válido, borra en GCS.
    - Si es una ruta local existente, borra en disco.
    No lanza excepción. Retorna True si parece haber borrado (o no existía).
    """
    # 1) intento GCS
    try:
        client = _get_gcs_client()
        bucket = _get_bucket(client)
        blob = bucket.blob(storage_path)
        if blob.exists():
            blob.delete()
            return True
    except Exception:
        # seguimos a fallback local
        pass

    # 2) fallback local
    try:
        p = Path(storage_path)
        if not p.is_absolute():
            # resolver ruta relativa a <root>/storage (igual que save_bytes)
            base_dir = Path(__file__).resolve().parents[2] / "storage"
            p = base_dir / storage_path

        if p.exists():
            os.remove(p)
        return True
    except Exception:
        return False


def get_bytes_any(path: str) -> bytes:
    """
    Descarga bytes desde:
    1) GCS (si el path es un blob key válido)
    2) HTTP(S) si path es URL
    3) Disco local si es ruta de archivo
    """
    # 1) GCS
    try:
        client = _get_gcs_client()
        bucket = _get_bucket(client)
        blob = bucket.blob(path)
        if blob.exists():
            return blob.download_as_bytes()
    except Exception:
        pass

    # 2) HTTP(S)
    if path.startswith("http://") or path.startswith("https://"):
        import requests
        r = requests.get(path, timeout=10)
        r.raise_for_status()
        return r.content

    # 3) Local
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()

    raise FileNotFoundError(f"No se pudo obtener bytes desde '{path}'")
