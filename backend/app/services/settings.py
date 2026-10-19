"""Small admin-tunable runtime settings, persisted in the `app_meta` KV table.

v1 only carries the Audio Overview defaults (spec.md §3.6) — the minimal
voice/style parameters forwarded to `audio_overview_create` once the NotebookLM
MCP is wired (T016). Until then they are simply stored and shown.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.app_meta import AppMeta

_AUDIO_KEY = "audio_settings"

VOICE_CHOICES = ("default", "warm", "bright", "calm")
STYLE_CHOICES = ("conversational", "deep_dive", "brief")

_AUDIO_DEFAULTS: dict[str, str] = {"voice": "default", "style": "conversational"}


def get_audio_settings(session: Session) -> dict[str, str]:
    row = session.get(AppMeta, _AUDIO_KEY)
    if row is None:
        return dict(_AUDIO_DEFAULTS)
    try:
        stored = json.loads(row.value)
    except (ValueError, TypeError):
        return dict(_AUDIO_DEFAULTS)
    return {**_AUDIO_DEFAULTS, **{k: str(v) for k, v in stored.items() if k in _AUDIO_DEFAULTS}}


def set_audio_settings(session: Session, *, voice: str, style: str) -> dict[str, str]:
    value = {"voice": voice, "style": style}
    row = session.get(AppMeta, _AUDIO_KEY)
    if row is None:
        row = AppMeta(key=_AUDIO_KEY, value=json.dumps(value))
        session.add(row)
    else:
        row.value = json.dumps(value)
    session.flush()
    return value
