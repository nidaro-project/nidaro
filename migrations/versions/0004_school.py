"""Add the school domain: subjects, materialized lessons, grades, homework."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_school"
down_revision = "0003_calendar_activity_fields"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
jsonb = postgresql.JSONB()
timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "school_subjects",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column(
            "member_id",
            uuid,
            sa.ForeignKey("family_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("teacher", sa.String(200)),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("member_id", "code"),
    )
    op.create_index("ix_school_subjects_household_id", "school_subjects", ["household_id"])
    op.create_index("ix_school_subjects_member_id", "school_subjects", ["member_id"])

    op.create_table(
        "school_lessons",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column(
            "member_id",
            uuid,
            sa.ForeignKey("family_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("subject_id", uuid, sa.ForeignKey("school_subjects.id", ondelete="SET NULL")),
        sa.Column("start", sa.Time(), nullable=False),
        sa.Column("end", sa.Time(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("teacher", sa.String(200)),
        sa.Column("room", sa.String(50)),
        sa.Column("canceled", sa.Boolean(), nullable=False),
        sa.Column("substitution", sa.Text()),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("member_id", "day", "position"),
    )
    op.create_index("ix_school_lessons_household_id", "school_lessons", ["household_id"])
    op.create_index("ix_school_lessons_member_id", "school_lessons", ["member_id"])
    op.create_index("ix_school_lessons_day", "school_lessons", ["day"])

    op.create_table(
        "school_grades",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column(
            "member_id",
            uuid,
            sa.ForeignKey("family_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_id", uuid, sa.ForeignKey("school_subjects.id", ondelete="SET NULL")),
        sa.Column("external_id", sa.String(250), nullable=False),
        sa.Column("value", sa.String(20), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("graded_on", sa.Date(), nullable=False),
        sa.Column("teacher", sa.String(200)),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_index("ix_school_grades_household_id", "school_grades", ["household_id"])
    op.create_index("ix_school_grades_member_id", "school_grades", ["member_id"])
    op.create_index("ix_school_grades_external_id", "school_grades", ["external_id"])

    op.create_table(
        "school_homework",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column(
            "member_id",
            uuid,
            sa.ForeignKey("family_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_id", uuid, sa.ForeignKey("school_subjects.id", ondelete="SET NULL")),
        sa.Column("external_id", sa.String(250), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("due_on", sa.Date()),
        sa.Column("attachments", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_index("ix_school_homework_household_id", "school_homework", ["household_id"])
    op.create_index("ix_school_homework_member_id", "school_homework", ["member_id"])
    op.create_index("ix_school_homework_external_id", "school_homework", ["external_id"])


def downgrade() -> None:
    op.drop_table("school_homework")
    op.drop_table("school_grades")
    op.drop_table("school_lessons")
    op.drop_table("school_subjects")
