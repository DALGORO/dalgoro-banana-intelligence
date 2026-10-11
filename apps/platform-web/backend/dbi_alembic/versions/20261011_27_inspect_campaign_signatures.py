"""Tablas aditivas para emparejar Campaign MULTI, INSPECT y firmas independientes.

Revision ID: dbi_0027_inspect_dual_sign
Revises: dbi_0026_gpkg_layer_choice

No modifica observaciones históricas ni habilita publicación al cliente.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0027_inspect_dual_sign"
down_revision: str | None = "dbi_0026_gpkg_layer_choice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Llaves candidatas compuestas para comprobar scope en el MOTOR, no solo
    # en la API. El ID ya es único; esto no cambia filas preexistentes.
    op.create_unique_constraint(
        "uq_dbi_campaigns_inspect_multispectral_scope", "dbi_campaigns",
        ["id", "tenant_ref", "organization_ref", "farm_id", "plot_id", "analysis_type"],
    )
    op.create_unique_constraint(
        "uq_dbi_field_observations_inspect_scope", "dbi_field_observations",
        ["id", "tenant_ref", "organization_ref", "farm_id", "plot_id"],
    )

    op.create_table(
        "dbi_inspect_campaign_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_analysis_type", sa.String(length=16), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("observation_version_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by_ref", sa.String(length=128), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_inspect_campaign_links"),
        sa.ForeignKeyConstraint(
            ["campaign_id", "tenant_ref", "organization_ref",
             "farm_id", "plot_id", "campaign_analysis_type"],
            ["dbi_campaigns.id", "dbi_campaigns.tenant_ref",
             "dbi_campaigns.organization_ref", "dbi_campaigns.farm_id",
             "dbi_campaigns.plot_id", "dbi_campaigns.analysis_type"],
            name="fk_dbi_inspect_links_campaign_scope_multi", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "tenant_ref", "organization_ref", "farm_id", "plot_id"],
            ["dbi_field_observations.id", "dbi_field_observations.tenant_ref",
             "dbi_field_observations.organization_ref",
             "dbi_field_observations.farm_id", "dbi_field_observations.plot_id"],
            name="fk_dbi_inspect_links_observation_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "observation_version_id"],
            ["dbi_field_observation_versions.observation_id",
             "dbi_field_observation_versions.id"],
            name="fk_dbi_inspect_links_version_identity", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "observation_version_id", name="uq_dbi_inspect_links_one_campaign_per_version",
        ),
        sa.CheckConstraint(
            "campaign_analysis_type = 'multispectral'",
            name="ck_dbi_inspect_links_multispectral_only",
        ),
        sa.CheckConstraint(
            "length(tenant_ref) BETWEEN 1 AND 128 "
            "AND btrim(tenant_ref) = tenant_ref AND tenant_ref NOT LIKE '%*%' "
            "AND length(organization_ref) BETWEEN 1 AND 128 "
            "AND btrim(organization_ref) = organization_ref AND organization_ref NOT LIKE '%*%' "
            "AND length(linked_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(linked_by_ref) = linked_by_ref AND linked_by_ref NOT LIKE '%*%'",
            name="ck_dbi_inspect_links_canonical_refs",
        ),
    )
    op.create_index("ix_dbi_inspect_links_campaign", "dbi_inspect_campaign_links", ["campaign_id"])
    op.create_index("ix_dbi_inspect_links_observation", "dbi_inspect_campaign_links", ["observation_id"])
    op.create_index(
        "ix_dbi_inspect_links_scope", "dbi_inspect_campaign_links",
        ["tenant_ref", "organization_ref", "farm_id", "plot_id"],
    )

    # Libro de firmas. No crear endpoints todavía: un INSERT directo NO
    # equivale a aprobación y nunca debe habilitar por sí solo GET cliente.
    op.create_table(
        "dbi_inspect_approval_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("link_id", sa.Uuid(), nullable=False),
        sa.Column("event_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_ref", sa.String(length=128), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_inspect_approval_events"),
        sa.ForeignKeyConstraint(
            ["link_id"], ["dbi_inspect_campaign_links.id"],
            name="fk_dbi_inspect_approval_events_link", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "link_id", "event_kind", name="uq_dbi_inspect_approval_event_step",
        ),
        sa.CheckConstraint(
            "event_kind IN ('technical_validated', 'administrative_authorized')",
            name="ck_dbi_inspect_approval_event_kind",
        ),
        sa.CheckConstraint(
            "length(actor_ref) BETWEEN 1 AND 128 "
            "AND btrim(actor_ref) = actor_ref AND actor_ref NOT LIKE '%*%'",
            name="ck_dbi_inspect_approval_actor",
        ),
    )
    op.create_index("ix_dbi_inspect_approval_events_link", "dbi_inspect_approval_events", ["link_id"])
    op.create_index("ix_dbi_inspect_approval_events_actor", "dbi_inspect_approval_events", ["actor_ref"])


def downgrade() -> None:
    # Sólo rollback controlado de tablas añadidas; nunca borra INSPECT original.
    op.drop_table("dbi_inspect_approval_events")
    op.drop_table("dbi_inspect_campaign_links")
    op.drop_constraint(
        "uq_dbi_field_observations_inspect_scope", "dbi_field_observations", type_="unique",
    )
    op.drop_constraint(
        "uq_dbi_campaigns_inspect_multispectral_scope", "dbi_campaigns", type_="unique",
    )
