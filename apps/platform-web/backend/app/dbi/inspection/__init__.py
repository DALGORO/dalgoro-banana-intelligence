"""Captura de campo y verdad-terreno agronómica DBI."""

from app.dbi.inspection.contracts import (
    DBI_FIELD_OBSERVATION_SCHEMA_VERSION,
    DBICoreObservation,
    DBIDiagnosticObservation,
    DBIFieldObservationCorrection,
    DBIFieldObservationCreate,
    DBIFieldObservationPayload,
    DBIFieldObservationVersion,
    DBIFoureObservation,
    DBIGPSFix,
    DBILeafCountObservation,
    DBIObservedBool,
    DBIObservedFloat,
    DBIObservedInt,
    DBIObservedText,
    DBIPhotoEvidence,
    DBIStructuralObservation,
)

__all__ = [
    "DBI_FIELD_OBSERVATION_SCHEMA_VERSION",
    "DBICoreObservation",
    "DBIDiagnosticObservation",
    "DBIFieldObservationCorrection",
    "DBIFieldObservationCreate",
    "DBIFieldObservationPayload",
    "DBIFieldObservationVersion",
    "DBIFoureObservation",
    "DBIGPSFix",
    "DBILeafCountObservation",
    "DBIObservedBool",
    "DBIObservedFloat",
    "DBIObservedInt",
    "DBIObservedText",
    "DBIPhotoEvidence",
    "DBIStructuralObservation",
]
