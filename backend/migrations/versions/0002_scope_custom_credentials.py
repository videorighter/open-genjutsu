"""Bind custom and GPU credentials to an approved endpoint."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "credentials",
        sa.Column("endpoint", sa.String(500), nullable=False, server_default=""),
    )
    op.drop_constraint(
        "credentials_user_id_provider_key", "credentials", type_="unique"
    )
    op.create_unique_constraint(
        "credentials_user_provider_endpoint",
        "credentials",
        ["user_id", "provider", "endpoint"],
    )


def downgrade():
    op.drop_constraint(
        "credentials_user_provider_endpoint", "credentials", type_="unique"
    )
    op.drop_column("credentials", "endpoint")
    op.create_unique_constraint(
        "credentials_user_id_provider_key", "credentials", ["user_id", "provider"]
    )
