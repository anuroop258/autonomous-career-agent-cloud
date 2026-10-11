# Application Tab Persistence Policy

After a platform Apply CTA is successfully clicked, the application state owns the tab and the automation must not close it merely because a later step fails, times out, encounters an unknown question, cannot verify an answer, or cannot submit.

Applies to:
- LinkedIn native Easy Apply
- LinkedIn external/company-site handoff
- Indeed native Apply
- Indeed external/company-site handoff
- Naukri native application
- Naukri external/company-site handoff

Tabs may be closed only before an application attempt begins (for example an ineligible job or a job with no Apply CTA), or by an explicit user/browser shutdown.
