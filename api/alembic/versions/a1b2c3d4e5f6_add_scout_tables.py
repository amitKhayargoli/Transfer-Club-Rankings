"""add_scout_tables_for_scouting_pipeline

Revision ID: a1b2c3d4e5f6
Revises: 22e2cf1b1e69
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '22e2cf1b1e69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add scout tables."""
    # ── scout_supplementary: wages, contracts, market values ──
    op.create_table(
        'scout_supplementary',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('player_name', sa.String(), nullable=False),
        sa.Column('team', sa.String(), nullable=False),
        sa.Column('season', sa.String(), nullable=False),
        sa.Column('league', sa.String(), nullable=False),
        sa.Column('league_tm_id', sa.String(), nullable=True, comment='Transfermarkt competition ID, e.g. GB1'),
        sa.Column('player_id', sa.Integer(), nullable=True, index=True, comment='FK to players.player_id'),
        sa.Column('transfermarkt_id', sa.Integer(), nullable=True, comment='Raw TM ID from CSV (parsed from float)'),
        sa.Column('market_value_eur', sa.Float(), nullable=True),
        sa.Column('weekly_wage_eur', sa.Float(), nullable=True),
        sa.Column('annual_wage_eur', sa.Float(), nullable=True),
        sa.Column('contract_expiry', sa.String(), nullable=True),
        sa.Column('release_clause_eur', sa.Float(), nullable=True),
        sa.Column('fotmob_id', sa.Float(), nullable=True),
        sa.Column('fotmob_xg', sa.Float(), nullable=True),
        sa.Column('fotmob_shots', sa.Float(), nullable=True),
        sa.Column('fotmob_key_passes', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    # Composite index for joining by (player_name, team, season, league)
    op.create_index(
        'ix_scout_supplementary_lookup',
        'scout_supplementary',
        ['player_name', 'team', 'season', 'league'],
    )

    # ── scout_player_stats: performance metrics as JSON blob ──
    op.create_table(
        'scout_player_stats',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('player_name', sa.String(), nullable=False, index=True),
        sa.Column('team', sa.String(), nullable=False),
        sa.Column('season', sa.String(), nullable=False, index=True),
        sa.Column('league', sa.String(), nullable=False),
        sa.Column('league_tm_id', sa.String(), nullable=True),
        sa.Column('player_id', sa.Integer(), nullable=True, index=True, comment='FK to players.player_id'),
        sa.Column('minutes', sa.Integer(), nullable=True),
        sa.Column('goals', sa.Integer(), nullable=True),
        sa.Column('assists', sa.Integer(), nullable=True),
        sa.Column('position', sa.String(), nullable=True),
        sa.Column('age', sa.Float(), nullable=True),
        sa.Column('data', sa.String(), nullable=True, comment='JSON blob of all ~230 FBref/Understat metrics'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_scout_player_stats_lookup',
        'scout_player_stats',
        ['player_name', 'season', 'league'],
    )


def downgrade() -> None:
    """Drop scout tables."""
    op.drop_index('ix_scout_player_stats_lookup', table_name='scout_player_stats')
    op.drop_table('scout_player_stats')
    op.drop_index('ix_scout_supplementary_lookup', table_name='scout_supplementary')
    op.drop_table('scout_supplementary')
