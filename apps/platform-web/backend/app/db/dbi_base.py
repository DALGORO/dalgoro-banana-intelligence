"""Metadatos SQLAlchemy exclusivos del dominio DBI."""

from sqlalchemy.orm import DeclarativeBase


class DBIBase(DeclarativeBase):
    """Base declarativa independiente de los modelos heredados."""

