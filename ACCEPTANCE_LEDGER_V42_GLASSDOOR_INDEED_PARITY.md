# V42 Glassdoor / Indeed application-parity acceptance ledger

## Scope
Only Glassdoor's application-routing path is changed. Existing Indeed runtime/form engine and shared company-site engine remain authoritative.

## Required behavior

- Native Glassdoor Easy Apply must enter the same native SmartApply state machine used by Indeed.
- Native transition must wait for the concrete application surface before form processing.
- Native readiness, blocker/human-verification handling, question routing, profile filling, resume replacement/identity verification, progression, and final-submit gating must come from the proven Indeed engine.
- Glassdoor employer-site Apply must be detected from its explicit employer-site CTA, including the current `data-test="applyButton"` / `Apply on employer site` contract.
- Employer-site Apply discovery must tolerate delayed Glassdoor hydration and poll for the CTA before declaring it missing.
- After the employer-site redirect/new-tab transition, the canonical company-site engine must wait for the destination page before form processing.
- The canonical company-site engine remains responsible for external form filling, resume selection/upload, question routing, blocker detection, and submission safety.
- Application tabs must remain open after Apply when a downstream state is incomplete/error/blocked.

## Reviewed source evidence
- Glassdoor saved HTML contains `button[data-test="applyButton"]` labelled `Apply on employer site`.
- Existing Indeed native wait/resume/profile reports establish the frame-aware SmartApply readiness and resume/profile behavior.
- Existing shared company-site engine owns external page waiting and form readiness.

## Gates

1. `pytest -q platforms/glassdoor/test_glassdoor_regression.py` -> expected 12 passed.
2. Cross-platform focused native/external regression set -> expected 37 passed.
3. `python -m py_compile platforms/glassdoor/glassdoor_agent.py platforms/glassdoor/test_glassdoor_regression.py` -> exit 0.
4. Re-extract the final ZIP and rerun gates 1-3.

## Known unrelated baseline
`tests/test_external_apply_routing.py::test_linkedin_native_apply_accepts_plain_apply_label` remains a pre-existing stale static assertion: V37/V40 fail the same assertion because the source uses an equivalent whitespace-tolerant regex. It is outside the Glassdoor change and is not modified here.
