from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.services.settings import STYLE_CHOICES, VOICE_CHOICES


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None = None


class AdminUserListResponse(BaseModel):
    users: list[AdminUserOut]


class AdminUserCreateRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class AdminUserPatchRequest(BaseModel):
    is_active: bool


class AudioSettings(BaseModel):
    voice: str = Field(default="default")
    style: str = Field(default="conversational")

    def normalized(self) -> AudioSettings:
        voice = self.voice if self.voice in VOICE_CHOICES else "default"
        style = self.style if self.style in STYLE_CHOICES else "conversational"
        return AudioSettings(voice=voice, style=style)


class AudioSettingsResponse(BaseModel):
    settings: AudioSettings
    voice_choices: list[str] = list(VOICE_CHOICES)
    style_choices: list[str] = list(STYLE_CHOICES)
