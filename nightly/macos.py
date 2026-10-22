#!/usr/bin/env python3
"""Fork-only native slices and universal, ad-hoc-signed macOS nightly bundle."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sys

import ci
import nightly

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {'arm64': 'aarch64-apple-darwin', 'x86_64': 'x86_64-apple-darwin'}


def run(args, capture=False):
    return nightly.command(args, ROOT, capture=capture)


def verify_architectures(path, required):
    found = set(run(['lipo', '-archs', path], capture=True).split())
    if found != set(required):
        raise ValueError(f'{path.name}: expected {required}, found {sorted(found)}')


def system_dependencies(output):
    dependencies = sorted(set(re.findall(r'^\s+(\S+)\s+\(compatibility version', output, re.MULTILINE)))
    if not dependencies:
        raise ValueError('no Mach-O dependencies found')
    foreign = [name for name in dependencies if not name.startswith(('/System/Library/', '/usr/lib/'))]
    if foreign:
        raise ValueError('unbundled macOS dependencies: ' + ', '.join(foreign))
    return dependencies


def build_slice(architecture, destination):
    if sys.platform != 'darwin':
        raise ValueError('native macOS builds require a Mac runner')
    nightly.clean(ROOT)
    manifest = json.loads((ROOT / 'nightly/manifest.json').read_text())
    nightly.validate_manifest(ROOT, manifest)
    revision = nightly.resolve(ROOT, 'HEAD')
    target = TARGETS[architecture]
    target_dir = ROOT / 'target/agent-nightly-macos'
    env = dict(os.environ, CARGO_TARGET_DIR=str(target_dir), CARGO_BUILD_JOBS='4',
               RUST_TEST_THREADS='4', RAYON_NUM_THREADS='4', MACOSX_DEPLOYMENT_TARGET='11.0',
               PHOTOCRAFT_BUILD_SHA=revision, PHOTOCRAFT_BUILD_DATE=datetime.now(nightly.ZONE).strftime('%Y-%m-%d'))
    args = ['cargo', 'build', '--release', '--locked', '--target', target, '-p', 'photocraft',
            '-p', 'photocraft-cli', '--features', 'photocraft/heif,photocraft-cli/heif']
    nightly.command(args, ROOT, env=env)
    destination.mkdir(parents=True, exist_ok=False)
    dependencies = {}
    for name in ('photocraft', 'photocraft-cli'):
        path = destination / name
        shutil.copy2(target_dir / target / 'release' / name, path)
        verify_architectures(path, [architecture])
        dependencies[name] = system_dependencies(run(['otool', '-L', path], capture=True))
    receipt = dict(integration=revision, architecture=architecture, target=target, command=args,
                   minimum_macos='11.0', toolchain=run(['rustc', '--version', '--verbose'], capture=True),
                   dependencies=dependencies, files={p.name: nightly.digest(p) for p in destination.iterdir()})
    (destination / 'SLICE-RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n')


def package(slices, windows_bundle, output):
    if sys.platform != 'darwin':
        raise ValueError('universal packaging requires macOS lipo, codesign and ditto')
    nightly.clean(ROOT)
    manifest = json.loads((ROOT / 'nightly/manifest.json').read_text())
    nightly.validate_manifest(ROOT, manifest)
    revision = nightly.resolve(ROOT, 'HEAD')
    windows = ci.verify_bundle(windows_bundle, revision)
    receipts = {}
    for architecture in TARGETS:
        folder = slices / architecture
        receipt = json.loads((folder / 'SLICE-RECEIPT.json').read_text())
        if receipt['integration'] != revision or receipt['architecture'] != architecture:
            raise ValueError('native slice revision or architecture mismatch')
        for name, expected in receipt['files'].items():
            if Path(name).name != name or nightly.digest(folder / name) != expected:
                raise ValueError('native slice checksum mismatch')
        receipts[architecture] = receipt
    stamp = datetime.now(nightly.ZONE).strftime('%Y%m%d-%H%M%S')
    bundle = output / f'photocraft-nightly-8bf-{stamp}-{revision[:12]}-macos-universal'
    bundle.mkdir(parents=True, exist_ok=False)
    app = bundle / 'PhotoCraft.app'
    resources = app / 'Contents/Resources'
    executable = app / 'Contents/MacOS/PhotoCraft'
    executable.parent.mkdir(parents=True)
    resources.mkdir()
    imports = {}
    for source, destination in (('photocraft', executable), ('photocraft-cli', bundle / 'photocraft-cli')):
        run(['lipo', '-create', slices / 'arm64' / source, slices / 'x86_64' / source, '-output', destination])
        destination.chmod(0o755)
        verify_architectures(destination, TARGETS)
        imports[destination.relative_to(bundle).as_posix()] = system_dependencies(run(['otool', '-L', destination], capture=True))
    # Reuse the established app identity/icon/document registrations, with the nightly revision.
    version = re.search(r'^version = "([^"]+)"', (ROOT / 'Cargo.toml').read_text(), re.MULTILINE).group(1)
    plist = (ROOT / 'packaging/macos/Info.plist.in').read_text().replace('@VERSION@', version).replace('@SHORT_VERSION@', version.split('-')[0].split('+')[0]).replace('@BUILD_SHA@', revision)
    (app / 'Contents/Info.plist').write_text(plist)
    plistlib.loads(plist.encode())
    (app / 'Contents/PkgInfo').write_bytes(b'APPL????')
    shutil.copy2(ROOT / 'assets/app-icon/photocraft.icns', resources / 'PhotoCraft.icns')
    (resources / '8bf').mkdir()
    for bits, machine in ((32, 0x14c), (64, 0x8664)):
        name = f'photocraft-8bf-worker{bits}.exe'
        nightly.verify_pe(windows_bundle / name, machine)
        for destination in (bundle / name, resources / '8bf' / name):
            shutil.copy2(windows_bundle / name, destination)
    # Read the exact hash-verified FreeCandy payload from the same-run Windows bundle.
    for item in manifest['freecandy']['files']:
        relative = Path(item['destination'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('plug-in destination escapes bundle')
        for parent in (bundle, resources):
            destination = parent / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(windows_bundle / relative, destination)
    for name in ('LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE', 'ATTRIBUTION.md', '8BF-COMPATIBILITY.md', 'SOURCE-MANIFEST.json'):
        shutil.copy2(windows_bundle / name, bundle / name)
    (bundle / 'README.txt').write_text('''PhotoCraft Nightly — Photoshop Plug-in Support

Your Photoshop plug-ins. Now in PhotoCraft.
Universal native Mac app and CLI: Apple Silicon + Intel, deployment target macOS 11.
PhotoCraft.app is ad-hoc signed, NOT Developer ID signed or notarized. macOS may
block a quarantined download; review it and use the supported Privacy & Security
Open Anyway override if you trust this experimental build. No system-wide security
setting changes are required or recommended.

Move PhotoCraft.app to Applications. Keep the CLI with its adjacent worker files.
Both x86/x64 Windows 8BF workers are also inside PhotoCraft.app/Contents/Resources/8bf.
Native .8bf filters require an external compatible Wine runtime; Apple Silicon may
also require Rosetta for an Intel Wine runtime. Wine is NOT bundled. Configure an
absolute PHOTOCRAFT_8BF_WINE path if Finder cannot discover your runtime.

FreeCandy is in plugins/freecandy7.wasm and in the app's Contents/Resources/plugins.
Add a plugins folder in Preferences > Plug-ins, or use Install Plug-in to enable it.
Experimental RGB/Gray 8-/16-bit raster filters only; UXP, .8bi and arbitrary vendor
compatibility are not certified. See 8BF-COMPATIBILITY.md and BUILD-RECEIPT.json.
''')
    # All app resources are in place before sealing the app. Never impersonate a Developer ID.
    sign = ['codesign', '--force', '--sign', '-', '--timestamp=none', '--options', 'runtime']
    run(sign + ['--entitlements', ROOT / 'packaging/macos/entitlements.plist', executable])
    run(sign + ['--entitlements', ROOT / 'packaging/macos/entitlements.plist', app])
    run(sign + ['--identifier', 'ai.storyteller.photocraft-cli', bundle / 'photocraft-cli'])
    for path in (app, bundle / 'photocraft-cli'):
        run(['codesign', '--verify', '--strict', '--deep', '--verbose=2', path])
    receipt = dict(title='PhotoCraft Nightly — Photoshop Plug-in Support', target='universal-apple-darwin',
                   integration=revision, embedded_build_sha=revision, manifest=manifest,
                   built_at=datetime.now(nightly.ZONE).isoformat(), timezone='America/Indiana/Indianapolis',
                   architectures=list(TARGETS), minimum_macos='11.0', signing='ad-hoc; not Developer ID signed; not notarized',
                   native_slices=receipts, windows_worker_source=dict(integration=windows['integration'], imports=windows['windows_imports']),
                   macos_dependencies=imports,
                   checks=['slice revision and hash checks', 'arm64 and x86_64 universal Mach-O', 'system-only dylib imports',
                           'x86/x64 PE workers in app Resources/8bf and beside CLI', 'pinned FreeCandy and licenses',
                           'strict ad-hoc codesign verification'],
                   files={p.relative_to(bundle).as_posix(): nightly.digest(p) for p in sorted(bundle.rglob('*')) if p.is_file()})
    (bundle / 'BUILD-RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n')
    ci.verify_bundle(bundle, revision)
    (bundle / 'SHA256SUMS').write_text(''.join(f'{nightly.digest(p)}  {p.relative_to(bundle).as_posix()}\n' for p in sorted(bundle.rglob('*')) if p.is_file()))
    archive = output / (bundle.name + '.zip')
    run(['ditto', '-c', '-k', '--keepParent', bundle, archive])
    archive.with_name(archive.name + '.sha256').write_text(f'{nightly.digest(archive)}  {archive.name}\n')
    print(f'Built {archive}\nSHA256 {nightly.digest(archive)}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('slice')
    build.add_argument('architecture', choices=TARGETS)
    build.add_argument('--output', type=Path, required=True)
    pack = sub.add_parser('package')
    pack.add_argument('--slices', type=Path, required=True)
    pack.add_argument('--windows-bundle', type=Path, required=True)
    pack.add_argument('--output', type=Path, default=Path('target/nightly'))
    args = parser.parse_args()
    if args.command == 'slice':
        build_slice(args.architecture, args.output.resolve())
    else:
        package(args.slices.resolve(), args.windows_bundle.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
