from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import String, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    plan: Mapped[str] = mapped_column(String(32), default="FREE_TRIAL", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, PAST_DUE, CANCELED

    # Trial y ciclo de facturación
    free_trial_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Cupos de empresas
    companies_quota: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Trazabilidad básica de pagos
    last_payment_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="KUSHKI", nullable=False)
    customer_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")

    @staticmethod
    def new_trial(user_id: int) -> "Subscription":
        now = datetime.utcnow()
        return Subscription(
            user_id=user_id,
            plan="FREE_TRIAL",
            status="ACTIVE",
            free_trial_until=now + timedelta(days=15),  # trial 15 días
            companies_quota=1,                          # 1 empresa durante trial
            provider="KUSHKI",
        )
