# Architecture Review — Question Routing + Custom Q&A

## Finding

The application architecture is fundamentally sound in its separation of browser/platform flow from shared form intelligence, but the **answer-source priority was wrong**.

The problematic order was:

```text
field/question
  -> fuzzy Custom Q&A
  -> profile reasoner / project resolver
  -> model fallback
```

That allowed a saved question such as:

```text
Experience and projects -> PROJECT ANSWER
```

to be reused for a different question such as:

```text
What are your projects?
```

because the old fuzzy matcher treated the single distinctive token `projects` as sufficient overlap.

## Corrected architecture

The answer pipeline is now:

```text
DOM field extraction
        |
        v
Semantic QuestionIntentRouter
        |
        +---- exact saved Custom Q&A ----> answer
        |
        v
Deterministic profile/project resolver
        |
        +---- known semantic question ----> grounded answer
        |
        v
Fuzzy Custom Q&A fallback
        |
        +---- ONLY when intent is unknown
        |
        v
Gemini / Ollama / other model fallback
        |
        v
Answer validation
        |
        v
Fill control
        |
        v
Post-fill verification
```

## Project-question behavior

Questions such as:

- What are your projects?
- Describe your projects
- Tell us about your projects
- What projects have you built?
- What projects have you worked on?

are now classified as `project_text` and routed to the profile-grounded project resolver.

The resolver builds the answer from the actual `projects` section of `profile.json`.

## Custom Q&A behavior

Exact normalized saved questions remain authoritative.

Example:

```text
Saved: Experience and projects
Live:  Experience and projects*
```

This still uses the saved answer.

However:

```text
Saved: Experience and projects
Live:  What are your projects?
```

no longer matches through fuzzy overlap.

Fuzzy matching now requires at least two meaningful overlapping content terms. A single shared word such as `projects` is insufficient.

Long helper text can still match safely when it contains the meaningful saved-question content, for example:

```text
Tell us about your experience and projects, including roles,
internships, and work you are proud of
```

## Frozen Easy Apply boundary

The LinkedIn Easy Apply CTA baseline remains frozen.

These functions were not changed by this architecture fix:

- `detect_apply_route`
- `click_easy_apply`
- `_wait_for_easy_apply_surface`

Therefore the Easy Apply freeze guard remains valid.

## Regression coverage

Validated together:

```text
33 targeted tests passed
```

The project-question regression specifically verifies that `PROJECT ANSWER` is not returned for `What are your projects?`, while exact saved Q&A behavior remains intact.
