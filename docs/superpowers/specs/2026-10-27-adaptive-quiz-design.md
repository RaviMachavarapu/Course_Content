# Adaptive quiz: instant feedback, scores, fresh questions on every retake — design

Date: 2026-10-27 · Status: draft for owner review · Branch: feature/pdf-sources

## 1. Goal

A student taking a quiz sees, right after answering each question, whether it was right, the correct answer and the explanation; gets a score at the end; and every retake shows new questions (multiple-choice and fill-in-the-blank) that the student hasn't seen before.

## 2. Owner decisions (2026-10-27)

| # | Decision |
|---|---|
| Q1 | Instant feedback per question (correct/incorrect + correct answer + explanation) and a score at the end. |
| Q2 | Retakes never repeat the student's earlier questions — every retake is a fresh set. |
| Q3 | Fresh sets come from NotebookLM **chat** (`notebook_query`) on the module's notebook — not Studio generation (no Studio quota; seconds, not minutes). Chosen after a live test. |
| Q4 | Question types: multiple-choice (4 options, one correct) **and** fill-in-the-blank. Fill-blank answers are words/plain numbers only; formula answers are asked as multiple-choice (owner decision, 2026-10-27). |
| Q5 | Attempt 1 = the admin-reviewed, published Studio quiz. Attempts 2+ = chat-generated sets (auto-validated, not admin-reviewed). |
| Q6 | Proof-quote check runs only when the module has PDF sources; link-only modules get format/answer checks only. |
| Q7 | Students download a questions-only quiz PDF; the full answer-key PDF is admin-only (already being built in the PDF fix wave). |

## 3. Live test evidence (chemistry module, notebook 29fa550e…)

One chat query asking for 10 questions (6 MCQ + 4 fill-blank, LaTeX, JSON, verbatim proof quote) returned in **41 s**: valid JSON, correct counts, 7/10 quotes found verbatim in the PDF text and 3/10 with all words present (PDF extraction splits sub/superscripts). Formulas used `\( … \)` delimiters despite being asked for `$`.

## 4. Behaviour

### 4.1 Attempt flow (student)
1. Student opens the quiz → the app starts (or resumes) an attempt. Attempt 1 uses the published Studio quiz questions; attempt N ≥ 2 uses the student's prepared fresh set (§4.3).
2. For each question the student answers (selects an option, or types the blank) and presses **Check**. The server grades that single answer and returns: correct/incorrect, the correct answer, the explanation. The answer is locked once checked.
3. After the last question: score (correct/total and percent) and a review list of all questions with the student's answer, the correct answer and explanation.
4. **Retake** starts the next attempt immediately with a fresh set.

### 4.2 Answer security
Correct answers and explanations are never sent to the browser before that question is checked. Grading is server-side. A question's answer is revealed only after the student locks an answer for it.

### 4.3 Fresh sets (chat generation)
- **When:** as soon as a student starts any attempt, the app prepares that student's *next* set in the background (Celery, own `quiz` queue, concurrency 1). If the student retakes before it's ready, the retake waits for it (progress message) — normally it's ready.
- **Prompt:** module notebook; ask for N questions (N = the Studio quiz's question count, default 10) — mix ~60% MCQ / ~40% fill-blank; strict JSON shape (as in §3); LaTeX formulas copied exactly from the source; verbatim proof quote; and a list of the student's previously seen question texts to avoid (most recent 60).
- **Validation (each question):** JSON shape; MCQ has exactly 4 distinct non-empty options and `correct_index` 0–3; fill-blank has exactly one `____` and a non-empty answer (+ optional accepted answers); not a near-duplicate (normalized text similarity ≥ 0.85) of any question the student has seen; if the module has PDF sources: the proof quote must be found in the module's PDF text after normalization (lowercase, collapse non-alphanumerics), or all its words present in order within a short window. Failing questions are dropped; if fewer than N remain, ask again once for the shortfall; if still short, serve what passed (minimum 5) or fall back to "no new questions available right now — try again later".
- **Notation:** `\( … \)` and `\[ … \]` are accepted as formula delimiters everywhere `$ … $` / `$$ … $$` are (web MathText, backend `_split_math`, PDF builders).
- **Limits:** chat uses the NotebookLM account's chat allowance (separate from Studio). Each prepared set is 1–2 chat queries. If chat is unavailable or rate-limited, preparation retries with back-off; the student sees the "try again later" message only if no prepared set exists.

### 4.4 Fill-in-the-blank answers and grading (revised 2026-10-27, owner decision)
- Fill-in-the-blank answers are **words or plain numbers only** (e.g. "racemic mixture", "5", "-3", "0.5", "50%", "40 °C"). A generated fill-blank question whose answer or any accepted answer contains formula notation (LaTeX delimiters or commands, `^`, `_`, `{}`, `/` between terms, √, chemical formulas with digits like H2O) is dropped at validation; the prompt asks for formula answers to be written as multiple-choice instead. The student never types a formula.
- Grading: Unicode NFKC; trim; collapse whitespace; map `−` (U+2212) to `-`; strip trailing sentence punctuation (`. , ; : ! ?` and quotes) but keep signs (`-`, `+`), `%` and `°`; a leading `.` before a digit becomes `0.`. Map curly quotes/apostrophes (’ ‘ “ ”) to straight ones and the en dash (–) to `-`; a trailing `'`/`’` directly after a digit is kept (prime, e.g. 3′). Case-insensitive, except case-sensitive when ANY of: the stored answer or the typed answer contains an uppercase letter that is not the first letter of a word (CO, Co/CO, NaCl, pH, mRNA); the stored answer contains a Greek letter (δ vs Δ); the stored answer is a single 1–2 letter token starting with a capital (element-symbol shape: C, Co, Na). Generation asks for common acceptable variants (plurals, spellings, hyphenation, unit spacing) in `accepted_answers`. Then exact match against the answer or any accepted answer.

### 4.5 Admin view
- Inspect/Staging for a quiz shows, per quiz artifact: the published Studio quiz (as today) and a read-only list of recently generated sets with their validation results (kept/dropped + reason), so admins can audit chat questions.
- A per-module switch "Fresh questions on retake" (default on) lets admins turn chat generation off; when off, retakes reuse the Studio quiz (today's behaviour).

## 5. Data model
- `quiz_question_set`: id, artifact_id, user_id, source (`studio` | `chat`), status (`preparing` | `ready` | `used` | `failed`), questions JSONB (with answers — server-only), validation_report JSONB, created_at.
- `quiz_attempt` (existing): add `question_set_id`, per-question `answers_json` entries `{index, response, correct, checked_at}`, `completed_at`; score fields as today.
- Seen-question history = the questions of the student's previous sets for that artifact (no separate table).

## 6. API (student)
- `POST /api/student/artifacts/{id}/quiz-attempts` → start/resume; returns questions WITHOUT answers.
- `POST /api/student/quiz-attempts/{attempt_id}/answers` `{index, response}` → `{correct, correct_answer, explanation}`; 409 if already checked.
- `POST /api/student/quiz-attempts/{attempt_id}/complete` → score + full review.
- Existing `GET …/quiz-attempts` keeps listing past attempts with scores.

## 7. Errors
| Situation | Student sees |
|---|---|
| Next set still preparing | "Preparing new questions…" with progress, then starts |
| Chat failed / limited and no set ready | "New questions aren't available right now — please try again later" (attempt 1 always works) |
| Fewer than 5 valid questions | Same as above; admin sees the validation report |

## 8. Testing
Fake chat provider in unit tests (never live). Validation rules (each drop reason), grading normalization, answer secrecy (no answers in any student response before check), prepared-next-set flow, retake never repeats (seen-question filter), admin switch off → Studio quiz reused, attempt 1 uses the Studio quiz. Frontend: per-question Check → feedback, fill-blank input, score screen, retake. One owner-approved live check: two retakes on the chemistry module.

## 9. Out of scope
- Other question types (matching, ordering, numeric with tolerance).
- Admin editing of chat-generated questions.
- Cross-student question sharing or a global question bank.
