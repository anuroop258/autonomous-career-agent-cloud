# Universal External Form Engine V2

This build keeps the proven Naukri/tab architecture and upgrades only the external-form layer.

## Runtime pipeline

1. **Observe** – build a structured snapshot of visible controls across the main document and Playwright frames.
2. **Classify** – resolve local labels/ARIA/name/placeholder before using HTML `type` as a fallback.
3. **Deterministic fill** – profile-backed values first.
4. **Adaptive widgets** – native selects, ARIA/custom comboboxes, checkboxes/radios, React/Vue controlled text fields, file inputs.
5. **Reason** – ambiguous/open-ended questions use the existing profile-grounded reasoner; Gemini first, Ollama fallback, then existing compatibility/local reasoning.
6. **Verify** – re-read the DOM after actions; do not assume a click/type succeeded.
7. **Block safely** – CAPTCHA/login/required-unresolved states stop progression but preserve the live application page.
8. **Next job isolation** – the surrounding runner keeps each application in its own fresh tab.

## Important behavior

- AI never receives direct browser control authority.
- The engine does not invent profile facts.
- Full Name semantics beat an incorrect `type=email` declaration.
- Experience `0` can match `Fresher`, `No experience`, `Less than 1`, and `0-1` style options.
- Resume selection respects `accept`; PDF is primary and bundled RTF is a fallback for RTF-only controls.
- CAPTCHA is not solved automatically. The form can still be filled before progression is blocked.
- A form without a consent checkbox is not considered unresolved merely because no terms control exists.
- Existing Naukri v27.1 application/state logic is intentionally not replaced.
