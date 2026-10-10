"""Create the Phase 3 platform schema."""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261008_create_platform_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(length=64), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_mode", sa.String(length=20), nullable=False),
        sa.Column("onboarding_state", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_check_constraint(
        "ck_tenants_source_mode",
        "tenants",
        "source_mode IN ('synthetic', 'live')",
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("membership_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_tenant_membership_user_tenant"),
    )
    op.create_check_constraint(
        "ck_tenant_membership_role",
        "tenant_memberships",
        "role IN ('OWNER', 'OPERATOR', 'VIEWER')",
    )

    op.create_table(
        "cloud_connections",
        sa.Column("connection_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("credentials_ciphertext", sa.String(length=1024), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "cloud_resources",
        sa.Column("resource_id", sa.String(length=64), primary_key=True),
        sa.Column("connection_id", sa.String(length=64), sa.ForeignKey("cloud_connections.connection_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_name", sa.String(length=255), nullable=False),
        sa.Column("resource_summary", sa.JSON(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "notification_endpoints",
        sa.Column("endpoint_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("secret_ciphertext", sa.String(length=512), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "notification_policies",
        sa.Column("policy_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("match_criteria", sa.JSON(), nullable=True),
        sa.Column("retry_policy", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("delivery_id", sa.String(length=64), primary_key=True),
        sa.Column("alert_id", sa.String(length=64), nullable=False),
        sa.Column("endpoint_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_unique_constraint(
        "uq_notification_delivery_alert_endpoint",
        "notification_deliveries",
        ["alert_id", "endpoint_id"],
    )

    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "rca_cases",
        sa.Column("rca_case_id", sa.String(length=64), primary_key=True),
        sa.Column("incident_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "audit_events",
        sa.Column("audit_event_id", sa.String(length=64), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("rca_cases")
    op.drop_table("incidents")
    op.drop_table("notification_deliveries")
    op.drop_table("notification_policies")
    op.drop_table("notification_endpoints")
    op.drop_table("cloud_resources")
    op.drop_table("cloud_connections")
    op.drop_table("tenant_memberships")
    op.drop_table("tenants")
    op.drop_table("users")
