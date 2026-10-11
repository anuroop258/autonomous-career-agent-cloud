from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "tools"))
import private_bundle
import set_run_limit

class PrivateBundleTests(unittest.TestCase):
    def test_encrypted_bundle_round_trip_and_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            root.mkdir()
            (root / "profile.json").write_text('{"candidate":"sample"}', encoding="utf-8")
            (root / "applications.db").write_bytes(b"test sqlite payload")
            (root / "resume").mkdir()
            (root / "resume" / "master_resume.tex").write_text("\\documentclass{article}", encoding="utf-8")
            (root / "cloud_private" / "sessions").mkdir(parents=True)
            (root / "cloud_private" / "sessions" / "naukri.json").write_text('{"cookies":[]}', encoding="utf-8")
            (root / "not-private.txt").write_text("must not enter encrypted bundle", encoding="utf-8")
            enc = Path(td) / "bundle.enc"
            restored = Path(td) / "restored"
            key = Fernet.generate_key()
            private_bundle.encrypt(root, enc, key)
            raw = enc.read_bytes()
            self.assertNotIn(b"sample", raw)
            private_bundle.decrypt(enc, restored, key)
            self.assertEqual((restored / "profile.json").read_text(encoding="utf-8"), '{"candidate":"sample"}')
            self.assertEqual((restored / "applications.db").read_bytes(), b"test sqlite payload")
            self.assertTrue((restored / "resume" / "master_resume.tex").exists())
            self.assertTrue((restored / "cloud_private" / "sessions" / "naukri.json").exists())
            self.assertFalse((restored / "not-private.txt").exists())

    def test_rejects_path_traversal(self):
        self.assertFalse(private_bundle._inside_allowed_area(private_bundle.PurePosixPath("../evil.txt")))
        self.assertFalse(private_bundle._inside_allowed_area(private_bundle.PurePosixPath("/etc/passwd")))

class RunLimitTests(unittest.TestCase):
    def test_sets_only_selected_portal_config_and_enforces_cap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "role_config.json"
            cfg.write_text(json.dumps({"target_native_applications": 20, "other": 99}), encoding="utf-8")
            original = set_run_limit.ROOT
            set_run_limit.ROOT = root
            try:
                original_argv = sys.argv[:]
                try:
                    sys.argv = ["set_run_limit.py", "--portal", "naukri", "--max-jobs", "2"]
                    self.assertEqual(set_run_limit.main(), 0)
                finally:
                    sys.argv = original_argv
                path = root / "role_config.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["target_native_applications"], 2)
                self.assertEqual(data["other"], 99)
            finally:
                set_run_limit.ROOT = original

if __name__ == "__main__":
    unittest.main()
