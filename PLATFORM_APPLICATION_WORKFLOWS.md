# Platform-specific application workflows

These three platforms intentionally have separate application engines/facades.
The common matching/profile concepts may be shared, but the browser/application
state machines are platform-specific.

## Naukri

`naukri_agent.py` remains authoritative.

Flow:

`search controller -> Applied pre-filter -> fresh job tab -> JD/experience/AI gates -> native Naukri Apply OR controlled external-company Apply -> native form engine -> verify -> Continue/Next -> final submission gate`

Rules:
- Search and job tabs have separate ownership.
- Applied cards are filtered before opening when the live card exposes Applied.
- Every unique candidate gets an isolated job tab.
- Native Naukri questions use the Naukri deterministic/QA hierarchy.
- External/company-site routes are intentionally clicked only when the Apply CTA is validated as external, then handed to the canonical company-site form engine for fill/verify/submit behavior.
- CAPTCHA/OTP/security verification is never bypassed.

## Indeed

`platforms/indeed/indeed_agent.py` remains authoritative.

Flow:

`dedup -> search result -> fresh job tab -> JD/experience/seniority gate -> native Indeed Apply or validated external-company Apply -> application form -> answer/fill/verify -> Continue/Next -> final submission gate`

Rules:
- Indeed's strict entry-level/experience gate remains independent of the JD score.
- Native Indeed Apply is different from an external employer route.
- The native Apply result is followed by the existing Indeed application form engine.
- External employer routes are detected, the correct Apply CTA is clicked, and the resulting company-site page is handed to the canonical CompanyWebsiteAgent.
- Human/security verification is a stop point, not a bypass target.

## LinkedIn

`platforms/linkedin/src/application/linkedin/linkedin_agent.py` remains authoritative.

Flow:

`LinkedIn search controller -> collect jobs -> stop immediately on zero jobs -> fresh job tab -> JD/experience gate -> Easy Apply OR controlled external-company Apply -> LinkedIn native form engine -> verify -> next job`

Rules:
- A search page with zero collected LinkedIn job URLs ends that role search immediately.
- Pagination is evaluated only after a non-empty result page.
- The search controller is never reused as a job/application tab.
- Easy Apply has its own LinkedIn modal/question flow.
- External Apply is detected, the validated external CTA is clicked, and the resulting employer-site surface is handed to the canonical CompanyWebsiteAgent; CAPTCHA/OTP/security checks remain stop points.
- CAPTCHA/security verification is never bypassed.

## Non-negotiable separation

Do not copy application steps between platforms merely because the UI labels
look similar.  In particular:

- LinkedIn `Easy Apply` != Indeed `Apply` != Naukri `Apply`.
- External company-site redirects are launched only after the platform-specific job-page route is validated as external; security verification is never bypassed.
- Indeed native Apply can open an application page that must be handed to its
  Indeed form engine.
- Naukri has its own native questionnaire; external company-site routes are preserved for manual review.

The three `application_engine.py` files are intentionally thin facades over
these proven platform agents. They provide an explicit platform boundary while
avoiding a risky rewrite of the live application state machines.
