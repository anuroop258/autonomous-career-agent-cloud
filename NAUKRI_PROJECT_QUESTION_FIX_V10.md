# Naukri Project Question Fix v10

Root cause found in the v9 build:

1. Naukri keeps previous recruiter answers in the same conversation panel.
2. `visible_options()` scanned the whole visible dialog/chat and could expose a previous `Yes` answer as an option for the current open-ended project question.
3. `ProfileReasoner._project_experience_answer()` treated any non-empty options list as a multiple-choice context, so a question such as:
   `Could you briefly explain the AI projects or applications you have built?`
   could return `None` instead of the profile-grounded project answer.
4. The text filler also pressed Enter after filling, which is unsafe for Naukri panels that use a separate `Save` button.

v10 fixes all four points:

- answer-option discovery is scoped to the current question's geometry;
- action controls are filtered;
- open-ended project prompts ignore stray Yes/No transcript bubbles;
- project wording is classified as `project_text` even with natural recruiter phrasing;
- text/number fields are filled before any generic dropdown scan;
- automatic Enter is removed; the normal verified `Save`/`Next`/`Continue` path advances the panel.
