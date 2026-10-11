# Job Automation QA/Filling Debug Agent

This package is specifically for failures where profile facts already exist but the automation cannot answer questions or fill the corresponding web form fields.

Primary targets:
- question answering
- profile fact routing
- DOM label -> input association
- answer normalization/validation
- form filling
- fill verification
- LLM fallback isolation
- cross-platform regression safety

This is NOT a generic browser/CDP debugger.

## Use

1. Copy these files into the root of the existing job-automation repository.
2. Run the inventory script:

```powershell
python .\scripts\qa_fill_inventory.py --project .
```

3. Give `QA_FILL_DEBUG_AGENT.md` to your repository-capable coding agent (OpenHands/Cline/etc.).
4. Require the agent to reproduce the failing question/fill behavior before editing.
5. Do not accept "fixed" based only on pytest/compile.

The agent's primary acceptance criterion is:
A known answer stored in the established profile source reaches the correct form field, is filled with the correct value/type, and is verified on the page.
