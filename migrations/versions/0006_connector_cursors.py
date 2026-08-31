"""Cursor persistence for connector sync: one high-water mark per household+connector."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_connector_cursors"
down_revision = "0005_school_equipment"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "connector_cursors",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("connector", sa.String(100), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("household_id", "connector"),
    )
    op.create_index("ix_connector_cursors_household_id", "connector_cursors", ["household_id"])


def downgrade() -> None:
    op.drop_index("ix_connector_cursors_household_id", table_name="connector_cursors")
    op.drop_table("connector_cursors")
