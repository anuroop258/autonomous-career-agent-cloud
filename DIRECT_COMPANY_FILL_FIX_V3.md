# Direct Company Fill V3

Built from the uploaded `ezyZip (13)(1).zip` baseline.

Fixes:
- `py main.py company-fill <URL> --platform linkedin --port 9232`
- Dashboard Custom Q&A is applied before semantic/profile fallbacks.
- Custom Q&A uses the visible field label before helper/context text.
- Custom Q&A dict answers are extracted correctly.
- Long helper text can still match a saved multi-word Q&A label when there is a strong content-token overlap.
- Native experience selects support `0-2`, `0–2`, `0—2`, `0−2`, `0 to 2`, `Less than 1 year`, `3+`, etc.
- Direct company-form tabs remain open.
- Gemini/Ollama are disabled for deterministic form filling.

Fill-only:
`py main.py company-fill "https://ringtrunk.com/careers/ai-engineer#application-form" --platform linkedin --port 9232`

Submit:
`py main.py company-fill "https://ringtrunk.com/careers/ai-engineer#application-form" --platform linkedin --port 9232 --submit`

Expected RingTrunk experience log:
`select_filled: semantic='experience' ...`
