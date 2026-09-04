"""HTTP autorizado para metadata, rangos y retiro de productos COG DBI."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.raster.api_schemas import (
    DBIRasterProductMetadataResponse,
    DBIRasterProductRetireResponse,
)
from app.dbi.raster.contracts import DBIRasterConflict
from app.dbi.raster.reader import (
    DBIRasterProductReader,
    DBIRasterProductUnavailable,
)
from app.dbi.raster.service import DBIRasterProductService, DBIRasterUnavailable
from app.dbi.storage_contracts import DBIPrivateObjectStore, MAX_STORAGE_RANGE_BYTES

router = APIRouter(prefix="/dbi", tags=["dbi-raster"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]

DBI_RASTER_NOT_FOUND_DETAIL = "Producto Raster DBI no disponible."
DBI_RASTER_CONFLICT_DETAIL = "El producto Raster DBI no supera las verificaciones de integridad."
DBI_RASTER_STORAGE_DETAIL = "El almacenamiento Raster DBI no está disponible."
DBI_RASTER_RANGE_DETAIL = "El rango Raster solicitado no es válido."


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DBI_RASTER_NOT_FOUND_DETAIL,
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DBI_RASTER_CONFLICT_DETAIL,
    )


def _range_error(total_size: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
        detail=DBI_RASTER_RANGE_DETAIL,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes */{total_size}",
        },
    )


def _require_plot_permission(
    context: DBIAccessContext,
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    permission: DBIPermission,
) -> None:
    try:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=permission,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _require_plot_read(
    context: DBIAccessContext,
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
) -> None:
    _require_plot_permission(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.READ,
    )


def _require_plot_write(
    context: DBIAccessContext,
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
) -> None:
    _require_plot_permission(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )


def get_dbi_raster_object_store(request: Request) -> DBIPrivateObjectStore:
    """Obtiene el puerto privado configurado por despliegue, nunca por cliente."""

    store = getattr(request.app.state, "dbi_object_store", None)
    required = ("stat", "read_range", "retire")
    if store is None or any(not hasattr(store, name) for name in required):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DBI_RASTER_STORAGE_DETAIL,
        )
    return store


StoreDependency = Annotated[
    DBIPrivateObjectStore,
    Depends(get_dbi_raster_object_store),
]


def _reader(session: Session, store: DBIPrivateObjectStore) -> DBIRasterProductReader:
    return DBIRasterProductReader(session, store)


def _parse_decimal(value: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError("decimal inválido")
    result = int(value)
    if result < 0:
        raise ValueError("decimal inválido")
    return result


def parse_single_http_range(
    value: str | None,
    *,
    total_size: int,
) -> tuple[int, int]:
    """Convierte un Range HTTP simple a [start, end_exclusive) bajo límite DBI."""

    if (
        not isinstance(total_size, int)
        or isinstance(total_size, bool)
        or total_size <= 0
        or not isinstance(value, str)
        or not value.startswith("bytes=")
    ):
        raise ValueError("Range inválido")
    specification = value[6:]
    if not specification or "," in specification or specification.count("-") != 1:
        raise ValueError("Range inválido")
    start_text, end_text = specification.split("-", 1)

    if start_text:
        start = _parse_decimal(start_text)
        if start >= total_size:
            raise ValueError("Range inválido")
        if end_text:
            end_inclusive = _parse_decimal(end_text)
            if end_inclusive < start or end_inclusive >= total_size:
                raise ValueError("Range inválido")
            end_exclusive = end_inclusive + 1
        else:
            end_exclusive = total_size
    else:
        suffix_length = _parse_decimal(end_text)
        if suffix_length <= 0:
            raise ValueError("Range inválido")
        suffix_length = min(suffix_length, total_size)
        start = total_size - suffix_length
        end_exclusive = total_size

    if end_exclusive - start > MAX_STORAGE_RANGE_BYTES:
        raise ValueError("Range excede política DBI")
    return start, end_exclusive


def _metadata(
    *,
    reader: DBIRasterProductReader,
    context: DBIAccessContext,
    farm_id: UUID,
    plot_id: UUID,
    product_id: UUID,
) -> DBIRasterProductMetadataResponse:
    try:
        metadata = reader.metadata(
            product_id=product_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    except DBIRasterProductUnavailable as error:
        raise _not_found() from error
    except DBIRasterConflict as error:
        raise _conflict() from error
    return DBIRasterProductMetadataResponse(**asdict(metadata))


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/raster-products/{product_id}",
    response_model=DBIRasterProductMetadataResponse,
)
def get_raster_product_metadata(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    product_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
    store: StoreDependency,
) -> DBIRasterProductMetadataResponse:
    """Devuelve metadata científica segura sin revelar dirección privada."""

    _require_plot_read(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    return _metadata(
        reader=_reader(session, store),
        context=context,
        farm_id=farm_id,
        plot_id=plot_id,
        product_id=product_id,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/raster-products/{product_id}/content",
    response_class=Response,
    responses={206: {"content": {"image/tiff": {}}}, 416: {"description": "Rango inválido"}},
)
def get_raster_product_range(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    product_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
    store: StoreDependency,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """Sirve exclusivamente un rango acotado; nunca responde el COG completo."""

    _require_plot_read(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    reader = _reader(session, store)
    metadata = _metadata(
        reader=reader,
        context=context,
        farm_id=farm_id,
        plot_id=plot_id,
        product_id=product_id,
    )
    try:
        start, end_exclusive = parse_single_http_range(
            range_header,
            total_size=metadata.size_bytes,
        )
    except ValueError as error:
        raise _range_error(metadata.size_bytes) from error

    try:
        result = reader.read_range(
            product_id=product_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            start=start,
            end_exclusive=end_exclusive,
        )
    except DBIRasterProductUnavailable as error:
        raise _not_found() from error
    except DBIRasterConflict as error:
        raise _conflict() from error

    return Response(
        content=result.data,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=result.content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": (
                f"bytes {result.start}-{result.end_exclusive - 1}/"
                f"{result.total_size_bytes}"
            ),
            "Content-Length": str(result.length),
            "ETag": f'"sha256:{metadata.sha256}"',
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/raster-products/{product_id}/retire",
    response_model=DBIRasterProductRetireResponse,
)
def retire_raster_product(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    product_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
    store: StoreDependency,
) -> DBIRasterProductRetireResponse:
    """Retira el objeto privado antes de confirmar su estado DBI; replay repara commit fallido."""

    _require_plot_write(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    try:
        evidence = DBIRasterProductService(session, store).retire(
            product_id=product_id,
            tenant_ref=context.tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            retired_at=datetime.now(timezone.utc),
        )
        session.commit()
    except DBIRasterUnavailable as error:
        session.rollback()
        raise _not_found() from error
    except (DBIRasterConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error

    return DBIRasterProductRetireResponse(
        product_id=evidence.product_id,
        status="retired",
        changed=evidence.changed,
        retired_at=evidence.retired_at,
    )
