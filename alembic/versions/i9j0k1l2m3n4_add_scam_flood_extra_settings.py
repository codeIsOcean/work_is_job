"""Add scam and flood extra settings columns

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2025-12-10

Adds extra settings columns for scam detector and flood detector:

SCAM:
- scam_action - action type for scam detection (delete/warn/mute/kick/ban)
- scam_mute_duration - mute duration in minutes
- scam_mute_text - custom mute notification text (%user% placeholder)
- scam_ban_text - custom ban notification text (%user% placeholder)
- scam_delete_delay - delay before deleting violator message (seconds)
- scam_notification_delete_delay - auto-delete notification after N seconds

FLOOD:
- flood_mute_text - custom mute notification text (%user% placeholder)
- flood_ban_text - custom ban notification text (%user% placeholder)
- flood_delete_delay - delay before deleting violator message (seconds)
- flood_notification_delete_delay - auto-delete notification after N seconds
"""
from alembic import op
import sqlalchemy as sa


revision = 'i9j0k1l2m3n4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add scam and flood extra settings columns."""

    # ─────────────────────────────────────────────────────────────
    # SCAM DETECTOR SETTINGS
    # ─────────────────────────────────────────────────────────────
    # Action type for scam (uses default_action if NULL)
    op.add_column('content_filter_settings', sa.Column(
        'scam_action',
        sa.String(20),
        nullable=True
    ))

    # Mute duration in minutes for scam
    op.add_column('content_filter_settings', sa.Column(
        'scam_mute_duration',
        sa.Integer(),
        nullable=True
    ))

    # Custom mute notification text (supports %user% placeholder)
    op.add_column('content_filter_settings', sa.Column(
        'scam_mute_text',
        sa.String(500),
        nullable=True
    ))

    # Custom ban notification text (supports %user% placeholder)
    op.add_column('content_filter_settings', sa.Column(
        'scam_ban_text',
        sa.String(500),
        nullable=True
    ))

    # Delay before deleting violator message (seconds)
    op.add_column('content_filter_settings', sa.Column(
        'scam_delete_delay',
        sa.Integer(),
        nullable=True
    ))

    # Auto-delete bot notification after N seconds (NULL = don't delete)
    op.add_column('content_filter_settings', sa.Column(
        'scam_notification_delete_delay',
        sa.Integer(),
        nullable=True
    ))

    # ─────────────────────────────────────────────────────────────
    # FLOOD DETECTOR SETTINGS
    # ─────────────────────────────────────────────────────────────
    # Custom mute notification text (supports %user% placeholder)
    op.add_column('content_filter_settings', sa.Column(
        'flood_mute_text',
        sa.String(500),
        nullable=True
    ))

    # Custom ban notification text (supports %user% placeholder)
    op.add_column('content_filter_settings', sa.Column(
        'flood_ban_text',
        sa.String(500),
        nullable=True
    ))

    # Delay before deleting violator message (seconds)
    op.add_column('content_filter_settings', sa.Column(
        'flood_delete_delay',
        sa.Integer(),
        nullable=True
    ))

    # Auto-delete bot notification after N seconds (NULL = don't delete)
    op.add_column('content_filter_settings', sa.Column(
        'flood_notification_delete_delay',
        sa.Integer(),
        nullable=True
    ))


def downgrade() -> None:
    """Remove scam and flood extra settings columns."""
    # Remove in reverse order

    # ─────────────────────────────────────────────────────────────
    # FLOOD DETECTOR SETTINGS
    # ─────────────────────────────────────────────────────────────
    op.drop_column('content_filter_settings', 'flood_notification_delete_delay')
    op.drop_column('content_filter_settings', 'flood_delete_delay')
    op.drop_column('content_filter_settings', 'flood_ban_text')
    op.drop_column('content_filter_settings', 'flood_mute_text')

    # ─────────────────────────────────────────────────────────────
    # SCAM DETECTOR SETTINGS
    # ─────────────────────────────────────────────────────────────
    op.drop_column('content_filter_settings', 'scam_notification_delete_delay')
    op.drop_column('content_filter_settings', 'scam_delete_delay')
    op.drop_column('content_filter_settings', 'scam_ban_text')
    op.drop_column('content_filter_settings', 'scam_mute_text')
    op.drop_column('content_filter_settings', 'scam_mute_duration')
    op.drop_column('content_filter_settings', 'scam_action')
