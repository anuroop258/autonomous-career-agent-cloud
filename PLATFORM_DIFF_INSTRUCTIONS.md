# Platform diff / change instructions

Use these rules for every future fix.

## 1. Choose the correct platform reference first

- **Naukri:** compare against the known-good Naukri flow in `naukri_agent.py` and its Naukri regressions.
- **Indeed:** compare against `platforms/indeed/indeed_agent.py` and its Indeed regressions.
- **LinkedIn:** compare against `platforms/linkedin/src/application/linkedin/linkedin_agent.py` and the proven LinkedIn fixed package.

Do not use another platform's application code as the reference for a platform-specific bug.

## 2. Matching is not application routing

The JD/profile matcher may share concepts, but Apply behavior is platform-specific.
A matcher fix must not silently change the application state machine.

## 3. Application workflow differences

| Platform | Native route | External route | Key workflow rule |
|---|---|---|---|
| Naukri | Naukri Apply/question flow | Company-site Apply | Applied-card pre-filter + fresh job tab + Naukri/native or company-site engine |
| Indeed | Indeed native Apply | External route when exposed | Strict experience/seniority gate + native Apply must enter Indeed's form engine |
| LinkedIn | Easy Apply | LinkedIn external Apply/interstitial | Zero-result search stops pagination; Easy Apply and external flows are separate |

## 4. Surgical-change rule

For a bug in one platform:

1. Reproduce it from the run log.
2. Identify the exact owner file/class.
3. Diff that owner against its platform-specific known-good reference.
4. Port only the proven fix plus a regression test.
5. Do not replace the other platforms' agents.
6. Do not change Chrome/CDP ports, search ownership, fresh job tabs, or safety boundaries unless the bug proves it necessary.
7. Run all three platform regression suites before packaging.

## 5. LinkedIn empty-result regression

The specific historical failure is:

`No matching jobs found -> start=25 -> start=50 -> ...`

The required behavior is:

`No matching jobs found -> stop this role immediately -> continue with next configured role/search`

Pagination must not be evaluated after an explicit empty-search state or a zero collected-job result.
