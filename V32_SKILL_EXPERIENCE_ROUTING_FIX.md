# V32 Skill-Experience Routing Fix

## Acceptance ledger
- [x] Questions phrased as "how much/how many years of experience do you have in <skill>" route to a duration-specific path before generic open-ended generation.
- [x] Uses the existing `question_mappings` field definition and `skill_experience_years` profile data when available.
- [x] When a mapped skill has no explicit skill-duration value, falls back only to documented professional experience years; no experience is invented.
- [x] Generic open-ended questions such as "Tell us about your relevant experience" remain on the existing generative path.
- [x] Gemini prompt has an explicit skill-duration task instruction as a defensive fallback.

## Observed failure
"How much experience do you have in Deep Learning?" was being treated as a generic textarea/open-ended generation task. Gemini consequently returned a general profile paragraph instead of a direct experience-duration answer.

## Fix
The shared `ProfileReasoner` now detects explicit skill-duration wording and resolves configured `question_mappings` entries before the generic open-ended path. The existing profile has a `deep_learning_experience` mapping to `skill_experience_years.Deep Learning`, but no explicit value for that skill, so the truthful professional duration falls back to the candidate's documented 0 professional years.

## Focused verification
- 8/8 focused tests passed (`test_skill_experience_routing.py` + `test_gemini_application_generation.py`).
- Python compilation passed.
- The broader existing `test_no_contact_leak.py` includes a pre-existing expectation for `Age` to classify as `unknown`, while the current classifier intentionally recognizes the explicit `age` field; that unrelated test was not changed.
