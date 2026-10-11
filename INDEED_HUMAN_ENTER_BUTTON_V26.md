# Indeed Human Verification — Explicit Enter/Continue (v26)

When Indeed presents a real human-verification challenge, the agent pauses the live flow and keeps the application tab open.

The dashboard exposes **Enter / Continue Indeed** only while the Indeed run is waiting for human verification. The operator clears the challenge in Chrome and then presses the dashboard button. The same Indeed process resumes from the paused step.

There is no automatic resume and no second Start action. If the challenge is still visible when the button is pressed, the agent continues waiting rather than advancing incorrectly.
