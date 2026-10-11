# Native Profile + All-Platform Profile Data Fix V30

## Acceptance ledger

1. Every supported platform profile must retain the canonical root `profile.json` as `full_profile`.
2. Indeed, Shine, Glassdoor and TimesJobs form profiles must contain the verified core contact facts: name, email, phone, city, state, country and postal code.
3. The same four form profiles must contain the seven stored project records.
4. Indeed native form routing must recognize phone/contact controls even when the visible label is weak or absent and metadata (`autocomplete`, `type=tel`, `inputmode=tel`) carries the semantic signal.
5. The existing email-leak protection must remain: `type=email` alone must not turn a `Message` field into an email field.
6. Explicit email fields must continue to resolve as email.

## Evidence-supported result

- All five platform `full_profile` sections match the canonical root profile exactly.
- Indeed, Shine, Glassdoor and TimesJobs form profiles contain phone `7032164500`, email `anuroop954@gmail.com`, Hyderabad/Telangana/India/500089 and all seven project records.
- Indeed native semantic routing now considers `name`, `id`, `placeholder`, `aria-label`, `autocomplete`, `type`, `inputmode`, and `data-testid`.
- Strong telephone metadata maps to the verified phone field.
- Email is still label-gated when `type=email` is the only signal, preventing the previous Message-field leak.
- Native deterministic values include contact, education, compensation, experience, work-authorization, relocation, summary, certification and skill values that are actually represented by the profile.

## Test evidence

Focused changed-code gate: **29 passed**.

Compilation gate: `platforms/indeed`, `src/application/common`, `company_fill.py`, and `profile_reasoner.py` compile successfully.

A broader compatibility selection had unrelated pre-existing failures in old mock/source-contract tests; those were not used as the acceptance gate for this native profile-data change.
