# Original Workflow Comparison — V19

Checked against the earlier V13 workflow and the earlier company-named-resume build.

## Preserved
- LinkedIn agent source is unchanged from V13 (same SHA-256).
- Naukri agent source is unchanged from V13 (same SHA-256).
- Portal CDP ports remain Naukri/Indeed=9222 and LinkedIn=9232.
- Native/external application logic remains separate.
- Tab-persistence behavior remains intact.

## Corrected regressions/behavior drift
- The launcher no longer forcibly disables `ENABLE_GEMINI` and `OLLAMA_ENABLED`.
- Web control-plane automation is now tracked per portal instead of one global process.
- LinkedIn, Indeed, and Naukri can run concurrently from the dashboard.
- Stopping runs terminates only the automation process tree(s), not Chrome/CDP.
- Restarting a stopped portal does not require closing Chrome.
- Portal launch does not spawn a duplicate Chrome instance when the CDP port is already connected.
- Tailored resume output is cached by JD/master/profile hashes to avoid rebuilding an identical resume on repeated runs.

## Timing check
A local isolated comparison showed the new ATS tailor itself remains sub-0.1s before PDF compilation; PDF verification adds about 0.1s. This is not a LinkedIn navigation delay. The LinkedIn platform agent source contains the same waits as V13.
