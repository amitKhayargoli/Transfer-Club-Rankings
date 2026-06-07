"""add_image_url_to_players

Revision ID: 3e8a1b2c3d4f
Revises: 22e2cf1b1e69
Create Date: 2026-06-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e8a1b2c3d4f'
down_revision: Union[str, Sequence[str], None] = '22e2cf1b1e69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('players', sa.Column('image_url', sa.String(), nullable=True, comment='Player photo URL from Transfermarkt'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('players', 'image_url')
