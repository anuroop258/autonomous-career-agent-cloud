# No Email Leakage Into Narrative Fields

## Acceptance ledger

- A field labelled `Message` or `Tell us about your relevant Experience` must never receive the candidate email solely because the ATS declares the HTML control as `type=email`.
- Email is filled only when the field's own label/placeholder/aria/name/id explicitly identifies email.
- Provider/model answers containing email are rejected for unrelated questions.
- `Tell us about your relevant Experience` has a deterministic project-grounded answer available even when Gemini is unavailable.

## Root cause evidenced by supplied run

The supplied run showed `field_filled: semantic='email' label='Message' name='Contact-Message-Field-01'`, followed by an email value being written to that field. The same run also showed Gemini unavailable because `google-genai` was not installed in the runtime.

## Fix

- Hardened `AIFormEngine` semantic classification against bogus `type=email` declarations and page-wide context contamination.
- Hardened `CompanyWebsiteAgent` classification and deterministic contact prefill.
- Added a final semantic defense before standard external-form fills.
- Extended deterministic experience-text matching.
- Added eight regression tests covering the exact failure mode, legitimate email fields, and the reasoner safety boundary.
