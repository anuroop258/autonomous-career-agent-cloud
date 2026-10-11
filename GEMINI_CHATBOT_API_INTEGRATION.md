# Gemini Chatbot API Integration

## Acceptance ledger

- Reuse the working Gemini chatbot's `google-genai` client pattern.
- Keep the job-agent's deterministic/profile-grounded routing first.
- Send only unresolved/open-ended form questions to Gemini.
- Read `GEMINI_API_KEY` and `GEMINI_MODEL` from the same `.env` convention as the chatbot.
- Default model matches the supplied working chatbot: `gemini-3.5-flash-lite`.
- Never embed or copy an API key into source code or the ZIP.
- Keep bounded retries for transient Gemini provider failures such as 503/429.
- Preserve existing Ollama/OpenAI compatibility fallbacks and answer validation.

## Configuration

The reasoner checks, in order, for an explicit `GEMINI_ENV_FILE`, the project `.env`, a sibling `gemini_chatbot/.env`, the current working directory `.env`, and `gemini_chatbot/.env`. Existing process environment variables are not overwritten.

Example:

```text
GEMINI_API_KEY=YOUR_EXISTING_KEY
GEMINI_MODEL=gemini-3.5-flash-lite
ENABLE_GEMINI=1
OLLAMA_ENABLED=0
```

The supplied chatbot archive contains the `.env` file format but its uploaded key value is a placeholder, so no real secret was copied into this package.

## Code changes

`profile_reasoner.py` now uses `google.genai.Client(...).chats.create(...).send_message(...)`, matching the supplied working desktop chatbot. It creates a fresh chat per application question to prevent question-history contamination.

Naukri, Indeed, LinkedIn, and Glassdoor launchers no longer forcibly disable Gemini. Ollama remains disabled by default unless explicitly enabled.

## Verification evidence

- Gemini integration + Shine regression: 16 passed.
- Canonical reasoner/routing focused suite: 12 passed.
- Python compile check: to be run on final extracted package.
- Runtime API connectivity was not performed in this environment because the `google-genai` package is not installed and outbound package installation is unavailable here. The SDK call pattern is copied from the supplied working chatbot source.
