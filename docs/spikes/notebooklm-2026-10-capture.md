# NotebookLM live capture — 2026-10-22

Recorded from the NotebookLM web app itself (signed-in Chromium, `mcp/capture-requests.mjs`
and helper scripts), against notebook `module-1` (one YouTube source). Every value below was
observed in a real request; nothing is inferred from the pinned connector's code. Requests
marked *aborted* were recorded and cancelled before reaching Google (no usage spent); the two
audio overviews were generated for real.

## Site and session

- NotebookLM is now **"Gemini Notebook" at `https://notebook.google.com`**.
  `notebooklm.google.com` redirects there.
- `notebooklm-mcp-server@4.0.2` hard-codes the old host. Its axios client drops the `Cookie`
  header on the cross-host redirect, so every call failed with "Authentication expired".
  This was **not DBSC**: copied cookies work against the new host. Fixed by patching
  `BASE_URL` at image build (`mcp/Dockerfile`).
- The upstream `auth` command exits on the signed-out landing page and exports no session.
  Replaced by `mcp/auth-login.mjs` (persistent profile, exports from `notebook.google.com`).
- A long-running browser on the same Google session rotates the cookies. After about an hour,
  the connector's exported copy was rejected (`RotateCookies` → HTTP 401). Re-exporting from
  the browser fixed it. Don't run the capture browser and the connector on one session for
  long.
- Usage is metered per **5-hour window** (RPC `EylDcb`). One audio generation cost about 9.8%
  of the window. Generate dialogs offer **Generate now** and **Generate later** (a
  background queue).

## STUDIO_GENERATE (`R7cb6c`)

`[clientOptions, notebookId, spec]`. The website always sends the same `clientOptions`:

```json
[2,null,null,[1,null,null,null,null,null,null,null,null,null,[1]],[[1,4,8,10,14,2,3,6]]]
```

The connector sends `[2]` for most types, and Google rejects its slide and report specs with
`[3]` INVALID_ARGUMENT, whichever build label is used.

`spec` always begins `[null, null, <type>, [[[sourceId]]], …]`. The option block's slot
depends on the type. In the tables below, `S` is `[[sourceId]]`.

### Audio Overview — type 1, slot 6

`[null, [focus|null, length|null, null, S, lang, null, format]]`

| Format | Code | Length options shown |
|---|---|---|
| Deep dive | 1 | Short 1, Default 2, Long 3 |
| Brief | 2 | none (length sent as `null`) |
| Critique | 3 | Short 1, Default 2 |
| Debate | 4 | Short 1, Default 2 |

The Hindi debate came back with a Hindi title ("AI की सोच भाषा या अनुभव"), so the options were
applied.

### Slide deck — type 8, slot 16

`[[focus|null, lang, format, length]]`. **Review slide outline** is a *top-level* flag
after the spec: the params become `[clientOptions, notebookId, spec, null, null, [1]]`.

- Format: Detailed deck **1**, Presenter slides **2**
- Length: Short **2**, Default **3**
- The outline-review follow-up (edit the draft outline, then build the deck) has **not been
  captured** yet. It needs a real generation.

### Reports

There are two formats, and they use different types.

**Interactive** (default) — type 11, slot 34: `[null, [null, lang]]`. The dialog has no
language control.

**Document** — type 2, slot 7: `[null, [title, description, null, S, lang, prompt(, 2)]]`.
A template must be chosen first. Templates are fixed title, description and prompt text,
sent verbatim:

- **Briefing doc**: "Briefing Doc" / "Key insights and important quotes" / its prompt
- **Study guide**: "Study Guide" / "Quiz with answer key plus glossary" / its prompt
- **Blog post**: "Blog Post" / "Informational article in the style of a blog post" / its
  prompt
- **Create your own**: "Create your own" / "Craft reports your way by specifying structure,
  style, tone and more" / the user's text, plus a trailing `2`. This route has its own
  language selector.
- **Suggested templates** are generated per source (four for this source), so they vary by
  module.

The full prompt strings are in `mcp/auth/capture-aborted.jsonl`, labelled `report-B-*`.

### Flashcards — type 4, slot 9

`[null, [1, null, focus|null, lang, null, null, [quantity, difficulty, images]]]`

- Quantity: Fewer 1, Standard 2, More 3
- Difficulty: Easy 1, Medium 2, Hard 3
- Include images: `[]`; Text only: `[1]`
- Language **is** supported. The connector never sent it.

### Quiz — type 4, slot 9

`[null, [2, null, focus|null, lang, null, null, null, [quantity, difficulty]]]`

- Quantity and difficulty codes are the same as for flashcards.
- On this account the dialog has **no "Include images" and no "Question types"**. Those
  appeared in the owner's own screenshot, so they are rolled out per account and can't be
  built or verified here.

### Infographic — type 7, slot 14

`[[focus|null, lang, null, orientation, detail, style]]`

- Orientation: Landscape 1, Portrait 2, Square 3
- Detail: Concise 1, Standard 2, Detailed (BETA) 3

| Visual style | Code |
|---|---|
| Auto-select | 1 |
| Sketch note | 2 |
| Professional | 3 |
| Bento grid | 4 |
| Editorial | 5 |
| Instructional | 6 |
| Bricks | 7 |
| Clay | 8 |
| Anime | 9 |
| Kawaii | 10 |
| Scientific | 11 |

### Languages

The dropdown offers 80 languages, labelled in their own script. The request sends a
BCP-47-style code: `en`, `hi`, `te`, `ta`, `kn`, `mr` were all observed.

## Retrieval

Raw content comes from the connector's `artifact_content_get`, which returns the artifact row
as `raw[0]`. Samples are in git-ignored `mcp/auth/content/`. Status `raw[0][4]`: 1 or 2 =
in progress, **3 = completed**, **6 = outline waiting for review**. `studio_poll` reports
type 11 (Interactive report) as `unknown`, and quiz as `flashcards` (both are type 4).

Seven real generations (two audio, two slide decks, report, flashcards, quiz, infographic)
confirmed that the options reach the output:

| Artifact | Options chosen | Result |
|---|---|---|
| Audio | Hindi, Debate | Hindi title, 6 min |
| Slides | Presenter, Short | 10 slides (an outline deck at Default length: 15) |
| Flashcards | Fewer, Text only, Telugu | 24 text-only cards in Telugu (but the *title* came back in Bengali script) |
| Quiz | Fewer, Hindi | 5 questions in Hindi |
| Infographic | Portrait | 1536 × 2752 PNG |

### Audio

The connector's `media_url` is always `null`. The URLs are in `raw[0][6]`:
`lh3.googleusercontent.com/notebooklm/…=mm,140`, plus `…m140-dv-mp2`, `=mm,hls` and `=mm,dash`
variants. They redirect via `lh3.google.com`, which needs the `.google.com` cookies, to
`googlevideo.com`. The result is **`audio/mp4` (AAC/m4a)**, not mp3: 5.8 MB for 359 s. A
client that drops cookies on redirect gets a sign-in HTML page instead.

### Slides

`raw[0][16]`:
- `[2]` is a list of slides: `[[imageUrl], one-line summary, full slide text]`. The image is
  a 1376 × 768 PNG.
- `[3]` is the **PDF** and `[4]` the **PPTX** download, both on
  `contribution.usercontent.google.com`.

### Slide outline review

While waiting (status 6), `raw[0][30][0]` lists the outline: `[0]` is the deck's style note,
and `[1..n]` are `"**Title**: description"` per slide. `raw[0][31]` holds the editor UI as a
JSON component (`CoOutlinerCard`).

- **Refine**: RPC `hRBcub` `[clientOptions, artifactId, null, [["feedback text"]]]`. This was
  recorded and cancelled, so its effect isn't observed yet.
- **Proceed** (build the deck): RPC `hRBcub` `[clientOptions, artifactId]`. Status goes to 2,
  then 3. The artifact ID is unchanged.

### Interactive report

`raw[0][34]` is a structured rich-text document: nested text runs for paragraphs, headings,
bold spans and lists. No HTML is returned.

### Document report

Content format **not captured**. Only the request was recorded.

### Flashcards and quiz

`artifact_content_get` returns `html`, which works. The data is JSON in the `data-app-data`
attribute:
- Flashcards: `{flashcards: [{f: {flashcardContentBlock: [{type: "text", content}]}, b: {…},
  c: topicIndex}], topics: {covered: […]}}`. There's a `data-flashcard-image-urls` attribute
  for image cards.
- Quiz: `{quiz: [{question, hint, answerOptions: [{text, isCorrect, rationale}]}], topics}`.
  Each question had 4 options, exactly 1 correct. There's a `data-image-urls` attribute.

### Infographic

`raw[0][14][2][0]`: `[_, [imageUrl], one-line summary, full text description]`. The image is
a PNG.

### Downloads and sessions

All downloads (slide PNGs, PDF, PPTX, infographic PNG) worked through the signed-in browser
(`ctx.request`, following redirects with cookies). A cookie-forwarding HTTP client in the
shim is not yet verified.

**Session sharing**: with the capture browser open, the connector's exported cookies were
rejected about 40 minutes after each export (`RotateCookies` → 401). Close the browser after
sign-in and let only the connector use the session.

## Source upload (2026-10-26)

How a module's link and uploaded PDFs reach NotebookLM as sources (resumable file upload
through the connector shim, automatic page-range splitting of oversized PDFs, source-ready
polling) is specified in section 3 of
`docs/superpowers/specs/2026-10-26-pdf-sources-design.md`. The end-to-end check for a
PDF-only module is `frontend/src/e2e/admin-pdf-ingestion.spec.ts` (fixture provider only).
