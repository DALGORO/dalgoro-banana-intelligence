"""Autoridad persistente de identidad y membresías DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase
from app.dbi.authorization import DBIPermission

DBI_PERMISSION_VALUES = tuple(permission.value for permission in DBIPermission)


def utc_now() -> datetime:
    """Devuelve una fecha consciente de zona horaria en UTC."""

    return datetime.now(timezone.utc)


class DBIPrincipalStatus(StrEnum):
    """Estados persistentes reconocidos para una identidad canónica."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class DBIMembershipStatus(StrEnum):
    """Estados revocables de una membresía DBI."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"


class DBIMembershipScopeType(StrEnum):
    """Niveles jerárquicos persistibles bajo un tenant."""

    ORGANIZATION = "organization"
    FARM = "farm"
    PLOT = "plot"


class DBIPrincipal(DBIBase):
    """Identidad DBI canónica vinculada por una referencia heredada opaca."""

    __tablename__ = "dbi_principals"
    __table_args__ = (
        UniqueConstraint(
            "legacy_identity_ref",
            name="uq_dbi_principals_legacy_identity_ref",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_dbi_principals_status",
        ),
        CheckConstraint(
            "legacy_identity_ref = btrim(legacy_identity_ref) "
            "AND length(legacy_identity_ref) > 0 "
            "AND position('*' in legacy_identity_ref) = 0 "
            "AND lower(legacy_identity_ref) NOT IN ('all', 'any')",
            name="ck_dbi_principals_legacy_identity_ref",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    legacy_identity_ref: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DBIPrincipalStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class DBIMembership(DBIBase):
    """Membresía única de un principal dentro de un tenant DBI."""

    __tablename__ = "dbi_memberships"
    __table_args__ = (
        UniqueConstraint(
            "principal_id",
            "tenant_ref",
            name="uq_dbi_memberships_principal_tenant",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'revoked')",
            name="ck_dbi_memberships_status",
        ),
        CheckConstraint(
            "tenant_ref = btrim(tenant_ref) "
            "AND length(tenant_ref) > 0 "
            "AND position('*' in tenant_ref) = 0 "
            "AND lower(tenant_ref) NOT IN ('all', 'any')",
            name="ck_dbi_memberships_tenant_ref",
        ),
        Index("ix_dbi_memberships_principal_id", "principal_id"),
        Index("ix_dbi_memberships_tenant_ref", "tenant_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    principal_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DBIMembershipStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class DBIMembershipPermission(DBIBase):
    """Permiso global explícito de una membresía dentro de su tenant."""

    __tablename__ = "dbi_membership_permissions"
    __table_args__ = (
        CheckConstraint(
            "permission IN ("
            "'read', 'write', 'submit_analysis', "
            "'approve_agronomic', 'manage'"
            ")",
            name="ck_dbi_membership_permissions_permission",
        ),
    )

    membership_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_memberships.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
    )


class DBIMembershipScope(DBIBase):
    """Ámbito jerárquico autorizado para una membresía DBI."""

    __tablename__ = "dbi_membership_scopes"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('organization', 'farm', 'plot')",
            name="ck_dbi_membership_scopes_type",
        ),
        CheckConstraint(
            "("
            "scope_type = 'organization' "
            "AND farm_id IS NULL AND plot_id IS NULL"
            ") OR ("
            "scope_type = 'farm' "
            "AND farm_id IS NOT NULL AND plot_id IS NULL"
            ") OR ("
            "scope_type = 'plot' "
            "AND farm_id IS NOT NULL AND plot_id IS NOT NULL"
            ")",
            name="ck_dbi_membership_scopes_hierarchy",
        ),
        CheckConstraint(
            "organization_ref = btrim(organization_ref) "
            "AND length(organization_ref) > 0 "
            "AND position('*' in organization_ref) = 0 "
            "AND lower(organization_ref) NOT IN ('all', 'any')",
            name="ck_dbi_membership_scopes_organization_ref",
        ),
        Index(
            "uq_dbi_membership_scopes_organization",
            "membership_id",
            "organization_ref",
            unique=True,
            postgresql_where=text("scope_type = 'organization'"),
        ),
        Index(
            "uq_dbi_membership_scopes_farm",
            "membership_id",
            "organization_ref",
            "farm_id",
            unique=True,
            postgresql_where=text("scope_type = 'farm'"),
        ),
        Index(
            "uq_dbi_membership_scopes_plot",
            "membership_id",
            "organization_ref",
            "farm_id",
            "plot_id",
            unique=True,
            postgresql_where=text("scope_type = 'plot'"),
        ),
        Index("ix_dbi_membership_scopes_membership_id", "membership_id"),
        Index("ix_dbi_membership_scopes_farm_id", "farm_id"),
        Index("ix_dbi_membership_scopes_plot_id", "plot_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    membership_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    organization_ref: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    farm_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="RESTRICT"),
        nullable=True,
    )
    plot_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("dbi_plots.id", ondelete="RESTRICT"),
        nullable=True,
    )
