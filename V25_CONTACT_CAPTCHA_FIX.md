# V25 Contact + Indeed Human Verification Fix

This build changes only two production areas:

1. External company-form contact prefill
   - Deterministic pass runs before AI/LLM reasoning.
   - Fills full/first/last name, email and phone from profile.
   - Scans the main document and child iframes.
   - Does not use Custom Q&A or LLMs for identity/contact fields.
   - Re-runs after native Next/Continue transitions.

2. Indeed mid-flow human verification
   - Replaces stdin/ENTER blocking with in-browser polling.
   - The live application process remains running while the operator clears
     the human verification challenge.
   - Once the challenge disappears, the same application route resumes
     automatically.
   - Default timeout is 15 minutes; configurable with
     INDEED_HUMAN_VERIFICATION_TIMEOUT_SECONDS (30-3600 seconds).
   - Application tabs are preserved on timeout/failure.

The LinkedIn Easy Apply agent was not modified.
The current v21 platform location settings are preserved unchanged.
