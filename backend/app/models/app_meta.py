"""`app_meta` — a trivial key/value table.

Proves the migration + session pipeline end to end (T004). Also a genuinely
useful home for singleton runtime facts (schema markers, one-off flags).
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AppMeta(Base, TimestampMixin):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
