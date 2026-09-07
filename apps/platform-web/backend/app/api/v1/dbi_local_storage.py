"""Transporte HTTP para grants temporales del almacenamiento DBI local."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.dbi.storage_contracts import (
    DBIStorageAccessMode,
    DBIStorageConflict,
    DBIStorageError,
    DBIStorageIntegrityError,
    DBIStorageNotFound,
    DBIStorageWriteRequest,
)
from app.dbi.storage_local import DBILocalObjectStore


router = APIRouter(
    prefix="/dbi/local-storage/grants",
    tags=["dbi-local-storage"],
)


def get_local_store(request: Request) -> DBILocalObjectStore:
    store = getattr(request.app.state, "dbi_object_store", None)
    if not isinstance(store, DBILocalObjectStore):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El almacenamiento local DBI no está disponible.",
        )
    return store


StoreDependency = Annotated[DBILocalObjectStore, Depends(get_local_store)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Grant DBI no disponible.")


@router.put("/{grant_ref}", status_code=status.HTTP_204_NO_CONTENT)
async def upload_local_object(
    grant_ref: str,
    request: Request,
    store: StoreDependency,
) -> Response:
    """Recibe por streaming un objeto autorizado por un grant WRITE efímero."""

    try:
        access = store.resolve_temporary_access(grant_ref)
    except DBIStorageNotFound as error:
        raise _not_found() from error

    if access.grant.mode is not DBIStorageAccessMode.WRITE or access.method != "PUT":
        raise _not_found()

    expected = access.grant.metadata
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type and content_type != expected.content_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El Content-Type no coincide con el grant DBI.",
        )

    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) != expected.size_bytes:
                raise ValueError
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El tamaño HTTP no coincide con el grant DBI.",
            ) from error

    temp_path: Path | None = None
    total = 0
    try:
        with NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=store.staging_directory,
            prefix="http-upload-",
            suffix=".part",
        ) as temporary:
            temp_path = Path(temporary.name)
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > expected.size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="La carga excede el tamaño autorizado.",
                    )
                temporary.write(chunk)

        if total != expected.size_bytes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La carga quedó incompleta.",
            )

        with temp_path.open("rb") as content:
            store.put(DBIStorageWriteRequest(metadata=expected), content)
    except HTTPException:
        raise
    except (DBIStorageConflict, DBIStorageIntegrityError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La carga no coincide con la identidad declarada.",
        ) from error
    except DBIStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El almacenamiento local DBI no pudo completar la carga.",
        ) from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{grant_ref}")
def download_local_object(
    grant_ref: str,
    store: StoreDependency,
) -> StreamingResponse:
    """Entrega por streaming un objeto autorizado por un grant READ efímero."""

    try:
        access = store.resolve_temporary_access(grant_ref)
    except DBIStorageNotFound as error:
        raise _not_found() from error

    if access.grant.mode is not DBIStorageAccessMode.READ or access.method != "GET":
        raise _not_found()

    metadata = access.grant.metadata

    def body():
        try:
            with store.open_read(metadata.address) as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
        except DBIStorageError:
            return

    return StreamingResponse(
        body(),
        media_type=metadata.content_type,
        headers={
            "Content-Length": str(metadata.size_bytes),
            "Cache-Control": "private, no-store",
        },
    )
