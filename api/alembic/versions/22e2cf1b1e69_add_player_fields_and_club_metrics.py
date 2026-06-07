"""add_player_fields_and_club_metrics_windows

Revision ID: 22e2cf1b1e69
Revises: c667297c9beb
Create Date: 2026-06-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22e2cf1b1e69'
down_revision: Union[str, Sequence[str], None] = 'c667297c9beb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns to players table
    op.add_column('players', sa.Column('citizenship', sa.String(), nullable=True, comment='Comma-separated list of nationalities'))
    op.add_column('players', sa.Column('agent_name', sa.String(), nullable=True, comment='Agent representing the player'))
    op.add_column('players', sa.Column('contract_expiry_date', sa.Date(), nullable=True, comment='Contract expiry at current club'))

    # Create club_metrics_windows table
    op.create_table('club_metrics_windows',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False, index=True),
        sa.Column('window_key', sa.String(), nullable=False),
        sa.Column('total_transfers', sa.Integer(), nullable=True),
        sa.Column('median_roi', sa.Float(), nullable=True),
        sa.Column('annualized_roi', sa.Float(), nullable=True),
        sa.Column('total_profit', sa.Float(), nullable=True),
        sa.Column('hit_rate', sa.Float(), nullable=True),
        sa.Column('value_creation', sa.Float(), nullable=True),
        sa.Column('profit_per_deal', sa.Float(), nullable=True),
        sa.Column('buying_club_premium', sa.Float(), nullable=True),
        sa.Column('composite_score', sa.Float(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('club_id', 'window_key', name='uq_club_window')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('club_metrics_windows')
    op.drop_column('players', 'contract_expiry_date')
    op.drop_column('players', 'agent_name')
    op.drop_column('players', 'citizenship')
