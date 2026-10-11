# Form Intelligence Upgrade

This patch addresses failures where the agent understands the candidate answer but identifies the wrong question/field, especially questions containing the word `experience`.

## What changed

- Added `QuestionIntentRouter` to distinguish:
  - skill/hands-on experience yes/no
  - project experience yes/no
  - professional/skill experience in years
  - open-ended experience questions
  - generic yes/no/select/open-text questions
- `experience` alone no longer maps to `experience_years`.
- The common form observer now captures `aria-describedby`, semantic group context, fieldset/radiogroup context, and radio-group answer options.
- The reasoner receives lightweight application context (job role, field semantic, widget and local question context) while remaining backwards compatible with older provider hooks.
- LinkedIn question extraction is now control-first and scoped to the active Easy Apply dialog instead of taking the first visible heading/label on the page.
- LinkedIn filling now ranks selects, radios, checkboxes and text inputs by the current question's semantic context.
- Indeed keeps the frame-aware scanner but restores deterministic-first field routing so known fields (for example LinkedIn Profile) are not displaced by an unrelated control.
- Known compatibility adapters were restored to the canonical Naukri implementation.

## Regression coverage

`pytest -q` => **39 passed**.

The original regression tests remain covered. New tests specifically verify that:

- `Do you have hands-on experience with Python...` is not classified as years of experience.
- `How many years of professional Python experience...` is classified as years.
- `Describe your experience with Python...` is routed to the reasoner.
- The common form engine does not incorrectly select `experience_years` for a skill yes/no question.

## Application

Copy the files from this patch over the matching files in your current project. Keep your existing `profile.json`, application databases, browser profile/session, resumes, and debug evidence.
