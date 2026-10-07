"""Record operator closure of ambiguous provider submissions."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("review_note", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("jobs", "review_note")
