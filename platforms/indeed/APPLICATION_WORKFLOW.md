# Indeed native application workflow

The native Indeed flow has exactly two routes after `Apply with Indeed`: 

## Route 1 — direct submit
`Apply with Indeed -> native review/resume state -> tailored resume replacement when required -> final Submit -> confirmation`

This route is used only when there are no unanswered employer/application fields. A page that merely contains a `Submit` control is not enough to bypass real unanswered fields.

## Route 2 — questions to submit
`Apply with Indeed -> detect real unanswered fields -> fill + verify -> Next/Continue/Review -> repeat -> final Submit -> confirmation`

Only explicit progression controls (`Next`, `Continue`, `Review`, `Save and continue`, `Save & continue`, `Done`, `Finish`) are allowed to advance this route. Generic `Apply`, `Apply now`, and `Apply again` controls are never treated as question-step controls.

After native Apply has been clicked, unresolved/partial states preserve the live application tab for manual completion.
