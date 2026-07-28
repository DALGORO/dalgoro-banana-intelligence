from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAuditLog
from app.models.user import User


def log_admin_action(
    db: Session,
    acting_admin: User | None,
    *,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    target_user_id: int | None = None,
    company_id: int | None = None,
    description: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AdminAuditLog:
    row = AdminAuditLog(
        admin_user_id=(acting_admin.id if acting_admin else None),
        action=(action or "").strip().upper(),
        entity_type=(entity_type or "").strip().upper(),
        entity_id=entity_id,
        target_user_id=target_user_id,
        company_id=company_id,
        description=(description or "").strip() or None,
        payload=payload or None,
    )
    db.add(row)
    return row


def serialize_admin_audit_log(row: AdminAuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "admin_user_id": row.admin_user_id,
        "admin_email": getattr(getattr(row, "admin_user", None), "email", None),
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "target_user_id": row.target_user_id,
        "target_user_email": getattr(getattr(row, "target_user", None), "email", None),
        "company_id": row.company_id,
        "company_name": getattr(getattr(row, "company", None), "name", None),
        "description": row.description,
        "payload": row.payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }