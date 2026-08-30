"""Add calendar activity fields to events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_calendar_activity_fields"
down_revision = "0002_meals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("is_all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "events",
        sa.Column("recurrence_weekdays", postgresql.ARRAY(sa.Integer()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "recurrence_weekdays")
    op.drop_column("events", "is_all_day")
