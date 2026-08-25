"""Create the first Nidaro vertical slice schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
jsonb = postgresql.JSONB()
timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_table(
        "family_members",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("metadata", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_table(
        "sources",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(250)),
        sa.Column("title", sa.String(250)),
        sa.Column("content", sa.Text()),
        sa.Column("metadata", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("starts_at", timestamp, nullable=False),
        sa.Column("ends_at", timestamp),
        sa.Column("location", sa.String(250)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_id", uuid, sa.ForeignKey("sources.id")),
        sa.Column("metadata", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_table(
        "event_participants",
        sa.Column(
            "event_id", uuid, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "member_id",
            uuid,
            sa.ForeignKey("family_members.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "tasks",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("due_at", timestamp),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("assignee_id", uuid, sa.ForeignKey("family_members.id")),
        sa.Column("event_id", uuid, sa.ForeignKey("events.id")),
        sa.Column("source_id", uuid, sa.ForeignKey("sources.id")),
        sa.Column("metadata", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_table(
        "facts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_type", sa.String(80), nullable=False),
        sa.Column("subject_id", uuid),
        sa.Column("fact_type", sa.String(80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("valid_from", timestamp),
        sa.Column("valid_until", timestamp),
        sa.Column("source_id", uuid, sa.ForeignKey("sources.id")),
        sa.Column("metadata", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_table(
        "commitments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("from_member_id", uuid, sa.ForeignKey("family_members.id")),
        sa.Column("to_person_name", sa.String(200)),
        sa.Column("due_at", timestamp),
        sa.Column("event_id", uuid, sa.ForeignKey("events.id")),
        sa.Column("source_id", uuid, sa.ForeignKey("sources.id")),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_table(
        "conversations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("title", sa.String(250)),
        sa.Column("message_history", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
    )
    op.create_table(
        "job_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("parameters", jsonb, nullable=False),
        sa.Column("queued_at", timestamp, nullable=False),
        sa.Column("started_at", timestamp),
        sa.Column("finished_at", timestamp),
        sa.Column("error", sa.Text()),
        sa.Column("result", jsonb),
    )
    for table in (
        "family_members",
        "sources",
        "events",
        "tasks",
        "facts",
        "commitments",
        "conversations",
    ):
        op.create_index(f"ix_{table}_household_id", table, ["household_id"])


def downgrade() -> None:
    for table in (
        "job_runs",
        "conversations",
        "commitments",
        "facts",
        "tasks",
        "event_participants",
        "events",
        "sources",
        "family_members",
        "households",
    ):
        op.drop_table(table)
