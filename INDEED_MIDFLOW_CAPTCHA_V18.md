# Indeed mid-flow human verification fix — v18

## Behavior

Indeed can insert a CAPTCHA / human-verification challenge after the native application has already started. The automation now:

1. detects a visible challenge during the application loop;
2. keeps the application tab open;
3. prints an explicit manual-action message;
4. waits for the operator to clear the challenge in Chrome;
5. waits for the operator to press ENTER;
6. re-checks that the challenge is gone;
7. resumes the same native route instead of restarting or closing the application.

The same pause/check is also applied around the observed resume replacement sequence:

`Resume/Edit -> CV options -> Upload a different file -> file selection -> Continue -> review`

CAPTCHA solving itself is never automated or bypassed.
