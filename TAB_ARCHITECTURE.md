# Naukri tab ownership architecture

1. The search page is never used as the job/application page.
2. Every unique job is opened with `context.new_page()`.
3. `pages_before_apply` is captured immediately before Apply.
4. Only tabs created AFTER that Apply click can be adopted as that job's application tab.
5. Existing tabs are never selected as an application target, even if they are external.
6. If Naukri opens a native application popup, both the original job tab and the
   application tab remain open.
7. If the matching job's CTA is an external/company-site Apply, the CTA is not clicked;
   that job tab remains open and the agent proceeds to the next job.
8. After Apply is clicked, the owned tab is marked `leave_page_open=True`, so unknown
   questions, failed verification, errors, or a timeout do not destroy the partial state.
9. The next job always receives a fresh tab.
10. `live_applied_state()` uses bounded DOM getter timeouts, and each job has a 120-second
    orchestration timeout. A bad page cannot terminate the whole run.
