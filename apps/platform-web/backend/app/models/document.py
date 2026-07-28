from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB            # ✅ usar JSONB en Postgres
from sqlalchemy.orm import relationship                     # ✅ relationship para back_populates
from app.db.base_class import Base

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    kind = Column(String(64), nullable=False)               # p.ej. "INV-ACC-01"
    title = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    mime = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)

    # Versionado por requisito/año/secuencia + metadata
    requirement_code = Column(String(64), index=True, nullable=True)   # igual a 'kind' o subcódigo
    period_year = Column(Integer, index=True, nullable=True)           # año de referencia
    seq = Column(Integer, nullable=True)                               # 1..N por año y requisito/empresa
    meta = Column(JSONB, nullable=True)                                # ✅ JSONB para Postgres

    company = relationship("Company", back_populates="documents")

    # ✅ define el índice dentro de la clase para mantenerlo unido al modelo
    __table_args__ = (
        Index("ix_documents_company_created", "company_id", "created_at"),
        Index("ix_documents_company_req_year", "company_id", "requirement_code", "period_year"),  # ← NUEVO
    )
