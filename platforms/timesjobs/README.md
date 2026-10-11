# TimesJobs Agent

Backend-only TimesJobs automation adapter. No React/webapp connection is included.

## UI flow from the supplied recording

- `timesjobs.com/myHome`
- open the search surface
- `Enter Skills, Designation, etc`
- optional `Enter locations`
- `Let's Find`
- collect `/job-detail/` links
- open the job detail
- inspect title, company, location, experience, and full visible JD
- apply through the visible `Apply` control
- handle TimesJobs' external-company redirect (the recording shows an HCLTech external route)

## Chrome

Attach-only. The agent does not launch Chrome.

Default CDP: `http://127.0.0.1:9222`

Override with `TIMESJOBS_CDP_PORT`.

## Run

```powershell
python platforms/timesjobs/timesjobs_main.py
```

Optional direct job URL:

```powershell
python platforms/timesjobs/timesjobs_main.py "https://www.timesjobs.com/job-detail/..."
```

External company application dry-run defaults to `true` through `TIMESJOBS_DRY_RUN=true`.

Set `TIMESJOBS_DRY_RUN=false` only when you are ready to allow the shared company-site engine to submit.

Persistent duplicate prevention uses the existing `applications.db` result table; jobs are recorded after they are actually processed, not bulk-marked during search discovery.
