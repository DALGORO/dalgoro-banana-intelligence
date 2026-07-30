"""Contratos, validación y conversión del límite espacial DBI."""

from __future__ import annotations

from math import isfinite
from typing import Any, Literal

from geoalchemy2.elements import WKBElement, WKTElement
from geoalchemy2.shape import from_shape, to_shape
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

DBI_SPATIAL_SRID = 4326
DBI_BOUNDARY_MAX_COORDINATES = 10_000
DBI_SPATIAL_RESULT_LIMIT = 20

Position = tuple[float, float]
LinearRingCoordinates = list[Position]
PolygonCoordinates = list[LinearRingCoordinates]
MultiPolygonCoordinates = list[PolygonCoordinates]


class GeoJSONMultiPolygon(BaseModel):
    """GeoJSON canónico 2D para límites agrícolas DBI."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["MultiPolygon"]
    coordinates: MultiPolygonCoordinates

    @field_validator("coordinates")
    @classmethod
    def validate_coordinate_structure(
        cls,
        coordinates: MultiPolygonCoordinates,
    ) -> MultiPolygonCoordinates:
        if not coordinates:
            raise ValueError("La geometría no puede estar vacía.")

        coordinate_count = 0
        for polygon_index, polygon in enumerate(coordinates):
            if not polygon:
                raise ValueError(
                    f"El polígono {polygon_index} debe contener al menos un anillo."
                )

            for ring_index, ring in enumerate(polygon):
                if len(ring) < 4:
                    raise ValueError(
                        "Cada anillo debe contener al menos cuatro posiciones."
                    )
                if ring[0] != ring[-1]:
                    raise ValueError(
                        f"El anillo {ring_index} del polígono {polygon_index} "
                        "debe estar cerrado."
                    )

                for longitude, latitude in ring:
                    if not isfinite(longitude) or not isfinite(latitude):
                        raise ValueError("Las coordenadas deben ser números finitos.")
                    if not -180 <= longitude <= 180:
                        raise ValueError("La longitud debe estar entre -180 y 180.")
                    if not -90 <= latitude <= 90:
                        raise ValueError("La latitud debe estar entre -90 y 90.")

                    coordinate_count += 1
                    if coordinate_count > DBI_BOUNDARY_MAX_COORDINATES:
                        raise ValueError(
                            "La geometría supera el límite de complejidad permitido."
                        )

        return coordinates

    @model_validator(mode="after")
    def validate_topology(self) -> "GeoJSONMultiPolygon":
        geometry = shape(self.model_dump(mode="python"))
        if geometry.geom_type != "MultiPolygon":
            raise ValueError("La geometría debe ser MultiPolygon.")
        if geometry.is_empty:
            raise ValueError("La geometría no puede estar vacía.")
        if not geometry.is_valid:
            raise ValueError(
                "La geometría no es topológicamente válida: "
                f"{explain_validity(geometry)}"
            )
        return self


def boundary_to_database(
    value: GeoJSONMultiPolygon | dict[str, Any] | None,
) -> WKBElement | None:
    """Convierte GeoJSON validado a EWKB con SRID canónico."""

    if value is None:
        return None

    payload = (
        value
        if isinstance(value, GeoJSONMultiPolygon)
        else GeoJSONMultiPolygon.model_validate(value)
    )
    geometry = shape(payload.model_dump(mode="python"))
    return from_shape(geometry, srid=DBI_SPATIAL_SRID, extended=True)


def boundary_from_database(value: Any) -> GeoJSONMultiPolygon | None:
    """Convierte el valor espacial persistido a GeoJSON no binario."""

    if value is None:
        return None
    if isinstance(value, GeoJSONMultiPolygon):
        return value
    if isinstance(value, dict):
        return GeoJSONMultiPolygon.model_validate(value)

    geometry: BaseGeometry
    if isinstance(value, (WKBElement, WKTElement)):
        geometry = to_shape(value)
    elif isinstance(value, BaseGeometry):
        geometry = value
    else:
        raise TypeError("Representación espacial DBI no compatible.")

    return GeoJSONMultiPolygon.model_validate(mapping(geometry))
