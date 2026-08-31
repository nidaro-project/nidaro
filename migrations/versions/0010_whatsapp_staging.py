"""WhatsApp staging: raw message events parked at ingest, drained by the connector."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_whatsapp_staging"
down_revision = "0009_connector_household_config"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "whatsapp_events",
        # Monotonic sequence id — doubles as the drain's high-water cursor,
        # which UUIDv7 cannot guarantee within one millisecond.
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("wamid", sa.String(250), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("from_user_id", sa.Text(), nullable=True),
        sa.Column("wa_id", sa.Text(), nullable=True),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column("context_id", sa.Text(), nullable=True),
        sa.Column("forwarded", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("observed_at", timestamp, nullable=False),
        sa.Column("processed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        # Globally unique message id: webhook retries and double-staging
        # from the bridge collapse onto one row.
        sa.UniqueConstraint("wamid"),
    )
    op.create_index("ix_whatsapp_events_household_id", "whatsapp_events", ["household_id"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_events_household_id", table_name="whatsapp_events")
    op.drop_table("whatsapp_events")
