"""Tombstone semantics for external records: mirror identity on events."""

import sqlalchemy as sa
from alembic import op

revision = "0007_external_record_tombstones"
down_revision = "0006_connector_cursors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("external_connector", sa.String(100), nullable=True))
    op.add_column("events", sa.Column("external_id", sa.String(250), nullable=True))
    op.create_index(
        "uq_events_external_identity",
        "events",
        ["household_id", "external_connector", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_events_external_identity", table_name="events")
    op.drop_column("events", "external_id")
    op.drop_column("events", "external_connector")
