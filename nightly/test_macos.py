"""Universal packaging must reject incomplete slices and foreign runtime libraries."""
from pathlib import Path
import unittest
from unittest.mock import patch
import macos


class MacPackagingTests(unittest.TestCase):
    def test_both_universal_architectures_are_required(self):
        with patch.object(macos, 'run', return_value='x86_64 arm64'):
            macos.verify_architectures(Path('PhotoCraft'), ['arm64', 'x86_64'])
        with patch.object(macos, 'run', return_value='arm64'):
            with self.assertRaisesRegex(ValueError, 'expected'):
                macos.verify_architectures(Path('PhotoCraft'), ['arm64', 'x86_64'])

    def test_unbundled_homebrew_or_rpath_libraries_are_rejected(self):
        system = '\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\n'
        self.assertEqual(macos.system_dependencies(system), ['/usr/lib/libSystem.B.dylib'])
        for library in ('/opt/homebrew/lib/libexample.dylib', '@rpath/libexample.dylib'):
            with self.assertRaisesRegex(ValueError, 'unbundled'):
                macos.system_dependencies(system + '\t' + library + ' (compatibility version 1.0.0, current version 1.0.0)\n')
        with self.assertRaisesRegex(ValueError, 'no Mach-O'):
            macos.system_dependencies('invalid executable')
