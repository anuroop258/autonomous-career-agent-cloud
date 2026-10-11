# Indeed Native Resume Flow v16

## Observed live flow
The supplied screen recording shows the SmartApply resume-selection sequence:

1. Resume/Edit
2. CV options
3. Upload a different file
4. Native Windows file chooser
5. Select the tailored PDF
6. Return to the resume-selection page
7. Continue
8. Return toward the review/submission surface

## v16 changes
- Resume Edit detection is scoped to the Resume card and supports buttons, links, and custom clickable wrappers.
- CV Options is clicked with exact-label matching and an explicit wait for the animated menu.
- Upload a different file is waited for before proceeding.
- Native file chooser is captured with Playwright and the job-specific tailored PDF is selected.
- DOM file-input fallback remains available.
- Upload confirmation is verified before clicking Continue.
- Continue is clicked and the destination review/submission state is verified before marking resume replacement complete.
- Native application tabs remain open when any downstream step fails or is uncertain.

The Easy Apply/LinkedIn frozen layer is not modified by this change.
