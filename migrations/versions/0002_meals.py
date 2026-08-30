"""Add the meals domain: dishes and planned_meals."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_meals"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
jsonb = postgresql.JSONB()
timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "dishes",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("tags", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_index("ix_dishes_household_id", "dishes", ["household_id"])
    op.create_table(
        "planned_meals",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(40), nullable=False),
        sa.Column("dish_id", uuid, sa.ForeignKey("dishes.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_index("ix_planned_meals_household_id", "planned_meals", ["household_id"])
    op.create_index("ix_planned_meals_date", "planned_meals", ["date"])


def downgrade() -> None:
    op.drop_index("ix_planned_meals_date", "planned_meals")
    op.drop_index("ix_planned_meals_household_id", "planned_meals")
    op.drop_table("planned_meals")
    op.drop_index("ix_dishes_household_id", "dishes")
    op.drop_table("dishes")
