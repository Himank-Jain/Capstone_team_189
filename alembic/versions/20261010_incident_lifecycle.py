"""Add lifecycle and resolution fields to incidents."""

import sqlalchemy as sa
from alembic import op

revision = "20261010_incident_lifecycle"
down_revision = "20261008_create_platform_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.add_column("incidents", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column("incidents", sa.Column("resolved_by", sa.String(length=64)))
    op.add_column("incidents", sa.Column("resolution_type", sa.String(length=50)))
    op.add_column("incidents", sa.Column("resolution_note", sa.String(length=2000)))
    op.add_column("incidents", sa.Column("regression_of", sa.String(length=64)))
    op.execute("UPDATE incidents SET status = UPPER(status)")
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=50),
            nullable=False,
            server_default="OPEN",
        )
        batch_op.create_check_constraint(
            "ck_incidents_status",
            "status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED')",
        )
        batch_op.create_check_constraint(
            "ck_incidents_resolution_type",
            "resolution_type IS NULL OR resolution_type IN "
            "('FIXED', 'FALSE_POSITIVE', 'EXPECTED_CHANGE', 'AUTO_RECOVERED')",
        )


def downgrade() -> None:
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_constraint("ck_incidents_resolution_type", type_="check")
        batch_op.drop_constraint("ck_incidents_status", type_="check")
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=50),
            nullable=False,
            server_default="open",
        )
    op.execute("UPDATE incidents SET status = LOWER(status)")
    op.drop_column("incidents", "regression_of")
    op.drop_column("incidents", "resolution_note")
    op.drop_column("incidents", "resolution_type")
    op.drop_column("incidents", "resolved_by")
    op.drop_column("incidents", "resolved_at")
    op.drop_column("incidents", "acknowledged_at")
