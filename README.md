# SmartApply Forensic Debugger

Model-free, read-only DOM inspection for the Indeed SmartApply bug where
`next_unanswered_field()` returns `None` even though a form is visible.

It does not use ChatGPT, Codex, Gemini, Ollama, Cline, or any other model.
It does not click, fill, submit, or modify the webpage.

## Install
Copy `scripts/smartapply_forensics.py` into the root of your existing project.

## Run
Keep the existing Chrome/CDP session and SmartApply tab open, then from the
project root:

```powershell
python .\scripts\smartapply_forensics.py --cdp-url http://127.0.0.1:9222
```

Outputs:

```text
debug-evidence\smartapply-forensics.json
debug-evidence\smartapply-screens\...
```

## It checks

- every page and iframe
- visible/hidden inputs, textareas, selects
- textbox/combobox/contenteditable/radio/checkbox
- label and associated label
- aria-label / aria-labelledby
- name/id/placeholder/autocomplete
- disabled/read-only/required state
- dimensions and computed visibility
- nearby container text
- open shadow DOM
- forms and likely application containers
- page body text
- screenshot of likely Indeed/SmartApply pages

This is meant to explain why the existing field-discovery code is seeing zero
fields on the real SmartApply DOM. It is intentionally separate from the
application engine so no production behavior is changed.


## v16 Indeed native resume replacement
The Indeed native review flow now follows the recorded Resume/Edit → CV options → Upload a different file → tailored PDF → Continue sequence with explicit post-step verification. See `INDEED_RESUME_FLOW_V16.md`.
