# Shared latest-upstream combination

## Definition

Main combines the latest verified `heiher/socks5-ios` app source with a fresh,
**unpatched** build of the latest verified `heiher/hev-socks5-server` main branch.
It is not a byte-identical mirror of the iOS repository, not its old prebuilt core,
and not the historical fork snapshot. Latest means the upstream main tips verified
for this update, not a floating dependency fetched differently on every build.

- iOS source: `180012e8b9dbaa2002a68ebd2c75bccebcfb789c`
- Server source: `b3585289622561caf4b8789b436cc8820ecd6be0`
- Verified date: 2026-09-22
- Submodules: the exact revisions referenced by that server, in `Build/upstream.json`.

Main's `Socks5/`, `Socks5.xcodeproj/` and LICENSE are byte-for-byte upstream.
The bundled XCFramework is rebuilt from clean server sources using upstream's
`build-apple.sh`. Its complete tracked file inventory, SHA-256 hashes and build
provenance are in `Build/baseline-framework.json`. The root README and build/audit
infrastructure describe this combination; the upstream README is preserved at
`docs/upstream/README.md`. There are no UDP, statistics, lifecycle or app-feature
patches on main. Consequently known unpatched upstream limitations are not hidden.
Use `release/integrated` for the feature-complete app.

## Inheritance

Every existing feature branch incorporates the new main as an ancestor, preserves
its own runtime feature code, and carries the identical baseline XCFramework,
`Build/upstream.json`, provenance inventory and shared build/check scripts. Its
`Build/features.json` identifies the actual main commit in `base_commit` and lists
only its feature patches. Traffic statistics additionally depends on UDP
compatibility; integration includes every feature tip. Old branch history is
preserved by merge ancestry and archive tags, not discarded by a forced rebase.

During feature builds the clean base engine is checked out at the shared pinned
revision, declared patches are applied, and a patched framework replaces the base
framework in the disposable build workspace. The committed baseline framework is
never represented as having those patches. Run `bash Build/build.sh` before building
feature code with Xcode; statistics needs its rebuilt public C API.

`Build/check.py` checks pin equality, the committed baseline framework inventory,
feature-to-main ancestry and shared file identity. Checks read baseline bytes from
Git, so a locally rebuilt feature framework is not mistaken for the committed one.
Future branches should start from current main and keep these shared files intact.
Updating the baseline is explicit: resolve upstream tips, rebuild the unpatched
framework, update the shared lock, merge main into descendants and revalidate.
There is no unattended update that could silently change a known working build.

## Verification and scope

The baseline and five focused branches are checked on Linux and macOS; the
integrated app is checked after those jobs succeed. macOS produces real ARM64 iOS
archives. Unpatched baseline tests include actual TCP relay and source identity;
its known Darwin UDP limitations are not mislabeled as fixed. Features run their
applicable UDP, statistics, background, settings and lifecycle regression tests.
No application Swift source or existing C patch changes in this baseline update.
Host tests and archives are not new iPhone call, VPN, battery or throughput tests.

Prior branch tips are saved under `archive/before-latest-baseline-20260922/`.
Publication verifies expected old SHAs and advances all seven branches atomically
only after successful checks. Candidate tags and the maintenance branch are then
removed; the maintenance commit is archived for reproducibility. A failed check
leaves the prior active branches untouched. Artifact logs record tested commit IDs.
