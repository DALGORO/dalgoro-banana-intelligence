"""Ingesta durable y persistencia consultable de resultados DBI."""

from app.dbi.results.consumer import DBIAnalysisResultConsumer
from app.dbi.results.contracts import (
    DBIResultAckPending,
    DBIResultFailureCode,
    DBIResultIngestionConflict,
    DBIResultIngestionUnavailable,
    ResultIngestionEvidence,
)
from app.dbi.results.repository import DBIResultRepository
from app.dbi.results.service import DBIAnalysisResultIngestionService

__all__ = [
    "DBIAnalysisResultConsumer",
    "DBIAnalysisResultIngestionService",
    "DBIResultAckPending",
    "DBIResultFailureCode",
    "DBIResultIngestionConflict",
    "DBIResultIngestionUnavailable",
    "DBIResultRepository",
    "ResultIngestionEvidence",
]
