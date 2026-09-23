# Server execution control

This branch is `feature/server-control`, based on the unchanged shared `main`.
It owns the validated server options and the actual Start/Stop/reconfiguration
policy. It does **not** own persistent settings, JSON files, file pickers, tabs for
other features, background keep-alive or traffic counters.

## Responsibility and dependency

`main -> feature/server-control -> feature/settings-persistence` is the declared
stack. The server layer does not import or refer to AppSettings or SettingsStore.
The persistence layer reuses its pinned server version instead of copying the engine
controller; this audit does not automatically move that dependency pin. This dependency is a build/composition relationship, not an additional
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
forever when Stop predates multi-worker startup. That correction is preserved.
The final revalidation below also guards the worker I/O yield against sleeping
after a pending Stop has already delivered its wakeup.

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
production build script can package this standalone composition when explicitly
requested. This revalidation does not produce an IPA or update the integrated release.

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

## Final server-control revalidation (2026-09-24)

Input: `68599f96331f3f45e3fa271db02e6ede0fc35d73`. Scope is this server
feature and its main-relative integration, not persistence, Background, UDP or the
integrated release. Other branch heads and their pinned dependency versions are not
updated by this revalidation. No new branch, app archive or IPA is requested.

### Byte-sensitive option equality

The former synthesized Equatable used Swift String's canonical equivalence. For
example, `U+00E9` and `U+0065 U+0301` compare equal as String but encode to different
UTF-8 bytes. Hev receives the actual YAML/credential bytes. The old model could
therefore suppress a credential change in onChange/current/desired comparisons,
leaving the previous credentials active even though the requested bytes changed.
This was reproduced in the actual old model and controller, not inferred solely
from a documentation warning.

ServerSettings now compares all ten text fields through their UTF-8 views and the
Boolean flag normally. No normalization, hashing, second stored representation or
JSON encoding is performed for equality. Exact copies still compare equal. A valid
changed value follows the existing serialized Stop/Start path; the controller,
validator, YAML generation, error messages, defaults and Codable schema are unchanged.
Raw drafts also remain distinct, including canonically equivalent invalid drafts.
The override is separate from the unchanged validation/YAML body.

Product changes are confined to ServerSettings equality and the existing lifecycle
patch, preserving its original startup fix. The shared editor/root, engine/framework
pins, Info.plist, signing settings, deployment
target, server API and state machine remain the audited input. There is no new
queue, timer, socket, background task, persistent data, host ID or permission. Option
comparison is linear in the compared byte sequences and occurs on option changes.
The worker correction adds one existing run-flag read before an I/O yield, with no
extra loop, task, allocation or synchronization object. Energy, throughput and device
storage behavior are not measured.

### Worker Stop before the first I/O wait

The new real-controller/native-engine test also exposed multi-worker Stop or
reconfiguration that failed to return. Runs 35903478155 and 35904315435 failed on
both Linux and macOS; these were observed failures, not successful validations or
assumed timeout-only infrastructure faults. The second run retained exact native
source/build inputs for reproduction; that temporary archive step is removed from
the final build script.

The worker event task can process Stop and clear run before the accept task reaches
its first cooperative I/O wait. The old yielder always suspended before inspecting
run. A wakeup already sent to the not-yet-waiting task then cannot wake the new wait,
so shutdown can remain blocked. A temporary local diagnostic observed stopped
workers entering that yield in a reproduction. The permanent fix checks run before
yielding, and retains the existing check after returning from yield. The four-line
addition is in the already declared lifecycle patch; the main branch and native
source pins are not changed.

worker_stop_probe.c compiles the actual worker body with only its yield boundary
substituted. The exact upstream worker blob is reconstructed and hash-checked:
683a773999569784b2a42d1bab136ef1c44a8101. The original fails the already-stopped
precondition; the fixed worker passes it plus normal-yield and Stop-during-yield
postconditions. This is a deterministic boundary check, not a replacement for the
real native controller/network test. Locally the full native test passed three
successive runs after the guard; the final test also adds 20 active Stop/restart
cycles with real authentication for each of one and four workers.

### Additional verification

The retained seven server scenarios and 512 old/new default/validation/YAML parity
cases remain. RevalidationTests adds 84 assertions: raw equality (Latin and Korean),
credential reconfiguration, latest-choice/Stop precedence, no overlapping invocation,
invalid replacements, bounded error handling, no automatic restart after native exit,
UTF-8 limits and YAML separators. The exact input model is a negative control: the
same 22 byte-sensitive postconditions fail there and must pass in the current model.
Those are postconditions and repetitions, not 22 device bugs.

The new native_controller_check.py links the production Swift controller and model
to the actual patched Hev static library. Test-only stdin/stdout commands drive it;
real TCP username/password handshakes check byte changes, 255-byte credentials,
Stop socket release and same-port restart with one and four workers. Forty extra
active Stop/restart cycles exercise the pending-wakeup correction. The old model
is separately linked against the same corrected native library as the equality
negative control, separating the two defects. This complements the existing native
parser/TCP and 40 pre-start cancellation cycles, rather than replacing them with a
mock. A successful invocation status is still not a listening-readiness guarantee.

Normal feature CI still uses BUILD_IPA=0 on Linux and Xcode 27, followed by actual
iPhoneOS 27 SDK type checking. Local Swift 6.2.1 Linux passed the seven retained
scenarios, 84 new assertions, 22 expected old-model failures and 512 parity cases.
Real native/SDK run identifiers and downloaded evidence are recorded below only
after inspecting those results. No earlier run is relabeled as this revalidation.

Physical iOS 27 SideStore signing/install, LiveContainer guest loading, local-network
permission, suspended process behavior, VPN/hotspot changes and UI interactions are
not established by host-side tests or SDK type checking. This branch does not add
Background keep-alive or persistent settings. The single root-owned controller is
the supported execution owner; simultaneous independent engines/controllers inside
one process are not a supported composition. No new readiness polling, automatic
retry policy, or host patch is added to hide those limits.

Public contracts consulted:
- https://docs.swift.org/swift-book/documentation/the-swift-programming-language/stringsandcharacters/#String-and-Character-Equality
- https://www.rfc-editor.org/rfc/rfc1929


### Completed revalidation evidence

Tested commit: `65332eee821b4ce07174b8cb1df8ecf80138c8b7`.
Tested tree: `b736cc761b2e08e6b315d228aec3c8b5f8fe50c7`.
Run `35905542895`: both Linux and Xcode-27 verification jobs succeeded. The earlier
runs `35903478155` and `35904315435` failed on the demonstrated native Stop race;
they remain failure evidence, not prior successful versions or generic CI glitches.
The temporary exact-native-input archive used for diagnosis is not in the final
build path. No stop deadline was extended and neither multi-worker checks nor
negative controls were removed to obtain a pass.

Both final jobs passed the retained seven server scenarios, 84 new model/state
assertions and 512 configuration/validation parity cases. The exact old Swift model
still failed all 22 selected byte-sensitive postconditions as expected. The actual
worker helper passed all three stop/yield postconditions; its exact upstream body
failed the pre-yield-stop case while preserving the other two. Negative-control
failures are intentional assertions about the old implementations, not failures of
the current branch.

The actual production Swift controller was linked to the real patched Hev library
on both platforms. Each produced all 14 expected result records across the old/new
model and one/four worker combinations: raw credential replacement, wrong/old bytes
rejected, Latin and Korean equivalence cases, 255-byte credentials, socket release
and same-port restart. Forty additional active Stop/restart cycles per platform
completed with real authentication. The original 40 native Stop-before-Start cycles,
TCP echo and actual parser fixtures also passed. Test command transports are not app
UI; repeated cycles are not independent iPhone or installer trials.

Xcode 27.0 `27A266a`, iPhoneOS SDK 27.0 typechecked all five production Swift files
for ARM64 at the unchanged iOS 17.2 minimum, with warnings treated as errors and an
empty diagnostic log. Native tests ran on Linux/macOS hosts; no app was linked for
iPhone, archived, installed or run on a Simulator in this audit. The SDK check is
not evidence of LiveContainer loader behavior or SideStore provisioning.

Downloaded final artifacts and verified SHA-256:
- Linux `10770803301`: `4f6e05cd0c4b93eb221cd90eae8d2c9b370e846197e4315ebbb835cef65f2e4b`
- macOS `10770338977`: `9e452b056ceae11b2b791bb2c1665f25fcdc854f97e6a3a66d6de061865dbc35`

All 61 source hashes in each artifact match the tested source tree. Format checks
and forward/reverse patch application passed for both the retained proxy hunk and
new worker hunk. The extended patch is explicitly locally owned/hash-locked in the
membership manifest; the old proxy hunk and inherited native tests remain separately
locked to their prior source. Removing the four-line guard reconstructs the exact
upstream worker blob checked above. This completion is a later README/specification-
only commit; production/build/test code stays byte-identical to the successful run.

Relative to the input branch, product changes are the 18-line model equality override
and four added native worker lines (including comment/spacing) in the existing patch.
Other changes are tests, build-test wiring, ownership validation and documentation.
There are eight changed existing files and four new test files; the other 49 input
files are byte-identical. Controller, root/editor, project/plist, defaults, original
native startup fix, immutable main and framework are not rewritten. The repository
still has the requested eight branches; the other seven heads are not changed.

IMPORTANT: `feature/settings-persistence` and `release/integrated` still pin the
previous server-control version. This audit does not automatically merge changes
into either branch. The previously provided 1.1.0(build 6) IPA does not contain these
two corrections and was not rebuilt or relabeled. A later explicit dependency update
and release verification/build are required to deliver them in the integrated IPA.

No further failing condition remains in the executed current-version checks. This
is not proof that every OS policy, app interruption, network interface or device
installation works. Physical iOS 27 SideStore/LiveContainer execution, VPN/hotspot
changes, suspend/termination behavior, UI interaction and energy remain untested.


## Six-feature closure recheck (2026-09-24)

This is a fresh verification of the unchanged product/test tree, not another
behavior change. Tested commit `92ac9aca5c1bdfca70875b2a5a437da7a447485a`,
tree `21b8afcd16697044d4861eca7e068b4508cffc39`, run `35928295462`:
both Linux and Xcode 27 jobs passed on their first attempt. Downloaded Linux
artifact `10780495023` has SHA-256
`97c4324279ab4bf6c7ab5aeb7eb798f06974e6e0b9e3b5db9a6620d11c3fc1b3`;
macOS artifact `10779623178` has SHA-256
`728f16bba4fb42da0555883918776d2c0d4df8e6c26744ba5e811b08c6ef7e9b`.
All 61 source hashes in each artifact match the unchanged input tree.

The seven server scenarios, 84 current assertions, 512 parity cases, 14 native
controller result records, 40 active Stop/restarts and 40 pre-start cancellations
per platform passed again. Expected failures of the old model/worker were retained.
The Xcode 27.0 `27A266a` / iPhoneOS 27.0 ARM64 typecheck passed with an empty
diagnostic log. There was no app archive, IPA, Simulator or physical-device run.

The role remains server configuration and execution only, independent of JSON
persistence, Background, statistics and icon resources. The six-feature closure
updates the downstream settings-persistence pin separately after this commit is
finalized; the older IMPORTANT paragraph above describes the prior audit, not
that later dependency update. main and release/integrated remain excluded and
unchanged. Physical iOS 27 SideStore/LiveContainer admission, UI/network-policy
interactions and energy are still not certified by these host tests. No additional
runtime defect was identified in the reviewed scope. This section and its mirror
are documentation-only additions after inspecting the completed evidence.
