"""Duration of an MP4/M4A file, read from its `moov/mvhd` box.

NotebookLM's Audio Overview download is audio/mp4 (AAC); its duration isn't in
the artifact data, so it's read from the file itself (no new dependency).
"""

from __future__ import annotations

import struct


def _boxes(data: bytes, start: int, end: int) -> list[tuple[bytes, int, int]]:
    """(type, payload start, box end) for each box in data[start:end]."""
    out, pos = [], start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos : pos + 8])
        header = 8
        if size == 1:  # 64-bit size
            if pos + 16 > end:
                break
            size = struct.unpack(">Q", data[pos + 8 : pos + 16])[0]
            header = 16
        elif size == 0:  # box runs to the end
            size = end - pos
        if size < header or pos + size > end:
            break
        out.append((kind, pos + header, pos + size))
        pos += size
    return out


def mp4_duration_seconds(data: bytes) -> float | None:
    """Duration in seconds, or None if this isn't an MP4 with an mvhd box."""
    for kind, body, end in _boxes(data, 0, len(data)):
        if kind != b"moov":
            continue
        for inner, ibody, _iend in _boxes(data, body, end):
            if inner != b"mvhd":
                continue
            try:
                version = data[ibody]
                if version == 1:
                    timescale, duration = struct.unpack(">IQ", data[ibody + 20 : ibody + 32])
                else:
                    timescale, duration = struct.unpack(">II", data[ibody + 12 : ibody + 20])
            except (IndexError, struct.error):  # truncated mvhd
                return None
            return duration / timescale if timescale else None
    return None
