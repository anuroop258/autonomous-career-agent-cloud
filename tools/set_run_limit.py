"""Set the selected portal's configured target to a small, per-run maximum (1-5)."""
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIGS={
    "naukri": [(Path("role_config.json"), "target_native_applications")],
    "indeed": [(Path("platforms/indeed/role_config.json"), "target_direct_applications")],
    "linkedin": [(Path("platforms/linkedin/linkedin_config.json"), "target_native_applications"), (Path("platforms/linkedin/role_config.json"), "target_native_applications")],
    "shine": [(Path("platforms/shine/role_config.json"), "target_direct_applications")],
    "timesjobs": [(Path("platforms/timesjobs/role_config.json"), "target_applications")],
    "glassdoor": [(Path("platforms/glassdoor/role_config.json"), "target_direct_applications")],
}

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--portal",choices=sorted(CONFIGS),required=True); ap.add_argument("--max-jobs",type=int,required=True); args=ap.parse_args()
    if not 1<=args.max_jobs<=5: ap.error("--max-jobs must be between 1 and 5")
    for rel,key in CONFIGS[args.portal]:
        path=ROOT/rel
        if not path.is_file(): continue
        obj=json.loads(path.read_text(encoding="utf-8"))
        if key not in obj and args.portal=="linkedin": continue
        obj[key]=args.max_jobs
        path.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        print(f"Set {rel.as_posix()}:{key}={args.max_jobs}")
    return 0
if __name__=="__main__": raise SystemExit(main())
