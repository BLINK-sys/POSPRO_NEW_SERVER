from extensions import db
from datetime import datetime


class AIConsultantAccess(db.Model):
    """
    Single-row settings table that controls who can use the AI Consultant
    (`/ai` page). Owner (bocan.anton@mail.ru) edits this from the admin
    panel — see `/api/admin/ai-consultant/settings`.

    Flags are checked per-request by `/api/ai-consultant/access` using
    the JWT of the calling user (or guest if no JWT).
    """
    __tablename__ = 'ai_consultant_access'

    id = db.Column(db.Integer, primary_key=True)

    # Group flags — apply to entire user category
    allow_guest = db.Column(db.Boolean, default=False, nullable=False)
    allow_registered = db.Column(db.Boolean, default=False, nullable=False)
    allow_wholesale = db.Column(db.Boolean, default=False, nullable=False)

    # Per-system-user opt-in for the AI Consultant chat (`/ai`).
    # Stored as JSON list of system_users.id. Empty by default.
    allowed_system_user_ids = db.Column(db.JSON, default=list, nullable=False)

    # Per-system-user opt-in for the AI-driven Product Import in the
    # admin product create form. Same shape as allowed_system_user_ids
    # but a separate list — the two features are gated independently.
    allowed_product_import_user_ids = db.Column(db.JSON, default=list, nullable=False)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_email = db.Column(db.String(255))

    def to_dict(self):
        return {
            'id': self.id,
            'allow_guest': bool(self.allow_guest),
            'allow_registered': bool(self.allow_registered),
            'allow_wholesale': bool(self.allow_wholesale),
            'allowed_system_user_ids': list(self.allowed_system_user_ids or []),
            'allowed_product_import_user_ids': list(self.allowed_product_import_user_ids or []),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by_email': self.updated_by_email,
        }

    @classmethod
    def get_or_create(cls):
        """Single-row pattern — return the singleton row, creating if missing."""
        row = cls.query.first()
        if not row:
            row = cls(
                allow_guest=False,
                allow_registered=False,
                allow_wholesale=False,
                allowed_system_user_ids=[],
                allowed_product_import_user_ids=[],
            )
            db.session.add(row)
            db.session.commit()
        return row
