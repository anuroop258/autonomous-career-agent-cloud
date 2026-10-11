# SmartApply Forensic Debugger

Copy `scripts\smartapply_forensics.py` into the root of your existing project.

Run while the SmartApply application tab is OPEN:

```powershell
python .\scripts\smartapply_forensics.py --cdp-url http://127.0.0.1:9222
```

Then inspect:

```powershell
Get-Content .\debug-evidence\smartapply-forensics.json -Raw
```

This tool is read-only and model-free. It inspects every open page/frame,
standard controls, labels/ARIA/placeholders, nearby context, forms, and open
shadow-DOM controls. It does not click, type, fill, submit, or modify the page.
