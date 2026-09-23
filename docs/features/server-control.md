# Server execution control

This branch is `feature/server-control`, based on the unchanged shared `main`.
It owns the validated server options and the actual Start/Stop/reconfiguration
policy. It does **not** own persistent settings, JSON files, file pickers, tabs for
other features, background keep-alive or traffic counters.

## Responsibility and dependency

`main -> feature/server-control -> feature/settings-persistence` is the declared
stack. The server layer does not import or refer to AppSettings or SettingsStore.
The persistence layer reuses this exact server layer instead of copying the engine
controller. This dependency is a build/composition relationship, not an additional
runtime service, process or dynamically loaded module.

`ServerSettings.swift` defines the existing eleven options, their defaults, input
validation and the YAML accepted by Hev. Codable makes the value portable but does
not read or write files. ServerConfigurationError describes invalid executable
options. It is independent of JSON schema and storage errors.

`ServerController.apply(_:running:retry:)` accepts only server options, desired
running state and explicit retry intent. The validated blocking Hev call runs on
a utility queue; UI state is MainActor-owned. Current/desired configurations ensure
that the old call finishes before a replacement starts. Attempted-configuration
tracking prevents unrelated UI changes from repeatedly restarting a failed engine.
An explicit Start, a new configuration or a completed Stop/Start may retry. This is
not the infinite audio recovery policy. Running means invocation status, not a
promise that an address was successfully bound.

The existing `hev-server-startup-stop.patch` belongs here, together with its native
regression. Its SYNC_ABRT correction prevents worker finalization from waiting
forever when Stop predates multi-worker startup. The patch is unchanged.

The standalone AppRoot holds options and desired Start/Stop in memory only. Launch
starts stopped with the existing defaults. The shared ContentView receives bindings
and Start/Stop callbacks and knows nothing about persistence. No option is silently
saved in this branch; persistence is supplied only by the downstream feature.

## Preserved contracts

Workers 1-64, TCP port 1-65535 and UDP port 0-65535; 255 UTF-8 bytes maximum for
executable text; paired authentication fields; rejection of control/newline input;
single-quote escaping; draft options editable while stopped. Defaults, native
source pins and the existing validation messages are preserved. In particular, UDP defaults remain 1080; this split does not change
that setting or claim the separate UDP compatibility feature is included here.

Extraction source: old `feature/settings` checkpoint
`16689f780f3e0e0c9344397273528697f197c9e5`. The model body is moved unchanged except
for the validation-error type name. The controller changes only its input signature
and the extraction of desired state; its execution algorithm is preserved.

## Versions and installation environment

Target use: physical iOS 27.0, installed through SideStore or run as a LiveContainer
guest. These environments are distinct. Minimum deployment remains iOS 17.2 and
Bundle ID remains `hev.Socks5`. No host patch, signing identity change, BGTask or
NetworkExtension is introduced. SDK compilation and Simulator evidence do not
establish actual SideStore provisioning or LiveContainer loading/host arbitration.

Full-repository checkout is required by provenance/parity checks, which read the
original audited settings commit. Build: `BUILD_IPA=0 bash Build/build.sh` for native
and model checks; `bash Build/check_swift_sdk.sh` uses the iPhoneOS 27 SDK. The
production build script can package this standalone composition, but the requested
new delivery is the integrated release IPA, not a replacement standalone app.

## Validation and costs

Local Linux checks passed the retained seven server state scenarios and 512 exact
old/new validation/YAML comparisons. Mock engine tests cover scheduling, while the
real native stop-before-start and TCP checks cover the pinned engine. The completed
checks below are separate from the integrated release build. No physical device or
installer test has been run.

No new timer, queue, socket layer or polling mechanism is added by separating the
branch. Configuration and lifecycle remain the same native calls. Energy and
throughput changes are not asserted without measurements.

README maintenance: distinguish minimum, target and actually-tested OS/build;
record tested commit/run, toolchain, success/failure/not-run scopes and limitations.
Keep this README byte-identical to `docs/features/server-control.md`. Historical
code remains reachable through the downstream persistence merge; no main history
is rewritten. Ownership and exact dependency files are machine-checked.

## Completed extraction verification (2026-09-23)

Tested commit: `295e0f70082de1d8356aca4551eb7a396d557bdd`.
Tested tree: `073b27583ef9f3152987168055907aa0dbdbc045`.
Actions run `35842578898`: both Linux and Xcode-27 jobs succeeded on their first run.
Each passed the seven server scenarios, 512 configuration parity cases, real TCP,
real parser fixtures and 40 native Stop-before-Start cycles (20 each for one/four
workers). Repetitions are not independent device tests. Xcode 27.0 `27A266a` and
iPhoneOS SDK 27.0 typechecked all five production Swift files with warnings-as-errors;
the diagnostic log is empty. No standalone app archive or IPA was built.

Downloaded macOS artifact `10741802078` SHA-256:
`ccf052572e8a5a25fdc363420958730e9a5a7679370aec4cf8c9e4214b908ed0`.
Downloaded Linux artifact `10741348256` SHA-256:
`43d8b7d0065d6a47790a0bee9d1208e2c0851d790fc4b888747e535072cedca2`.
Both digests and all 57 source hashes were verified. This result section is a later
documentation-only change; production/tests remain the exact successful source.
