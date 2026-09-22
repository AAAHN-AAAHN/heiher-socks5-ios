# Build, validation, and release infrastructure

## Source identity and branch ownership

Main combines latest verified iOS source and a freshly built unpatched engine.
See [the shared baseline specification](main-baseline.md). Feature branches inherit
identical pins and framework objects from main. They rebuild from pinned
server `b3585289622561caf4b8789b436cc8820ecd6be0`, core
`162dd996299fc2d2bff2dd63728f8a2cd71ed31a`, task system
`328f35d903221b51811b3d02b277d665dfbdc75f`, and YAML
`162227cd7d2b6108bc8bc133273e11413222ddf4`.

Every feature branch is buildable as a checkout, not a patch-only placeholder.
Traffic statistics explicitly depends on UDP compatibility; the other four are
not a cumulative ladder. The final release has all five feature tips in its Git
ancestry, contains the same feature module files and specification documents, and
has a small explicit root view composing them. Branch-specific root READMEs are
also copied byte-for-byte into `docs/branches` in the release. A file/hash membership
manifest verifies module identity and documents the intentional composition glue.

`Build/features.json` selects actual patches, tests and app modules. Build code
must not infer the composition from a branch-name substring. This makes a detached
checkout unambiguous. `Build/build.sh` fails on an unexpected source revision, patch
mismatch, style mismatch, test failure or incorrect app packaging. It never updates
upstream branches. The committed framework is the fresh unpatched main baseline. Feature builds
replace it only in the disposable build workspace; it is not a prepatched library.
Source ZIPs preserve the composition but use a git checkout to run the full build,
which records the actual commit and produces a git source archive.

## Commands

On macOS with Xcode, Python 3, git, and clang-format-18 (or clang-format 18 on PATH):

```sh
bash Build/build.sh
```

The script checks out the pinned recursive core into `.build/core` when absent,
applies only the manifest's patches, runs native tests, builds the Apple framework,
and creates an unsigned iPhone Release archive and IPA. The core checkout must be
clean; use a fresh worktree or remove `.build` before changing compositions. The
workflow uses a clean runner and installs the pinned formatter. Tests and docs are
not compiled into the IPA. Dependencies needed by upstream are built by its own
Makefiles; no network library or package manager is added to the app.

On Linux the same script performs applicable native tests, C style checks and Swift
model/controller/storage tests, then stops without pretending to build iOS. The
statistics feature is tested in both buffered and Linux splice configurations.
macOS exercises Darwin UDP behavior using actual socket endpoints. Every feature
also receives its own ARM64 iPhone archive; the final release is not the only build.

## Test scope

- UDP: real Hev, TCP/UDP echo, addresses, payloads, known/unknown ports, multiple peers.
- Statistics: exact payload totals, asymmetric traffic, idle, concurrency, restarts;
  independent Swift delta and unit formatting checks.
- Background: production controller with scripted platform doubles, late callbacks,
  fixed retry cadence and explicit Off; real Apple WAV decoder on macOS.
- Settings: actual temporary JSON files, imports, UTF-8 limits, newlines, stored intent,
  controller doubles and a separate real multi-worker stop-before-start C probe.
- Icon: source image structure/opacity and archived app icon metadata.
- Integration: feature file identity, patch inventory, tab order, bindings, unique
  Xcode objects, API compile checks, scene/background permissions, unchanged silence.

Mocks are explicitly not iPhone call/suspension tests. Native host networking is
not hotspot/VPN/Sunshine emulation. No CPU, battery, or absolute optimality claim is
inferred from passing functional tests. The minimal UDP peer-selection behavior and
other known upstream limits remain documented rather than silently redesigned.

## Style and minimality audit

The C changes are checked against their own pinned upstream `.clang-format` using
formatter version 18. Swift follows the existing four-space, native-framework style;
new feature boundaries use ordinary bindings, value models and MainActor controllers.
No wholesale reformatting of unchanged upstream files is done merely to change
appearance. Standard frontend/actual Xcode compilation checks remain required.
Python build/test files use standard-library code, explicit exit checks, subprocess
deadlines for potential hangs, and bounded input reads. No test or helper process
is included in the app's runtime target.

## History, artifacts, and failure policy

Before old branch names are deleted their exact tips are preserved as
`archive/2026-09-22/<old-branch>` tags. A history bundle and old-ref manifest are also
provided. No commits are garbage-collected or force-deleted. Main restoration and
old-branch cleanup occur only after all feature and integrated checks succeed;
updates use expected old SHAs so concurrent changes are not overwritten.

CI produces per-composition logs, core version identities, patch hashes, source ZIP,
unsigned IPA, SHA256SUMS, and debug symbols. A successful CI badge means those named
checks passed, not that all operating-system states or every network input are
proved correct. Build failures preserve logs and do not get reclassified as a lack
of GitHub permissions. The normal build workflow has read-only repository permissions.
Only the explicitly authorized one-time reorganization workflow writes branches.
