#!/usr/bin/env python3
"""Fork-only, pinned PhotoCraft nightly assembly and portable release packaging.

Python 3.10+ standard library; the editor and workers are built from Rust.
No branch is reset, rebased, pushed, or merged back into a feature branch.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Indiana/Indianapolis")
FORK_PATHS = ("nightly/", ".github/workflows/fork-nightly.yml")
TARGETS = {"linux": "x86_64-unknown-linux-gnu", "windows": "x86_64-pc-windows-gnu"}
WINDOWS_SYSTEM_DLLS = set("""
advapi32.dll avrt.dll bcrypt.dll cfgmgr32.dll comctl32.dll comdlg32.dll crypt32.dll
d2d1.dll d3d11.dll d3d12.dll d3dcompiler_47.dll dcomp.dll dnsapi.dll dwmapi.dll
dwrite.dll dxgi.dll gdi32.dll hid.dll imm32.dll iphlpapi.dll kernel32.dll kernelbase.dll
msimg32.dll msvcrt.dll ncrypt.dll netapi32.dll normaliz.dll ntdll.dll ole32.dll
oleacc.dll oleaut32.dll opengl32.dll powrprof.dll propsys.dll psapi.dll rpcrt4.dll
secur32.dll setupapi.dll shell32.dll shlwapi.dll ucrtbase.dll user32.dll userenv.dll
usp10.dll uxtheme.dll version.dll windows.data.pdf.dll windowscodecs.dll winhttp.dll
wininet.dll winmm.dll winspool.drv wintrust.dll ws2_32.dll wtsapi32.dll
""".split())


def command(args, cwd, env=None, capture=False):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, check=True,
                            text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def git(root, *args):
    return command(["git", *args], root, capture=True)


def resolve(root, revision):
    return git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")


def ancestor(root, older, newer):
    return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=root,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def clean(root):
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError(f"{root} has uncommitted or untracked files; preserve/commit them before building")


def validate_manifest(root, manifest):
    if manifest.get("version") != 1 or not manifest.get("features"):
        raise ValueError("manifest requires version 1 and at least one pinned feature")
    pins = [manifest["upstream"], manifest["source"]] + [f["commit"] for f in manifest["features"]]
    for pin in pins:
        if len(pin) != 40 or resolve(root, pin) != pin:
            raise ValueError(f"manifest revisions must be immutable full commit SHAs: {pin}")
    for pin in [manifest["upstream"]] + [f["commit"] for f in manifest["features"]]:
        if not ancestor(root, pin, manifest["source"]):
            raise ValueError(f"source {manifest['source']} does not contain required revision {pin}")
    for feature in manifest["features"]:
        if not ancestor(root, manifest["upstream"], feature["commit"]):
            raise ValueError(f"refresh {feature['name']} onto the pinned upstream before integration")


def check_pr(root, base, feature, tooling="fork/nightly-tooling"):
    """Guard fork-only content, while allowing feature-required worker builders/docs."""
    base, feature, tooling = (resolve(root, ref) for ref in (base, feature, tooling))
    if ancestor(root, tooling, feature):
        raise ValueError("PR branch contains the fork-only tooling commit; use the feature branch")
    paths = git(root, "diff", "--name-only", f"{base}...{feature}").splitlines()
    denied = [p for p in paths if p.startswith(FORK_PATHS)]
    if "README.md" in paths:
        diff = git(root, "diff", f"{base}...{feature}", "--", "README.md")
        if any(s in diff for s in ("Your Photoshop plug-ins. Now in PhotoCraft.", "plug-in-enabled nightly", "nightly/nightly.py")):
            denied.append("README.md (nightly branding)")
    if denied:
        raise ValueError("PR includes fork-only paths: " + ", ".join(denied))
    print(f"PR separation passed: {feature[:12]} ({len(paths)} changed files)", flush=True)


def assemble(root, manifest, destination, branch):
    clean(root)
    validate_manifest(root, manifest)
    destination = destination.resolve()
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    tooling = resolve(root, "HEAD")
    for feature in manifest["features"]:
        check_pr(root, manifest["upstream"], feature["commit"], tooling)
    # The source merge records reviewed conflict resolutions; do not invent resolutions in a build.
    command(["git", "worktree", "add", "-b", branch, destination, manifest["source"]], root)
    command(["git", "merge", "--no-edit", "--no-ff", tooling], destination)
    print(f"Assembled {resolve(destination, 'HEAD')} in {destination}", flush=True)


def verify_pe(path, machine, gui=False):
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError(f"invalid Windows executable: {path}")
    offset = struct.unpack_from("<I", data, 60)[0]
    if offset + 94 > len(data) or data[offset:offset + 4] != b"PE\0\0":
        raise ValueError(f"invalid PE header: {path}")
    if struct.unpack_from("<H", data, offset + 4)[0] != machine:
        raise ValueError(f"wrong PE architecture: {path}")
    if gui and struct.unpack_from("<H", data, offset + 92)[0] != 2:
        raise ValueError(f"editor must use Windows GUI subsystem (release build): {path}")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def pe_imports(path):
    output = command(["x86_64-w64-mingw32-objdump", "-p", path], path.parent, capture=True)
    imports = sorted(set(re.findall(r"DLL Name:\s*(\S+)", output)))
    if not imports:
        raise ValueError(f"could not inspect executable imports: {path}")
    unknown = [name for name in imports if name.lower() not in WINDOWS_SYSTEM_DLLS
               and not name.lower().startswith(("api-ms-win-", "ext-ms-win-"))]
    if unknown:
        raise ValueError(f"unbundled non-system Windows dependencies in {path.name}: {', '.join(unknown)}; statically link or explicitly package and license them")
    return imports


def plugin_payload(manifest, repository):
    """Read committed, hash-pinned distributables without touching a developer's checkout."""
    plugin = manifest["freecandy"]
    commit = resolve(repository, plugin["commit"])
    if commit != plugin["commit"] or len(commit) != 40:
        raise ValueError("FreeCandy revision must be an immutable full commit SHA")
    payload = []
    for item in plugin["files"]:
        destination = Path(item["destination"])
        if destination.is_absolute() or ".." in destination.parts:
            raise ValueError("FreeCandy payload destination must stay inside the bundle")
        data = subprocess.check_output(["git", "show", f"{commit}:{item['source']}"], cwd=repository)
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"FreeCandy payload checksum mismatch: {item['source']}")
        payload.append((destination, data))
    return payload


def build(root, manifest, platform, output, target_dir, freecandy_repo=None):
    clean(root)
    validate_manifest(root, manifest)
    head = resolve(root, "HEAD")
    if not ancestor(root, manifest["source"], head):
        raise ValueError("build from an assembled nightly worktree containing the pinned source")
    if sys.platform != "linux":
        raise ValueError("this builder uses the documented Linux + MinGW toolchain for both targets")
    # Affinity constrains compiler/linker internal thread pools as well as Cargo.
    cpus = sorted(os.sched_getaffinity(0))[:8]
    os.sched_setaffinity(0, cpus)
    os.nice(10)
    target_dir = target_dir.resolve()
    if freecandy_repo is None:
        freecandy_repo = target_dir / "nightly-inputs/freecandy7"
        if not freecandy_repo.exists():
            freecandy_repo.mkdir(parents=True)
            command(["git", "init"], freecandy_repo)
        command(["git", "fetch", "--depth=1", manifest["freecandy"]["repository"], manifest["freecandy"]["commit"]], freecandy_repo)
    payload = plugin_payload(manifest, freecandy_repo.resolve())
    env = dict(os.environ, CARGO_BUILD_JOBS="8", RUST_TEST_THREADS="8", RAYON_NUM_THREADS="8",
               CARGO_TARGET_DIR=str(target_dir), PHOTOCRAFT_REQUIRE_WINRES="1")
    # Optional fonts are recorded, never copied into source or silently assumed present.
    fonts = None
    if env.get("CRAFT_FONTS_DIR"):
        font_dir = Path(env["CRAFT_FONTS_DIR"]).resolve()
        clean(font_dir)
        fonts = dict(commit=resolve(font_dir, "HEAD"))
        env["CRAFT_FONTS_DIR"] = str(font_dir)
    target = TARGETS[platform]
    stamp = datetime.now(ZONE).strftime("%Y%m%d-%H%M%S")
    name = f"photocraft-nightly-8bf-{stamp}-{head[:12]}-{platform}-x86_64"
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / name
    if bundle.exists():
        raise ValueError(f"bundle already exists: {bundle}")
    # Do not create the bundle before all builds pass.
    commands = []
    def run(args):
        commands.append([str(x) for x in args])
        command(args, root, env)
    run(["cargo", "build", "--locked", "--release", "--target", target,
         "-p", "photocraft", "-p", "photocraft-cli", "--features", "photocraft/heif,photocraft-cli/heif"])
    workers = []
    imports = {}
    for architecture, bits in (("i686", 32), ("x86_64", 64)):
        worker_target = f"{architecture}-pc-windows-gnu"
        run(["cargo", "build", "--locked", "--release", "--manifest-path", "compat/8bf-worker/Cargo.toml",
             "--target-dir", target_dir / "8bf-workers", "--target", worker_target])
        worker = target_dir / "8bf-workers" / worker_target / "release/photocraft-8bf-worker.exe"
        verify_pe(worker, 0x14C if bits == 32 else 0x8664)
        imports[f"photocraft-8bf-worker{bits}.exe"] = pe_imports(worker)
        workers.append((worker, f"photocraft-8bf-worker{bits}.exe"))
    binary_dir = target_dir / target / "release"
    suffix = ".exe" if platform == "windows" else ""
    if platform == "windows":
        verify_pe(binary_dir / "photocraft.exe", 0x8664, gui=True)
        verify_pe(binary_dir / "photocraft-cli.exe", 0x8664)
        for binary in ("photocraft.exe", "photocraft-cli.exe"):
            imports[binary] = pe_imports(binary_dir / binary)
    bundle.mkdir()
    for binary in ("photocraft", "photocraft-cli"):
        shutil.copy2(binary_dir / (binary + suffix), bundle / (binary + suffix))
    for worker, name in workers:
        shutil.copy2(worker, bundle / name)
    for relative, data in payload:
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE", "ATTRIBUTION.md"):
        shutil.copy2(root / name, bundle / name)
    with (bundle / "ATTRIBUTION.md").open("a", encoding="utf-8") as attribution:
        attribution.write(
            "\n## Nightly plug-in payload\n\n"
            "| Path | Title | Author | Source | License |\n| --- | --- | --- | --- | --- |\n"
            f"| plugins/freecandy7.wasm | FreeCandy7 | FreeCandy7 contributors | {manifest['freecandy']['repository']} "
            f"at {manifest['freecandy']['commit']} | 0BSD; see plugins/FreeCandy7-LICENSE and plugins/FreeCandy7-LICENSE-THIRD-PARTY |\n")
    shutil.copy2(root / "docs/native-8bf.md", bundle / "8BF-COMPATIBILITY.md")
    shutil.copy2(root / "nightly/manifest.json", bundle / "SOURCE-MANIFEST.json")
    (bundle / "README.txt").write_text(
        "PhotoCraft Nightly — Photoshop Plug-in Support\n\n"
        "Your Photoshop plug-ins. Now in PhotoCraft.\n"
        "Experimental Windows x86/x64 .8bf filters on RGB/Gray 8-/16-bit raster layers.\n"
        "Keep both worker executables next to the editor. Linux requires external Wine\n"
        "with support for both architectures. No proprietary 8BF plug-ins or Wine are bundled.\n"
        "Use Preferences > Plug-ins to add folders, or Filter > Plug-ins > Install 8BF Plug-in.\n"
        "FreeCandy is included in plugins/freecandy7.wasm. Add this bundle's plugins folder in\n"
        "Preferences > Plug-ins, or choose Filter > Plug-ins > Install Plug-in to load it.\n"
        "See 8BF-COMPATIBILITY.md for limits. UXP, .8bi and universal compatibility are not provided.\n"
        "This is an unsigned experimental fork build. See BUILD-RECEIPT.json for exact sources.\n",
        encoding="utf-8")
    receipt = dict(title="PhotoCraft Nightly — Photoshop Plug-in Support", built_at=datetime.now(ZONE).isoformat(),
                   timezone="America/Indiana/Indianapolis", integration=head, manifest=manifest, target=target,
                   rustc=command(["rustc", "--version", "--verbose"], root, capture=True), profile="release",
                   commands=commands, cpus=cpus, fonts=fonts,
                   windows_imports=imports,
                   checks=["pinned source ancestry", "clean source worktree", "worker x86/x64 PE architecture", "Windows imports: system DLLs only"] +
                          (["Windows editor GUI subsystem"] if platform == "windows" else []),
                   runtime_validation="See validation report; build success alone does not certify vendor plug-ins.",
                   files={p.relative_to(bundle).as_posix(): digest(p) for p in sorted(bundle.rglob("*")) if p.is_file()})
    (bundle / "BUILD-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (bundle / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.relative_to(bundle).as_posix()}\n" for p in sorted(bundle.rglob("*")) if p.is_file()))
    if platform == "windows":
        archive = output / (bundle.name + ".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    stream.write(path, f"{bundle.name}/{path.relative_to(bundle).as_posix()}")
    else:
        archive = output / (bundle.name + ".tar.gz")
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(bundle, arcname=bundle.name)
    archive.with_name(archive.name + ".sha256").write_text(f"{digest(archive)}  {archive.name}\n")
    print(f"Built {archive}\nSHA256 {digest(archive)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify", help="verify immutable manifest pins and PR separation")
    assemble_parser = commands.add_parser("assemble", help="create a fresh integration branch/worktree")
    assemble_parser.add_argument("destination", type=Path)
    assemble_parser.add_argument("--branch", required=True)
    build_parser = commands.add_parser("build", help="build and package one target from the integration worktree")
    build_parser.add_argument("platform", choices=TARGETS)
    build_parser.add_argument("--output", type=Path, default=Path("target/nightly"))
    build_parser.add_argument("--target-dir", type=Path, default=Path("target/agent-nightly"))
    build_parser.add_argument("--freecandy-repo", type=Path, help="read the pinned artifact from an existing repository instead of fetching")
    guard_parser = commands.add_parser("check-pr", help="reject fork-only paths/branding in a feature diff")
    guard_parser.add_argument("feature")
    guard_parser.add_argument("--base", default="origin/main")
    guard_parser.add_argument("--tooling", default="fork/nightly-tooling")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    manifest = json.loads((root / "nightly/manifest.json").read_text())
    if args.command == "assemble":
        assemble(root, manifest, args.destination, args.branch)
    elif args.command == "build":
        build(root, manifest, args.platform, args.output, args.target_dir, args.freecandy_repo)
    elif args.command == "check-pr":
        check_pr(root, args.base, args.feature, args.tooling)
    else:
        validate_manifest(root, manifest)
        for feature in manifest["features"]:
            check_pr(root, manifest["upstream"], feature["commit"])
        print("Manifest pins and feature separation verified.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(f"nightly: {error}")
