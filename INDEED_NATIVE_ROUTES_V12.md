# Indeed Native Routes v12

Indeed native Apply now uses exactly two application routes after the native `Apply with Indeed` CTA is clicked.

## Route 1 — direct submit
Apply with Indeed -> native review/resume state -> replace tailored resume when required -> final Submit -> confirmation.

Used only when there are no unanswered employer/application fields.

## Route 2 — questions to submit
Apply with Indeed -> detect real unanswered field -> fill and verify -> Next/Continue/Review -> repeat -> final Submit -> confirmation.

The route stays `questions_to_submit` through the final Submit checkpoint. Generic `Apply`, `Apply now`, and `Apply again` are never used as question-step progression controls.

If an unresolved native state occurs after Apply has been clicked, the application tab remains open for manual completion.
