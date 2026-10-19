# Fixture: `sample-neural-nets`

Deterministic stand-in content used by `FixtureProvider` (dev + CI). The HTML
files loosely mirror NotebookLM Studio output so the type-specific parsers
(T021) have something realistic to consume.

- `*.html` — raw Studio-style markup per artifact type
- `infographic.mind_map.json` — the `mind_map_tree` returned in `RawArtifact.extras`
- `audio_overview.mp3` — a tiny placeholder MP3 (valid frame syncs, silent);
  **not** real audio, just enough bytes to exercise `fetch_binary` and storage.
