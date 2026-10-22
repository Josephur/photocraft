"""Reject incorrect or tampered CI payloads before native execution/publication."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ci


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        files = {}
        for name in ('photocraft', 'photocraft-cli', 'photocraft-8bf-worker32.exe', 'photocraft-8bf-worker64.exe',
                     'plugins/freecandy7.wasm', 'plugins/FreeCandy7-LICENSE', 'plugins/FreeCandy7-LICENSE-THIRD-PARTY',
                     'LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE', 'ATTRIBUTION.md', '8BF-COMPATIBILITY.md',
                     'README.txt', 'SOURCE-MANIFEST.json'):
            path = self.bundle / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(name.encode())
            files[name] = hashlib.sha256(name.encode()).hexdigest()
        self.receipt = dict(integration='a' * 40, embedded_build_sha='a' * 40, files=files,
                            target='x86_64-unknown-linux-gnu', manifest={'freecandy': {'files': [
                                {'destination': 'plugins/freecandy7.wasm', 'sha256': files['plugins/freecandy7.wasm']}]}})
        self.save()

    def save(self):
        (self.bundle / 'BUILD-RECEIPT.json').write_text(json.dumps(self.receipt))

    def test_revision_and_file_hashes_are_checked(self):
        ci.verify_bundle(self.bundle, 'a' * 40)
        with self.assertRaisesRegex(ValueError, 'revision'):
            ci.verify_bundle(self.bundle, 'b' * 40)
        (self.bundle / 'photocraft-8bf-worker32.exe').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            ci.verify_bundle(self.bundle, 'a' * 40)

    def test_missing_worker_and_path_escape_are_rejected(self):
        del self.receipt['files']['photocraft-8bf-worker32.exe']
        self.save()
        with self.assertRaisesRegex(ValueError, 'required'):
            ci.verify_bundle(self.bundle, 'a' * 40)
        self.receipt['files']['photocraft-8bf-worker32.exe'] = hashlib.sha256(b'photocraft-8bf-worker32.exe').hexdigest()
        self.receipt['files']['../outside'] = '0' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'escapes'):
            ci.verify_bundle(self.bundle, 'a' * 40)


class AutomationRootTests(unittest.TestCase):
    def test_editor_launch_keeps_one_document_read_root(self):
        output = Path("/qa")
        for platform in ("darwin", "win32"):
            with patch.object(ci.sys, "platform", platform):
                args = ci.editor_launch(Path("/bundle"), output, 1234, output / "token")
            self.assertEqual(args.count("--automation-read-root"), 1)
            self.assertEqual(Path(args[args.index("--automation-read-root") + 1]), output)

    def test_cli_layout_uses_exact_app_resources_workers_without_adjacent_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "bundle"
            originals = {"photocraft-cli": b"exact-cli", **{
                f"PhotoCraft.app/Contents/Resources/8bf/photocraft-8bf-worker{bits}.exe": str(bits).encode()
                for bits in (32, 64)}}
            for name, data in originals.items():
                path = bundle / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            cli = Path(ci.resources_layout_cli(bundle, root / "qa"))
            self.assertEqual(cli.read_bytes(), originals["photocraft-cli"])
            self.assertEqual(cli.parent.name, "MacOS")
            for bits in (32, 64):
                name = f"photocraft-8bf-worker{bits}.exe"
                self.assertFalse((cli.parent / name).exists())
                self.assertEqual((cli.parent.parent / "Resources/8bf" / name).read_bytes(), str(bits).encode())
            for name, data in originals.items():
                self.assertEqual((bundle / name).read_bytes(), data)
