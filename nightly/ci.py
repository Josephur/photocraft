#!/usr/bin/env python3
"""CI verification for exact nightly payloads, original fixtures and native runtime."""
import argparse
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import time

import nightly

ROOT = Path(__file__).resolve().parent.parent


def verify_bundle(bundle, revision):
    receipt = json.loads((bundle / "BUILD-RECEIPT.json").read_text())
    if receipt["integration"] != revision or receipt["embedded_build_sha"] != revision:
        raise ValueError("bundle does not match the workflow revision")
    suffix = ".exe" if receipt["target"] == "x86_64-pc-windows-gnu" else ""
    editor = "PhotoCraft.app/Contents/MacOS/PhotoCraft" if receipt["target"] == "universal-apple-darwin" else "photocraft" + suffix
    required = {editor, "photocraft-cli" + suffix, "photocraft-8bf-worker32.exe",
                "photocraft-8bf-worker64.exe", "plugins/freecandy7.wasm", "plugins/FreeCandy7-LICENSE",
                "plugins/FreeCandy7-LICENSE-THIRD-PARTY", "LICENSE-MIT", "LICENSE-APACHE", "NOTICE",
                "ATTRIBUTION.md", "8BF-COMPATIBILITY.md", "README.txt", "SOURCE-MANIFEST.json"}
    if receipt["target"] == "universal-apple-darwin":
        required |= {"PhotoCraft.app/Contents/Info.plist", "PhotoCraft.app/Contents/Resources/8bf/photocraft-8bf-worker32.exe",
                     "PhotoCraft.app/Contents/Resources/8bf/photocraft-8bf-worker64.exe",
                     "PhotoCraft.app/Contents/Resources/plugins/freecandy7.wasm"}
    if not required <= receipt["files"].keys():
        raise ValueError("bundle is missing required plug-in payloads")
    for name, expected in receipt["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("bundle receipt path escapes its directory")
        if nightly.digest(bundle / relative) != expected:
            raise ValueError(f"payload checksum mismatch: {name}")
    for item in receipt["manifest"]["freecandy"]["files"]:
        if receipt["files"].get(item["destination"]) != item["sha256"]:
            raise ValueError("FreeCandy payload does not match its pinned manifest")
    return receipt


def fixtures(destination):
    for arch in ("i686", "x86_64"):
        output = destination / arch
        output.mkdir(parents=True, exist_ok=True)
        for source, name in (("fixture", "conformance"), ("host_services", "host-services"), ("handle_services", "handle-services")):
            subprocess.run(["rustc", "--edition=2024", "--crate-type=cdylib", "--target", arch + "-pc-windows-gnu",
                            "-C", "linker=" + arch + "-w64-mingw32-gcc", "-O",
                            str(ROOT / "compat/8bf-worker/tests" / (source + ".rs")),
                            "-o", str(output / ("photocraft-" + name + ".8bf"))], check=True)



def editor_launch(bundle, output, port, token):
    """Keep relative document automation I/O under one allowed root."""
    suffix = ".exe" if os.name == "nt" else ""
    editor = bundle / "PhotoCraft.app/Contents/MacOS/PhotoCraft" if sys.platform == "darwin" else bundle / ("photocraft" + suffix)
    args = [str(editor), "--new-instance", "--safe-gpu", "--control", str(port),
            "--control-token-file", str(token), "--automation-read-root", str(output), "--automation-write-root", str(output)]
    return args


def resources_layout_cli(bundle, output):
    """Test shared Resources lookup with an exact CLI copy; never modify the signed app."""
    contents = output / "cli-layout/PhotoCraft.app/Contents"
    cli = contents / "MacOS/photocraft-cli"
    cli.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle / "photocraft-cli", cli)
    workers = contents / "Resources/8bf"
    workers.mkdir(parents=True, exist_ok=True)
    for bits in (32, 64):
        name = f"photocraft-8bf-worker{bits}.exe"
        shutil.copy2(bundle / "PhotoCraft.app/Contents/Resources/8bf" / name, workers / name)
    return str(cli)


def smoke(bundle, output, revision, fixture_dir=None):
    from PIL import Image
    verify_bundle(bundle, revision)
    output.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if os.name == "nt" else ""
    cli = str(bundle / ("photocraft-cli" + suffix))
    env = dict(os.environ, PHOTOCRAFT_CONFIG_DIR=str(output / "profile"), RAYON_NUM_THREADS="4",
               PHOTOCRAFT_NO_PRINT="1", LPDEST="photocraft-no-such-printer")
    version = subprocess.check_output([cli, "--version"], env=env, text=True).strip()
    if revision[:9] not in version:
        raise ValueError(f"incorrect embedded version: {version}")
    results = []

    def run(commands, path, depth=8, program=None):
        args = [program or cli, "run", "--new", json.dumps(dict(width=128, height=128, mode="rgb", depth=depth, background="white"))]
        for command, params in commands:
            args += ["--cmd", command, "--params", json.dumps(params)]
        result = subprocess.run(args + ["--out", str(path)], env=env, text=True, capture_output=True, timeout=120, check=True)
        return [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]

    wood = output / "freecandy-wood.png"
    run([("plugin.install", dict(path=str(bundle / "plugins/freecandy7.wasm"))),
         ("plugin.run", dict(id="com.stack-tech.freecandy7", params=dict(effect="wood")))], wood, 16)
    colors = len(set(Image.open(wood).convert("RGB").getdata()))
    if colors <= 32:
        raise ValueError("FreeCandy Wood did not produce varied image pixels")
    results.append(dict(case="FreeCandy Wood RGB16", distinct_colors=colors, passed=True))
    if fixture_dir:
        layout_cli = resources_layout_cli(bundle, output) if sys.platform == "darwin" else None
        for arch in ("i686", "x86_64"):
            fixture = fixture_dir / arch / "photocraft-conformance.8bf"
            install = ("plugin.8bf.install", dict(path=str(fixture)))
            installation = run([install], output / (arch + "-before.png"))
            plugin_id = installation[0]["result"]["id"]
            commands = [install, ("plugin.8bf.run", dict(id=plugin_id, show_ui=False))]
            env["PHOTOCRAFT_8BF_FIXTURE_MODE"] = "invert"
            for undo, expected in ((False, 0), (True, 255)):
                path = output / (arch + ("-undo.png" if undo else "-invert.png"))
                run(commands + ([("edit.undo", {})] if undo else []), path)
                if Image.open(path).convert("RGB").getextrema() != ((expected, expected),) * 3:
                    raise ValueError(f"{arch} native filter/undo returned incorrect pixels")
            results.append(dict(case=arch + " native filter and undo", passed=True))
            if layout_cli:
                for undo, expected in ((False, 0), (True, 255)):
                    path = output / (arch + ("-layout-undo.png" if undo else "-layout-invert.png"))
                    run(commands + ([("edit.undo", {})] if undo else []), path, program=layout_cli)
                    if Image.open(path).convert("RGB").getextrema() != ((expected, expected),) * 3:
                        raise ValueError(f"{arch} CLI in app Resources layout returned incorrect pixels")
                results.append(dict(case=arch + " exact CLI copy in app Resources layout filter and undo", passed=True))
    profile = output / "profile"
    profile.mkdir(exist_ok=True)
    (profile / "preferences.json").write_text(json.dumps({"plugIns": {"useAdditionalPluginsFolder": True,
        "additionalPluginsFolders": [str(bundle / "plugins")]}}))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = output / "control.token"
    args = editor_launch(bundle, output, port, token)
    connection = None
    with (output / "editor.log").open("w") as log:
        process = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError("editor exited before control connection; see editor.log")
                try:
                    connection = socket.create_connection(("127.0.0.1", port), timeout=1)
                    break
                except OSError:
                    time.sleep(0.5)
            if connection is None:
                raise RuntimeError("editor control connection timed out")
            connection.settimeout(60)
            stream = connection.makefile("rwb")
            def rpc(method, params=None):
                stream.write((json.dumps(dict(id=method, method=method, params=params or {})) + "\n").encode())
                stream.flush()
                reply = json.loads(stream.readline())
                if not reply.get("ok"):
                    raise RuntimeError(str(reply))
                return reply.get("result")
            for _ in range(50):
                if token.is_file():
                    break
                time.sleep(0.1)
            rpc("auth", dict(token=token.read_text().strip()))
            rpc("app.open", dict(path=wood.name))
            menus = rpc("ui.menu.list")
            (output / "menus.json").write_text(json.dumps(menus, indent=2))
            if "FreeCandy7" not in json.dumps(menus) or "8BF" not in json.dumps(menus):
                raise ValueError("expected plug-in menus are missing")
            rpc("ui.screenshot", dict(path="editor.png", focus=False))
            rpc("app.quit")
            process.wait(timeout=30)
            results.append(dict(case="Native editor launch, plug-in menus and screenshot", passed=True))
        finally:
            if connection:
                connection.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)
            token.unlink(missing_ok=True)
    (output / "runtime.json").write_text(json.dumps(dict(integration=revision, version=version, results=results), indent=2) + "\n")
    print(json.dumps(results, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fixture = sub.add_parser("fixtures")
    fixture.add_argument("destination", type=Path)
    for name in ("verify", "smoke"):
        command = sub.add_parser(name)
        command.add_argument("bundle", type=Path)
        command.add_argument("--revision", required=True)
        if name == "smoke":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--fixtures", type=Path)
    args = parser.parse_args()
    if args.command == "fixtures":
        fixtures(args.destination.resolve())
    elif args.command == "verify":
        verify_bundle(args.bundle.resolve(), args.revision)
    else:
        smoke(args.bundle.resolve(), args.output.resolve(), args.revision, args.fixtures.resolve() if args.fixtures else None)


if __name__ == "__main__":
    main()
