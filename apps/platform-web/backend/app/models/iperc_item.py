# app/models/iperc_item.py
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, Boolean, Date, JSON, Numeric, ForeignKey
from app.db.base_class import Base

class IPERCItem(Base):
    __tablename__ = "iperc_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )

    sheet: Mapped[str] = mapped_column(String(64), nullable=False, default="BASE", index=True)
    
    activity: Mapped[str] = mapped_column(String(64), nullable=False)
    process: Mapped[str] = mapped_column(String(128), nullable=False)
    job: Mapped[str] = mapped_column(String(128), nullable=False)
    task: Mapped[str] = mapped_column(String(256), nullable=False)

    hazard_group: Mapped[str] = mapped_column(String(64), nullable=False)
    hazard: Mapped[str] = mapped_column(String(256), nullable=False)
    event: Mapped[str] = mapped_column(String(256), nullable=False)
    consequence: Mapped[str] = mapped_column(String(256), nullable=False)

    exposed_persons: Mapped[str | None] = mapped_column(String(128))
    
    probability: Mapped[float | None] = mapped_column(Numeric)
    severity: Mapped[float | None] = mapped_column(Numeric)
    risk_level: Mapped[str | None] = mapped_column(String(32))

    # NUEVO: GTC-45
    nd: Mapped[int | None] = mapped_column(Integer)       # Nivel de Deficiencia
    ne: Mapped[int | None] = mapped_column(Integer)       # Nivel de Exposición
    nc: Mapped[int | None] = mapped_column(Integer)       # Nivel de Consecuencia
    np: Mapped[int | None] = mapped_column(Integer)       # ND*NE
    nr: Mapped[int | None] = mapped_column(Integer)       # NP*NC
    risk_interp: Mapped[str | None] = mapped_column(String(32))   # TRIVIAL/TOLERABLE/MODERADO/IMPORTANTE/INTOLERABLE
    acceptable: Mapped[str | None] = mapped_column(String(32))    # ACEPTABLE / NO ACEPTABLE
    np_level: Mapped[str | None] = mapped_column(String(4))    # 'MA' | 'A' | 'M' | 'B'
    nr_level: Mapped[str | None] = mapped_column(String(2))    # 'I' | 'II' | 'III' | 'IV'
    nr_color: Mapped[str | None] = mapped_column(String(8))    # '#e74c3c' etc. (opcional)

    # Controles existentes
    controls_existing_engineering: Mapped[dict | None] = mapped_column(JSON)
    controls_existing_admin: Mapped[dict | None] = mapped_column(JSON)
    controls_existing_epp: Mapped[dict | None] = mapped_column(JSON)

    # Controles planificados
    controls_planned_engineering: Mapped[dict | None] = mapped_column(JSON)
    controls_planned_admin: Mapped[dict | None] = mapped_column(JSON)
    controls_planned_epp: Mapped[dict | None] = mapped_column(JSON)

    # Flags y anexos
    requires_work_permit: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_health_surveillance: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_env_monitoring: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_epp: Mapped[dict | None] = mapped_column(JSON)
    evidence_refs: Mapped[dict | None] = mapped_column(JSON)

    # Fechas y estado
    review_date: Mapped[Date | None] = mapped_column(Date)
    next_review: Mapped[Date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(32), default="vigente")
