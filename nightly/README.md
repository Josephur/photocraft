# PhotoCraft Nightly — Photoshop Plug-in Support

This fork builds **experimental Photoshop-compatible `.8bf` filter support** together with the
FreeCandy host's effect suites, parameter controls, presets, selection behavior, and previews.
The editor remains native Rust. Windows x64 and Linux x86_64 portable bundles each include both
32-bit and 64-bit Windows workers. Linux additionally needs an external Wine runtime with both
architectures supported. See [compatibility and installation](../docs/native-8bf.md).

Local build commands produce unsigned artifacts. The fork’s [nightly workflow](https://github.com/Josephur/photocraft/actions/workflows/fork-nightly.yml)
publishes [prereleases](https://github.com/Josephur/photocraft/releases) only after both platforms build and runtime checks pass.
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
| `nightly/latest` (fork default), `nightly/<build>` | Source plus fork tooling/README, built at an exact commit | Never |

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

## Published nightly CI

The fork default branch is `nightly/latest`, which contains the reviewed source and fork-only tooling.
The headline and download links therefore appear on the repository page. Feature PRs still use
the independent feature branches above. Advance `nightly/latest` by merging updated source/tooling;
never reset it over upstream `main`, force-push it, or use it as an upstream PR head.

`.github/workflows/fork-nightly.yml` runs on pushes to `nightly/latest`, manual dispatch, and daily at
**4:17 a.m. America/Indiana/Indianapolis** (GitHub may delay scheduled starts). It builds Linux
and Windows using Ubuntu 24.04, Rust 1.98.1, locked dependencies and pinned Actions revisions.
Each job has read-only repository permissions; only the final publication job can write releases.
The workflow is restricted to Josephur/photocraft and the `nightly/latest` branch.

Both archives must pass payload hashes, embedded revision, PE architecture/import checks and
FreeCandy render tests. Linux runs a packaged editor smoke test under Xvfb/software Vulkan.
A native Windows runner tests the **shipped GNU binaries**, both worker architectures against
original clean-room fixtures, native filtering and undo, editor launch and the plug-in menus.
Only then does CI publish a uniquely tagged prerelease with both archives and SHA-256 sidecars.
Actions retain the runtime screenshots/reports and original QA fixtures for 14 days; synthetic
fixtures are not included in product release archives. Releases retain their immutable versioned
assets. Scheduled builds use the checked-in source pins; they do not silently merge new upstream
or feature commits. Refresh those pins through the reviewed process above.

The fork’s inherited FreeBSD, Perf (nightly), and Windows ARM64 scheduled workflows are disabled
in repository Actions settings to avoid unrelated scheduled jobs on the new default branch.
Normal feature CI and upstream workflow files remain unchanged.


### Universal macOS nightlies

The fork workflow builds native slices in parallel on `macos-15` (Apple Silicon)
and `macos-15-intel`, then combines the editor and CLI with `lipo`. The release ZIP
contains a native universal `PhotoCraft.app`, universal CLI, both exact Windows
worker binaries from the same run, pinned FreeCandy WASM and licenses. The app has
its own workers in `Contents/Resources/8bf`; CLI workers remain beside the CLI.
FreeCandy is available in both the top-level `plugins` folder and app Resources.

The app and CLI are ad-hoc signed after packaging, with strict signature checks
and system-only dynamic library checks. They are **not Developer ID signed or
notarized**. macOS may block quarantined downloads; use the supported Privacy &
Security Open Anyway flow only after reviewing and trusting the build. The build
deployment target is macOS 11; CI runtime acceptance is on macOS 15.

Publication requires native app startup/control/menu checks and actual FreeCandy
RGB16 rendering on Intel and Apple Silicon. The Wine bridge checks use the exact
shipped workers and original clean-room test filters, including inversion and undo
through the shipped CLI. A byte-identical CLI copy in a temporary app-shaped folder
also exercises the shared Resources worker lookup, without changing the signed app.
The desktop control channel deliberately rejects native plug-in registration and
execution; GUI-triggered native filter execution is not certified by these checks. CI downloads checksum-pinned Gcenx Wine stable **11.0_1 on Apple Silicon** and
devel **11.18 on Intel**, with the normal Mac graphics driver, only for QA. Stable
11.0_1 failed to initialize on the hosted Intel runner; 11.18 passes the original
worker cases. Runtime versions and archive hashes are recorded in QA metadata.
CPU fixture checks do not certify GPU-using plug-ins; Wine is not shipped. Users need
an external compatible Wine runtime, and Intel Wine on Apple Silicon needs Rosetta.
This certifies the tested bridge cases, not arbitrary third-party plug-ins.

To reproduce on Macs, use `python3 nightly/macos.py slice arm64 --output <slice-dir>`
and `slice x86_64` on the matching hosts, then `package --slices <parent-with-both-arch-dirs>
--windows-bundle <verified-same-revision-Windows-bundle>`. The packager verifies
slice receipts before lipo/signing and writes a complete hashed build receipt.
