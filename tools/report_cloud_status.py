"""Best-effort status update for failures before tools/run_cloud_agent.py starts."""
from __future__ import annotations
import argparse, json, os, sys, urllib.request

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--status",choices=["failed","cancelled","completed"],required=True); ap.add_argument("--error",default=""); args=ap.parse_args()
    base=os.getenv("CLOUD_CONTROL_API_BASE","").rstrip("/"); key=os.getenv("CLOUD_CONTROL_API_KEY",""); task=os.getenv("CAREER_AGENT_TASK_ID","")
    if not base or not key or not task:
        print("Cannot report: missing control URL, API key or task ID.",file=sys.stderr); return 0
    payload=json.dumps({"task_id":task,"status":args.status,"error":args.error,"github_run_id":os.getenv("GITHUB_RUN_ID")}).encode()
    req=urllib.request.Request(base+"/api/worker/report",data=payload,method="POST",headers={"Content-Type":"application/json","X-API-Key":key})
    try:
        with urllib.request.urlopen(req,timeout=8) as resp: print("Reported workflow setup failure to control page.",resp.status)
    except Exception as exc: print(f"Could not report failure ({type(exc).__name__}).",file=sys.stderr)
    return 0
if __name__=="__main__": raise SystemExit(main())
