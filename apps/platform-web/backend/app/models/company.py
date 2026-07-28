# --- inicio cambio ---
from __future__ import annotations
from datetime import datetime
from typing import List, TYPE_CHECKING                         # ✅ nuevo (tipado opcional)

from sqlalchemy import String, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base

if TYPE_CHECKING:                                             # ✅ evita import cíclico en tiempo de carga
    from app.models.document import Document

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    ruc: Mapped[str] = mapped_column(String(13), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    activity: Mapped[str] = mapped_column(String(80), nullable=False)  # bananera, camaronera, etc.
    workers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), default="MEDIO", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    owner = relationship("User", backref="companies")

    # ✅ relación inversa: Company -> Document (coincide con Document.company back_populates="company")
    documents: Mapped[List["Document"]] = relationship(
        "Document",
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,          # opcional, útil si defines ondelete en FK
    )
# --- fin cambio ---
