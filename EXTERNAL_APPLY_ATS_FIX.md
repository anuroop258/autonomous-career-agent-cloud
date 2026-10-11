# External Apply CTA ATS Fix

Changed only `src/application/common/company_website_agent.py` apply-button detection/click logic.

Supported structures verified from supplied pages:
- Oracle HCM / American Express: `button.apply-now-button` with `Apply Now` label.
- Workday / Dentsu: `a[data-automation-id="adventureButton"][role="button"]` with `href` ending in `/apply`.
- Zoho Recruit / Busigence: `input[type="button"][value="Apply Now"]` / `#zr-detail-view-applybtn`.

Existing text-based Apply discovery remains unchanged after the new structural fast path.
