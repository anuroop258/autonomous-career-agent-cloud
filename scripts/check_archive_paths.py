from pathlib import Path
import sys
import zipfile

archive = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../job_agent_v28_extract_safe.zip")
if not archive.is_file():
    raise SystemExit(f"archive not found: {archive}")
with zipfile.ZipFile(archive) as zf:
    paths = zf.namelist()
longest = sorted(((len(p), p) for p in paths), reverse=True)
limit = 160
if longest and longest[0][0] > limit:
    print(f"ARCHIVE_PATH_CHECK: FAIL longest={longest[0][0]} path={longest[0][1]}")
    raise SystemExit(1)
print(f"ARCHIVE_PATH_CHECK: PASS entries={len(paths)} longest={longest[0][0] if longest else 0}")
