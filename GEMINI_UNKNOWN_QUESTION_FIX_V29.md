# V29 — Gemini answering for unknown questions, connected properly

Flow (unchanged order): deterministic profile -> exact saved Q&A -> fuzzy Q&A (unknown intent only) -> **Gemini** -> Ollama -> OpenAI -> local.

## What was wrong
1. `company_fill.py` forced `ENABLE_GEMINI=0`, so direct company-site forms never reached Gemini.
2. Gemini answers with no `confidence` were stored as 0 and then dropped by the form engine (needs >= 0.65).
3. Answers with a missing/odd `kind`, or only `selected_options`, were discarded by validation.
4. `GEMINI_TIMEOUT` was never applied; a stalled call could hang a form.
5. A bad/placeholder key, missing SDK, or wrong model was retried on every question.
6. The prompt told Gemini to return null for open-ended text questions ("why this role?").
7. JSON was requested only by prompt text.

## Fixes (profile_reasoner.py, company_fill.py)
- Gemini no longer disabled in company_fill.
- Client uses `HttpOptions(timeout=GEMINI_TIMEOUT)`; config uses `response_mime_type="application/json"`.
- Placeholder key (`PASTE_YOUR_...`) = not configured.
- Permanent errors (invalid key, 401/403, 404 model, SDK missing) disable Gemini for the run with one clear log line; transient 429/503 still retry.
- Validation defaults missing confidence to 0.8, rejects < 0.5 and "null/unknown" strings, infers `kind`, accepts `selected_options`.
- Prompt allows concise profile-grounded first-person answers for open text questions.
- In-run cache so repeated questions across jobs cost one API call.
- Logs: "asking <model>", "answered ...", "rejected", "DISABLED".

## Setup
Copy `.env.example` to `.env`, set `GEMINI_API_KEY` (and `GEMINI_MODEL` if `gemini-3.5-flash-lite` is not valid for your key), `pip install -r requirements.txt`.

## Tests
6 new tests in `tests/test_gemini_chatbot_integration.py` pass. 3 pre-existing failures (Indeed mock `is_closed`, provider-failure mock, reasoner identity) fail identically on the original zip. Live Gemini calls were not run (no key/network here).
