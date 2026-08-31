"""School subjects carry the household-maintained what-to-pack equipment list."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_school_equipment"
down_revision = "0004_school"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "school_subjects",
        sa.Column("equipment", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("school_subjects", "equipment")
