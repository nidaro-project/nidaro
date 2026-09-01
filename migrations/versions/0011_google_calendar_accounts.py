"""Google Calendar accounts: per-household registry of consented accounts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_google_calendar_accounts"
down_revision = "0010_whatsapp_staging"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "google_calendar_accounts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("google_email", sa.String(250), nullable=False),
        sa.Column("calendar_id", sa.String(250), nullable=False),
        # Scopes Google actually granted (granular consent may grant a subset);
        # write features degrade instead of assuming.
        sa.Column("granted_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("household_id", "google_email"),
    )
    op.create_index(
        "ix_google_calendar_accounts_household_id", "google_calendar_accounts", ["household_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_google_calendar_accounts_household_id", table_name="google_calendar_accounts")
    op.drop_table("google_calendar_accounts")
