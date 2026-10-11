"""Encrypt/decrypt the small, user-specific data bundle for the free cloud runner.

The encrypted .enc file belongs in a second *private* GitHub repository. Never commit
plaintext profiles, session JSON, SQLite databases, or resumes to the source repository.
Requires cryptography (already listed by the cloud project requirements).
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile

from cryptography.fernet import Fernet, InvalidToken

PORTALS = {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}
BUNDLE_NAME = "career-agent-private.enc"


def _inside_allowed_area(rel: PurePosixPath) -> bool:
    parts = rel.parts
    if not parts or rel.is_absolute() or ".." in parts or "\\" in str(rel):
        return False
    if parts in {
        ("profile.json",), ("resume_content_bank.json",), ("applications.db",),
        ("applications.db-wal",), ("applications.db-shm",),
    }:
        return True
    if parts and parts[0] in {"resume", "resume_versions"} and len(parts) > 1:
        return True
    if parts[0] == "cloud_private" and len(parts) >= 3 and parts[1] == "sessions" and parts[-1].endswith(".json"):
        return True
    if len(parts) in (2, 3) and parts[0] == "platforms" and parts[1] in PORTALS:
        filename = parts[2] if len(parts) == 3 else ""
        return filename in {"profile.json", "applications.db", "applications.db-wal", "applications.db-shm"}
    return False


def collect_files(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    direct = [
        root / "profile.json",
        root / "resume_content_bank.json",
        root / "applications.db",
        root / "applications.db-wal",
        root / "applications.db-shm",
    ]
    candidates.update(p for p in direct if p.is_file())
    for portal in PORTALS:
        folder = root / "platforms" / portal
        for name in ("profile.json", "applications.db", "applications.db-wal", "applications.db-shm"):
            path = folder / name
            if path.is_file(): candidates.add(path)
    for folder_name in ("resume", "resume_versions"):
        folder = root / folder_name
        if folder.is_dir():
            candidates.update(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink())
    session_dir = root / "cloud_private" / "sessions"
    if session_dir.is_dir():
        candidates.update(p for p in session_dir.glob("*.json") if p.is_file() and not p.is_symlink())
    return sorted((p for p in candidates if not p.is_symlink()), key=lambda p: p.as_posix())


def _key(args) -> bytes:
    if getattr(args, "key_env", False):
        raw = os.getenv("CAREER_AGENT_PRIVATE_BUNDLE_KEY", "")
    else:
        raw = getattr(args, "key", None) or ""
    if not raw:
        raise ValueError("Provide --key, or set CAREER_AGENT_PRIVATE_BUNDLE_KEY and use --key-env")
    try:
        key = raw.encode("ascii")
        Fernet(key)  # validates the key format
        return key
    except Exception as exc:
        raise ValueError("Encryption key is not a valid Fernet key. Use the key printed by --generate-key.") from exc


def encrypt(root: Path, output: Path, key: bytes) -> int:
    root = root.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = collect_files(root)
    if not files:
        raise RuntimeError("No private profile/session/database/resume files were found. Refusing to create an empty bundle.")
    with NamedTemporaryFile(prefix="career-agent-bundle-", suffix=".zip", delete=False) as tmp:
        temp_zip = Path(tmp.name)
    try:
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in files:
                rel = path.relative_to(root).as_posix()
                if not _inside_allowed_area(PurePosixPath(rel)):
                    continue
                zf.write(path, arcname=rel)
        encrypted = Fernet(key).encrypt(temp_zip.read_bytes())
        output.write_bytes(encrypted)
        try: output.chmod(0o600)
        except OSError: pass
    finally:
        try: temp_zip.unlink()
        except OSError: pass
    print(f"Encrypted {len(files)} private files to: {output}")
    print("The output is encrypted. Store it only in your private data repository.")
    return 0


def decrypt(input_path: Path, root: Path, key: bytes) -> int:
    input_path = input_path.resolve()
    if not input_path.is_file(): raise FileNotFoundError(f"Encrypted bundle not found: {input_path}")
    try:
        plaintext = Fernet(key).decrypt(input_path.read_bytes())
    except InvalidToken as exc:
        raise RuntimeError("Could not decrypt the bundle. Check CAREER_AGENT_PRIVATE_BUNDLE_KEY.") from exc
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    with NamedTemporaryFile(prefix="career-agent-decrypt-", suffix=".zip", delete=False) as tmp:
        temp_zip = Path(tmp.name)
        tmp.write(plaintext)
    try:
        with zipfile.ZipFile(temp_zip, "r") as zf:
            for info in zf.infolist():
                if info.is_dir(): continue
                rel = PurePosixPath(info.filename)
                if not _inside_allowed_area(rel):
                    raise RuntimeError(f"Refusing unsafe/unexpected bundle path: {info.filename}")
                dest = root.joinpath(*rel.parts).resolve()
                if root not in dest.parents:
                    raise RuntimeError(f"Refusing path traversal: {info.filename}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(info))
                count += 1
    finally:
        try: temp_zip.unlink()
        except OSError: pass
    print(f"Restored {count} private files under {root}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    e = subs.add_parser("encrypt", help="create an encrypted private data bundle")
    e.add_argument("--root", type=Path, default=Path.cwd())
    e.add_argument("--output", type=Path, required=True)
    e.add_argument("--key", help="Fernet key; prefer --key-env for automation")
    e.add_argument("--key-env", action="store_true")
    e.add_argument("--generate-key", action="store_true", help="generate and print a new key; save it immediately")
    d = subs.add_parser("decrypt", help="restore files from an encrypted private data bundle")
    d.add_argument("--input", type=Path, required=True)
    d.add_argument("--root", type=Path, default=Path.cwd())
    d.add_argument("--key", help="Fernet key; prefer --key-env for automation")
    d.add_argument("--key-env", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "encrypt":
            if args.generate_key:
                if args.key or args.key_env:
                    parser.error("Use --generate-key alone; do not provide --key or --key-env")
                key = Fernet.generate_key()
                print("PRIVATE BUNDLE KEY (copy it now into GitHub Actions secret CAREER_AGENT_PRIVATE_BUNDLE_KEY):")
                print(key.decode("ascii"))
            else:
                key = _key(args)
            return encrypt(args.root, args.output, key)
        return decrypt(args.input, args.root, _key(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
