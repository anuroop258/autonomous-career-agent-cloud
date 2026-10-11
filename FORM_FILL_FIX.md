# Form Fill Fix

## What was fixed

Indeed SmartApply forms can render employer fields as custom `role=textbox` / `role=combobox` controls instead of ordinary input/textarea/select elements. The previous unified scanner could therefore find no answerable fields and fall back to page-text question detection, which could select a marketing sentence such as "Ready to embark on this journey with us?" and stop as `unknown_question`.

The Indeed agent now:

- discovers visible `role=textbox` and `role=combobox` controls alongside normal controls;
- skips non-answerable roles such as button/radio/checkbox/option in the text-field pass;
- adds a deterministic profile-field recovery pass when the normal field scanner finds nothing;
- uses the canonical profile reasoner before Gemini/Ollama for profile facts;
- preserves verification before advancing the application.

This specifically allows known fields such as LinkedIn Profile to be filled without requiring Gemini or Ollama.

## Verification

`pytest -q` => **31 passed**.

The fix is code-level and regression-tested. A live Indeed/LinkedIn browser run is still required to verify against the current production DOM.
