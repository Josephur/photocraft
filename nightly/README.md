# PhotoCraft Nightly — Photoshop Plug-in Support

This fork builds **experimental Photoshop-compatible `.8bf` filter support** together with the
FreeCandy host's effect suites, parameter controls, presets, selection behavior, and previews.
The editor remains native Rust. Windows x64 and Linux x86_64 portable bundles each include both
32-bit and 64-bit Windows workers. Linux additionally needs an external Wine runtime with both
architectures supported. See [compatibility and installation](../docs/native-8bf.md).

No release is published by these commands. The first builds are local unsigned artifacts.
The pinned FreeCandy WASM effect module is included with its 0BSD and third-party licenses in
`plugins/`; add that folder in Preferences > Plug-ins to enable it. Third-party native plug-ins
remain separate installations.

## Branch ownership

| Branch | Purpose | Upstream PR source? |
| --- | --- | --- |
| `feature/photoshop-8bf-compatibility` | 8BF host, workers, tests, required packaging and technical docs | Yes |
| `feature/plugin-effect-suites-updated` | Original plug-in suite branch refreshed onto upstream | Yes, or split into smaller feature PRs |
| `fork/nightly-tooling` | This directory and our fork's README headline | Never |
| `nightly/source` | Reviewed source merge, including any conflict resolutions | Never |
| `nightly/<build>` | Source plus fork tooling/README, built at an exact commit | Never |

**Features flow into the nightly. Never merge a nightly or tooling branch back into a feature
branch.** GitHub PRs compare the selected head with upstream; other branches in the same fork
are not part of that diff. Required 8BF worker builders remain legitimate feature files.

`manifest.json` pins upstream, each feature and the combined source merge by full SHA. The source
merge retains reviewed conflict resolutions, so builds do not guess how to resolve conflicts.
Assembly verifies every feature and upstream is included. Old backup/partial branches are
documented in the manifest instead of blindly merging every worktree or branch.

## Build from Linux

Prerequisites: Git, Python 3.10+ with IANA timezone data, Rust, the normal PhotoCraft Linux build
dependencies, and MinGW-w64 compilers/resource tools for both Windows architectures. Install
the Rust targets once:

```sh
rustup target add x86_64-unknown-linux-gnu x86_64-pc-windows-gnu i686-pc-windows-gnu
```

From the `fork/nightly-tooling` worktree, with committed changes:

```sh
python3 -m unittest discover -s nightly -v
python3 nightly/nightly.py verify
python3 nightly/nightly.py assemble ../photocraft-nightly-build --branch nightly/20261021
cd ../photocraft-nightly-build
python3 nightly/nightly.py build linux
python3 nightly/nightly.py build windows
```

The builder uses release mode, HEIF support and locked dependencies, requires embedded Windows
resources, checks the Windows editor's GUI subsystem, and fails if either worker is absent or
has the wrong architecture. It constrains its entire process tree to at most eight of the
available logical CPUs, sets Cargo/test/Rayon limits to eight, and lowers priority. Run the two
build commands sequentially. It refuses dirty source and existing worktree/output collisions.

Use `--target-dir /absolute/build-cache` to share the same task-owned cache between the two
commands. `--output /absolute/artifacts` selects the artifact directory. Optional
`--freecandy-repo /absolute/FreeCandy7` reads the committed artifact directly from an existing
checkout, without changing that checkout or reading its uncommitted content. Otherwise the
builder fetches the manifest's public FreeCandy repository at its pinned commit into the build
cache. The WASM and both license files must match their manifest SHA-256 hashes. Optional
`CRAFT_FONTS_DIR=/absolute/clean/craft-fonts` is recorded by revision; without it the app uses its
normal fonts/system-font behavior. No font files are committed here.

Each portable bundle contains the editor, CLI, both 8BF workers, compatibility instructions,
licenses, source manifest, file hashes, and `BUILD-RECEIPT.json` with the integration SHA, target,
toolchain and build commands. Bundle names and timestamps use America/Indiana/Indianapolis.
Linux `.tar.gz` bundles use the build host's system libraries; they are not universal AppImages.
The Windows `.zip` is unsigned. Build success does not establish vendor filter compatibility.

## Refresh upstream and features

1. Fetch `origin` (storytold/photocraft) and inspect its new `main` SHA.
2. In each clean feature worktree, merge `origin/main`; retain feature-required docs/tests.
   Resolve feature conflicts there and run the relevant repository checks. Preserve uncommitted
   work by creating a new branch/worktree instead of resetting an existing checkout.
3. In `nightly/source`, merge the refreshed feature heads. Resolve overlap by retaining both
   behaviors and test the combined source. This branch has no fork README or orchestration.
4. In `fork/nightly-tooling`, update `manifest.json` with full upstream, feature and source SHAs.
   Commit the manifest. If desired, merge upstream into tooling too and retain the fork headline.
5. Run `verify`, assemble into a fresh branch/worktree, then build and validate both platforms.

Feature fixes found during integration belong on the appropriate feature branch first; then
merge that fix forward into `nightly/source`. Conflict-only resolutions can stay in its merge
commit. New worktrees/features must be explicitly added to the manifest after review.

## Before any upstream PR

```sh
python3 nightly/nightly.py check-pr feature/photoshop-8bf-compatibility
python3 nightly/nightly.py check-pr feature/plugin-effect-suites-updated
git diff --stat origin/main...feature/photoshop-8bf-compatibility
git diff origin/main...feature/photoshop-8bf-compatibility
```

The guard rejects nightly paths, the known headline, and tooling ancestry while allowing
worker build/packaging scripts needed by 8BF. Inspect the whole diff as well: an automatic guard
cannot decide whether every other feature change belongs in a particular PR.

To make the headline appear at the fork's GitHub root later, publish a tested `nightly/<build>`
branch to **Josephur/photocraft** and select that branch as the fork's default. That changes only
which branch GitHub displays. Keep upstream PR heads on the named feature branches. Never push
the integration branch over upstream `main` or use it as an upstream PR head. Publication,
default-branch changes, signing and scheduling are separate explicit steps.
