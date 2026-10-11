# LinkedIn External Apply Regression Verification

## Restored workflow

LinkedIn external/company-site application routing now follows the working controlled flow:

1. Detect and validate the external Apply CTA.
2. Click the validated external CTA.
3. Adopt the resulting non-LinkedIn application page.
4. Hand the application page to `CompanyWebsiteAgent` using the existing job-specific tailored resume.
5. Keep the source LinkedIn job tab open.
6. Treat CAPTCHA/OTP/security verification as stop points.

## Regression protection

Updated:
- `platforms/linkedin/linkedin_agent.py`
- `tests/test_external_apply_routing.py`
- `platforms/linkedin/test_external_apply_boundary.py`

## Verification evidence

- `python -m py_compile platforms/linkedin/linkedin_agent.py` — passed
- Focused LinkedIn/external/frontend wiring suite — **27 passed**

The broader `tests/test_reasoning_fallbacks_and_safety.py` collection was not used as the acceptance gate for this repair because it currently has unrelated import/provider failures in the extracted bundle.
