"""Metadatos SQLAlchemy exclusivos del dominio DBI."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

DBI_NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class DBIBase(DeclarativeBase):
    """Base declarativa independiente de los modelos heredados."""

    metadata = MetaData(naming_convention=DBI_NAMING_CONVENTION)
