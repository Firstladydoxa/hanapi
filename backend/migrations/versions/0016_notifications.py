"""In-app notifications."""
from alembic import op
from app.models.db import Notification

revision = "0016_notifications"
down_revision = "0015_rhapsody_permanent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Notification.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Notification.__table__.drop(bind=op.get_bind(), checkfirst=True)
