# External resume named-selection fix

## Root cause fixed
1. The generic `AIFormEngine` could upload the master `resume.pdf` before the canonical company-site uploader ran.
2. `CompanyWebsiteAgent` then treated `self.resume_uploaded=True` as final state, so the job-specific tailored resume was never selected.
3. LinkedIn native Easy Apply used only `input[type=file]`; the observed UI exposes an `Upload resume` button and creates the chooser/input after that control is pressed.

## New flow
Job-specific tailored PDF -> unique upload filename -> press `Upload resume` when needed -> file chooser/input -> verify exact filename -> select the exact named resume option when exposed -> only then continue to Next/Apply.

The generic AI form engine is now prevented from owning resume uploads inside the company-site flow.
