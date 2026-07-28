from sqlalchemy import Column, Integer, String, Text, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base_class import Base

class DocumentTemplate(Base):
    __tablename__ = "document_templates"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, index=True)
    activity = Column(String(60), nullable=False, index=True)
    title = Column(Text, nullable=False)
    version = Column(String(20), default="1.0")
    fields_json = Column(JSONB, nullable=False)  # definición de campos del formulario
    file_path = Column(Text, nullable=False)     # ruta de la plantilla (docx/xlsx/…)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("code", "activity", name="uq_document_templates_code_activity"),
        Index("ix_document_templates_activity_code", "activity", "code"),
    )

    def __repr__(self) -> str:
        return f"<DocumentTemplate {self.activity}:{self.code} v{self.version}>"
