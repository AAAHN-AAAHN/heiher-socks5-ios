# Declared composition build and validation

The main engine baseline and upstream source pins remain immutable. Feature branches
own their additions, and `release/integrated` records exact module commits and file
owners in `docs/feature-membership.json`.

## Commands

`bash Build/build.sh --checks-only` runs declared Swift/native tests and, on an
Xcode 27 macOS runner, iPhoneOS 27 ARM64 type checking. It never archives an app.
`bash Build/build.sh` additionally builds the patched XCFramework and unsigned IPA
on macOS. On Linux it runs applicable native/Swift tests, not an iOS build.
Use a clean checkout and `.build/core`; clang-format 18 is required. Do not put the
whole Homebrew LLVM toolchain before Xcode just to select its formatter.

Runtime depends on main. Config persistence depends on runtime; it does not duplicate
the engine controller, model, YAML conversion or lifecycle patch. The integrated
composition contains the latest frozen UDP, statistics, background, runtime,
persistence and icon modules. Individual old feature audit entry points retain their
standalone-scope checks; the release runner reuses their actual native case functions
against the fully patched release instead of weakening those scope gates.

Artifacts retain commit/tree, source ZIP, source hashes, per-case logs, native patch
apply/reverse evidence and, for a macOS build, IPA/dSYM/package details. One compiled
IPA is not the same as all CI jobs passing. Source tests, macOS native execution,
SDK type checks, Simulator execution and actual SideStore/LiveContainer installation
must be reported separately. A known fixed-port/unknown-client UDP observation stays
a known limitation, not a passing required profile.

Installation: import the unsigned release IPA through the user's existing SideStore
or LiveContainer workflow. No new signing certificate, BGTask host pattern, host IPA
or forced LiveContainer Bundle ID setting is required by these modules. Actual
installer versions and host configurations must be recorded when tested, never guessed.
The release contains location/audio background modes; standalone runtime/persistence
do not keep the app alive in the background.
