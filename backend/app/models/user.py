"""`user` — admins and students share one table, separated by `role`.

Fields per PROJECT_FRAME.md §8.1. Admins are created only via the `seed-admin`
CLI or admin-only user management; students self-register (T008).
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    student = "student"


def normalize_email(email: str) -> str:
    return email.strip().lower()


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", validate_strings=True), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User {self.email} ({self.role.value})>"
