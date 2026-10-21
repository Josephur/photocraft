"""Exercise Git separation and packaged executable checks with disposable fixtures."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("nightly", Path(__file__).with_name("nightly.py"))
nightly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nightly)


class NightlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Nightly test")
        self.git("config", "user.email", "test@example.invalid")
        self.write("README.md", "Upstream\n")
        self.base = self.commit("upstream")
        self.git("checkout", "-b", "feature/8bf")
        self.write("compat/build-workers.sh", "feature-required builder\n")
        self.feature = self.commit("8bf")
        self.git("checkout", "-b", "nightly/source")
        self.source = self.feature
        self.git("checkout", "-b", "fork/nightly-tooling", self.base)
        self.write("README.md", "Our Photoshop plug-in nightly\n")
        self.write("nightly/README.md", "fork-only tooling\n")
        self.tooling = self.commit("tooling")
        self.manifest = dict(version=1, upstream=self.base, source=self.source,
                             features=[dict(name="8bf", branch="feature/8bf", commit=self.feature)],
                             excluded_branches=[])

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def write(self, path, text):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, title):
        self.git("add", ".")
        self.git("commit", "-m", title)
        return self.git("rev-parse", "HEAD")

    def test_pr_guard_allows_required_worker_builder_but_rejects_tooling_ancestry(self):
        nightly.check_pr(self.root, self.base, self.feature, self.tooling)
        self.git("merge", "--no-edit", self.feature)
        with self.assertRaisesRegex(ValueError, "fork-only"):
            nightly.check_pr(self.root, self.base, "HEAD", self.tooling)

    def test_assembly_includes_pins_and_branding_without_moving_features(self):
        self.write("nightly/manifest.json", json.dumps(self.manifest))
        self.tooling = self.commit("manifest")
        destination = Path(self.temp.name) / "assembled"
        nightly.assemble(self.root, self.manifest, destination, "nightly/test")
        self.assertEqual(self.git("rev-parse", "feature/8bf"), self.feature)
        self.assertIn("Photoshop", (destination / "README.md").read_text())
        self.assertTrue((destination / "compat/build-workers.sh").is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            nightly.assemble(self.root, self.manifest, destination, "nightly/test2")

    def test_missing_feature_and_dirty_tooling_fail_before_worktree_creation(self):
        manifest = dict(self.manifest, source=self.base)
        with self.assertRaisesRegex(ValueError, "does not contain"):
            nightly.validate_manifest(self.root, manifest)
        self.write("README.md", "uncommitted")
        destination = Path(self.temp.name) / "assembled"
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            nightly.assemble(self.root, self.manifest, destination, "nightly/test")
        self.assertFalse(destination.exists())

    def test_pe_requires_architecture_and_gui_subsystem(self):
        data = bytearray(512)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 128)
        data[128:132] = b"PE\0\0"
        struct.pack_into("<H", data, 132, 0x8664)
        struct.pack_into("<H", data, 152, 0x20B)
        struct.pack_into("<H", data, 220, 2)
        path = Path(self.temp.name) / "app.exe"
        path.write_bytes(data)
        nightly.verify_pe(path, 0x8664, gui=True)
        with self.assertRaisesRegex(ValueError, "architecture"):
            nightly.verify_pe(path, 0x14C)
        struct.pack_into("<H", data, 220, 3)
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "GUI"):
            nightly.verify_pe(path, 0x8664, gui=True)
        path.write_bytes(b"broken")
        with self.assertRaises(ValueError):
            nightly.verify_pe(path, 0x8664)


if __name__ == "__main__":
    unittest.main()
