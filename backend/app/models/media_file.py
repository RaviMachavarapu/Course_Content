from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.coltypes import media_file_kind_enum
from app.models.enums import MediaFileKind

if TYPE_CHECKING:
    from app.models.artifact_version import ArtifactVersion


class MediaFile(Base):
    __tablename__ = "media_file"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[MediaFileKind] = mapped_column(media_file_kind_enum, nullable=False)
    #: unique: looked up on every media request (and keys carry the revision)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifact_version: Mapped[ArtifactVersion] = relationship(back_populates="media_files")
