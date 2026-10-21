"""Reject incorrect or tampered CI payloads before native execution/publication."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

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
