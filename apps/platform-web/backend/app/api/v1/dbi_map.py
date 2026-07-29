"""Endpoint inicial de la interfaz cronológica de mapas DBI."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import current_user
from app.models.user import User
from app.schemas.dbi_map import (
    FarmMapTimelineResponse,
    build_empty_farm_map_timeline,
)

router = APIRouter(prefix="/dbi/farms", tags=["dbi-map"])


@router.get(
    "/{farm_id}/map/timeline",
    response_model=FarmMapTimelineResponse,
)
def get_farm_map_timeline(
    farm_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
    _user: User = Depends(current_user),
) -> FarmMapTimelineResponse:
    """Devuelve el contrato inicial, todavía sin persistencia DBI."""

    return build_empty_farm_map_timeline(farm_id)
