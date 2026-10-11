# Indeed Native Apply Tab Persistence Fix — v11

## Root cause
After a successful `Apply with Indeed` click, `process_job()` sets `application_opened = True` and enters the native application engine. The cleanup `finally` block previously closed the current page whenever the returned status was not in a fixed allow-list. That allow-list did not cover every native-apply failure/partial state (for example resume upload verification failures), so a real application surface could be closed immediately after the Apply click.

## Fix
Once `application_opened` is true, the cleanup block no longer enters the generic page-close path. The live application page and its owning job tab are preserved unless the native application is confirmed submitted (`status == "applied"`).

This makes the post-click behavior:

`Apply with Indeed` -> application UI -> fill/review/submit or failure -> KEEP TAB OPEN unless submission is confirmed.

## Regression checks
`platforms/indeed/test_native_apply_tab_persistence_regression.py` verifies:
- `application_opened` is set before the application engine runs.
- A hard native-apply preservation branch exists.
- The preservation branch cannot execute `page.close()`.
