# SOCKS5 for iOS: settings

This is the focused `feature/settings` branch.
For the complete app use `release/integrated`; the shared app + engine baseline remains on `main`.

Build and verification: [instructions](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/settings/docs/build-and-validation.md).
The following specification is also preserved verbatim at `docs/features/settings-lifecycle.md`.

# Unified settings and server lifecycle

## Goal and isolation

`feature/settings` owns persistent user choices and server start/stop coordination.
It is not a new proxy or I/O abstraction. It starts from combined main and does not
include statistics or the background implementation. The JSON schema retains the
background switches and all tab identifiers for lossless exchange with the integrated
app; unavailable tabs display Server without overwriting their stored identifier.
The standalone UI has Server and Settings. The final root adds the other features
and applies the same stored values to their real controllers.

The owner requested crash-resistant restoration, not a save-on-normal-exit feature.
Values are therefore written when edited, including the selected tab and desired
Start/Stop, rather than relying on application termination callbacks.

## Supported versions and installation environments

| Item | Declared or verified scope |
| --- | --- |
| Minimum deployment target | iOS 17.2, unchanged. This is not a claim that every intervening iOS version was tested. |
| Intended user environment | Physical iOS 27.0 iPhone; SideStore independent installation OR LiveContainer guest execution. |
| Actual SDK validation | Xcode 27.0 build 27A266a, Apple Swift 6.4, iPhoneOS SDK 27.0; ARM64 type checking of all seven production Swift files with minimum iOS 17.2. |
| Actual test execution | macOS 27.0 build 26A5406e and local Swift 6.2.1 Linux. Real Foundation JSON/files; controlled provider ordering; substituted engine for Swift state tests; real pinned native parser/relay/lifecycle on macOS. |
| Physical installation testing | Not performed in this audit. No SideStore or LiveContainer version is claimed tested. |
| App/IPA build | Not performed. The checks-only job skips the production archive/IPA job. Type checking is not linking or device execution. |

The settings format and relative Application Support path do not require a fixed
signed Bundle ID, app group, keychain group, BGTask registration or NetworkExtension.
SideStore installation can change application identity/container; preserving the
same container or copying settings between installations is not automatic proof
provided by these tests. In LiveContainer, the guest depends on the loader's sandbox
and UserDefaults mapping. No host IPA, permissions, signature or bundle identifier
is modified. Native file-picker/provider permissions and file protection must still
work in the actual installed environment. No host compatibility toggle is introduced.
The standalone Settings branch does not implement location/audio keep-alive; it only
retains those choices in the portable model for the integrated composition.

## Data model and schema

`AppSettings.swift` is a Codable, Equatable value type. Version 1 contains all eleven
original server fields, `serverRunning`, `background.continuousLocation`,
`background.silentAudio`, and `selectedTab`. Server fields are strings where the UI
edits text, allowing an incomplete value to be retained as a draft while stopped.
Settings do not contain byte counters, location coordinates, diagnostic states,
error strings, or secrets outside the user's configured authentication values.

`ServerSettings.configuration()` validates before execution. Workers must be 1-64,
the TCP listen port 1-65535, and the UDP listen port 0-65535. Text is single-line,
with a maximum of 255 UTF-8 bytes per field, matching the native parser's 256-byte
buffers. Username and password must be both empty or both present. Overlong fields
are rejected before execution/import rather than silently truncated by Hev; raw
draft text can still be saved while being edited. Single quotes are doubled when
constructing YAML.
All original server options remain available and keep the original defaults.
The engine still resolves/validates actual interface and address availability.

During reorganization, Unicode newline characters were added to the rejected set.
A single-line UI normally cannot enter them, but a JSON import can. U+0085, U+2028
and U+2029 must not create YAML structure inside a nominal string. Encoding now uses
the same 64-KB limit as decoding so a newly exported snapshot is not too large for
its own loader. Startup file reads are bounded like file-provider reads.

## Storage and interchange

`SettingsStore.swift` is a MainActor ObservableObject holding one JSON value.
`Application Support/Socks5/settings.json` is atomically replaced when the value
changes. Identical changes do not serialize or write. There is no periodic saving
and no disk write from the statistics, location, or audio hot paths. On iOS the
file remains available after the first device unlock through the file-protection
option used for atomic writes. This is not encryption of exported JSON.

On the first launch without JSON, the previous background UserDefaults keys are
migrated. Old keys are removed only after a successful file write. If the first
write fails,
the first later successful edit/import write completes that pending cleanup; no
automatic retry or second persistence store is added. An unreadable
saved file fails closed with a visible error and is not overwritten during load.
If a later explicit edit cannot be persisted, the error remains visible, but the
in-memory choice is updated so storage failure cannot prevent Stop or Off.

`SettingsView.swift` uses native file import/export. Security-scoped provider access
is coordinated off MainActor; reads are limited to 65,537 bytes so the decoder can
reject oversized input without allocating arbitrary file contents. An in-memory
revision prevents a slow import from replacing
a newer edit, explicit Stop (even if already stopped), or a newer import. Cancellation
is checked before reading and before applying the result. A stale result throws a
visible error without changing disk or live state; importing it again is an explicit
replacement. A provider operation already blocked inside coordination is not forcibly
terminated by cancellation and may finish later, but its canceled result is not
applied. No BGTask, extra timer or host change is used. Import validates
the whole model and executable settings before replacing disk or live state. A valid
import can immediately start/stop services and select another tab. Exports include
the authentication password in plaintext. Keep them private and only import trusted
configurations. No extra keychain service is silently mixed into the owner's
single-file configuration format.

## Server execution

`ServerController.swift` owns the blocking engine invocation independently of tab
visibility. A current configuration and desired configuration serialize ordinary
Stop/Start and imported reconfiguration. The old blocking call must return before
the next one begins. UI state is changed on MainActor; Hev runs on a background queue.
No packets, sockets, or data buffers are reimplemented here.

A saved Start is applied when the app launches. A saved Stop remains stopped.
The app cannot relaunch its own terminated process. Status is invocation status,
not proof that the OS has accepted a particular listening address. Engine failures
are shown. The existing attempted-configuration guard prevents unrelated
tab/foreground changes from repeatedly starting an already-failed configuration.
Explicit Start, a new configuration, or a completed Stop/Start can try again. This
is deliberately not the infinite retry policy used for silent audio.

## Existing native startup cancellation correction (preserved)

The previous mock engine remembered a Stop before Start, but the real Hev path
could hang when workers > 1. A pending SYNC_STOP made `hev_socks5_proxy_run()` return
before SYNC_CONT; initialization had cleared SYNC_ABRT, leaving worker threads
waiting forever while finalization joined them. The actual native probe timed out
before the correction, although the old Swift mock tests passed.

`Patches/hev-server-startup-stop.patch` sets SYNC_ABRT immediately before that early
return. It is a two-line net change inside the existing branch; no new readiness
API, polling loop, thread, callback, or state machine is added. It is separate from
UDP/statistics patches and belongs to this feature. The integrated composition at
the original settings checkpoint included six patch
files: two UDP, three statistics, and this lifecycle fix. This audit preserves only
the one declared settings patch here; it does not update the integrated branch.

`server_lifecycle_host.c` and `server_lifecycle_regression.py` verify 20 real
Stop-before-Start cycles each with one and four workers under a subprocess deadline.
The unchanged relay loop is never replaced. Broader unrelated upstream features
are not claimed to have been formally verified or redesigned.

## Verification and ownership

Settings tests use real Foundation file I/O and isolated temporary files. Server
controller tests substitute only the blocking engine to force transitions, and
include unexpected engine exit, suppressed automatic retry, explicit retry, and
completed stop/start. The real C probe complements those mocks. JSON round trips,
legacy migration, all fields/tabs, validation failures, atomic import behavior,
unreadable storage, oversized encoding, and Unicode YAML separators are tested.
The source-scope check verifies this branch's single-window ownership, binding of
all eleven fields, native patch declaration and settings/root wiring. This is not
a new verification of release/integrated or of physical UI interactions. Tests are
not application resources.

See `Build/features.json`, `docs/build-and-validation.md`, and the CI artifact logs
for exact source revisions and executable commands. These tests do not simulate
an iOS process kill at every filesystem instruction or guarantee startup with an
unavailable network interface.

## Completed Settings-only audit (2026-09-23)

Input feature commit: `9c2e76afcde7a20ff1bbdcf2a1f7e9092e1a98fd`.
Excluded inherited main baseline: `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
Tested commit: `42486c9ec57a8694a646a6294af6b742b87c3b1a`.
Tested tree: `4f49a4da7c605131c7973ec2b667652f3ff30c17`.
CI run: `35836607369`; `settings-checks` succeeded, production `verify` deliberately
skipped. This result record is a later README/specification-only change, not another
execution. Product/test code remains the tested bytes. No other branch was modified
and no audit branch was created; the seven existing branches remain the only ones.

### Reproduced defects and minimal changes

| Finding | Correction |
| --- | --- |
| A canceled import, a slow earlier import or an import predating Stop/edits could still replace current settings after provider coordination returned. | Add one MainActor-owned revision and pre/post-read cancellation checks. Newer explicit actions win; disk and live state remain unchanged when the stale import is rejected. |
| Failed first migration left the old background keys behind even when a later write succeeded. | Keep the migration defaults reference only until the first successful write, then remove the two migrated keys. Failed writes never delete them. |
| Address/interface strings up to 1024 bytes passed Swift validation, but the actual Hev parser retained at most 255 bytes. | Apply the 255-byte limit to all seven executable text fields. Keep quoting, numeric ranges, drafts, defaults and schema version unchanged. |

The original store failed 13 of the same 15 import/migration postconditions; the
corrected store passed all 15. The negative control runs the actual original store
with controlled coordinator timing and real files, not a hand-written imitation
of its logic. These are multiple postconditions of the documented cases, not 13
independent user-device bugs. The original Swift model also emitted a 256-byte field
that the actual pinned native parser reduced to 255, proving the length mismatch.

Only AppSettings.swift and SettingsStore.swift change production behavior. The
server controller, UI, root, project, Info.plist, all eleven defaults, existing native
startup/stop patch, original settings/server/native tests, source pins, framework and
shared Build scripts remain unchanged. The revision is one UInt64; migration retains
one existing UserDefaults reference temporarily. No timer, additional execution queue,
extra file or per-packet/audio/location write is introduced. Provider work remains
off MainActor; the existing small synchronous atomic save behavior is retained.
No energy, CPU, storage-latency or throughput measurement is claimed.

### Verified results

| Check | Result |
| --- | --- |
| Original settings tests | 39 checks passed: fields/tabs, JSON, legacy migration, failed imports/saves, drafts and invalid input. |
| Original server controller tests | Seven named scenarios passed, including 50 serialized Stop/Start repetitions and no automatic loop after an engine exit. Engine calls are substituted only for these Swift state tests. |
| Additional input/storage tests | 116 assertions passed, including UTF-8 and numeric limits, all field/control combinations, exact 64-KB boundary, failed-write atomicity, fail-closed load and unchanged-file timestamp. |
| Concurrent/canceled import and migration | 15 assertions passed. Original-store negative control reproduced its 13 failed postconditions. |
| Repeated persistence | 250 sequential atomic import/readback cycles; this is not an injected power-loss or SIGKILL test. |
| Actual native lifecycle | 20 Stop-before-Start cycles with one worker and 20 with four workers passed without a hang. The existing two-line lifecycle patch was preserved. |
| Actual native parser and TCP | Swift-generated default/quoted YAML matched the real Hev getters; native SOCKS5 TCP echo passed. |
| Source preservation | 33 inherited main files byte-identical; six main-file integration/configuration deltas checked separately. Native patch apply/format/reverse and source pins passed. |
| Actual iOS 27 API type checking | All seven production Swift files passed warnings-as-errors; diagnostic log empty. No application was linked, archived or installed. |

The original 39 settings checks use real Foundation JSON, FileHandle, atomic writes
and isolated UserDefaults. On macOS their regular import path uses real
NSFileCoordinator; the concurrency test alone substitutes coordinator scheduling.
Linux uses small UI/provider compatibility doubles; neither platform reproduces
iOS Files/iCloud delivery, security-scoped entitlements, protected-device startup,
SideStore signing or LiveContainer guest execution. Native tests run on macOS, not
in an iPhone process. Default path/plist/bindings checks are source checks, not UI taps.

First run `35836071124` failed before the tests because the newly added outer
main-to-feature whitespace check misread context-only spaces in the existing patch
file as source whitespace. The patch was not changed. Ordinary source/doc whitespace
is now checked separately; its actual native payload remains checked by the unchanged
`git apply --whitespace=error-all` path and its exact bytes remain scope-locked. No
runtime assertion was removed. This failed artifact is retained as a failure, not
reported as a successful API or functional test.

Successful artifact `10739547743`, SHA-256:
`95bfde19008ea6264300a2b65ac09f11c710fbf31f8928e6b1e5b667e342737e`.
Failed artifact `10739082634`, SHA-256:
`e926df339fb08da4ebeca8d227e56683b955c2e0778af5af57e56ae245af855f`.
Both downloaded ZIP digests were checked. All 60 tested-source SHA-256 values and
the reconstructed Git tree match the tested commit; input and main source archives
also reconstruct their recorded trees. Artifacts contain source and test logs, no IPA.

### Remaining limits and operating contract

App launch restores saved intent, not system permission or proof of a listening
socket. Invalid executable drafts remain stored but do not start the engine. A
failed explicit save leaves an error and updates live intent, so Stop/Off can work;
the last successfully saved file may still contain older intent until a later save
succeeds. There is no automatic disk-save retry. A failed import write does not alter
live settings. Atomic replacement reduces partial-file exposure; no claim of
power-loss durability at every filesystem instruction is made.

Task cancellation is cooperative: it prevents applying a canceled import after
reading, not guaranteed immediate termination of a blocked external provider call.
The UI does not add a new progress monitor, import timeout or cancellation button.
Exports still contain plaintext configured credentials by the existing portable-JSON
contract. Actual device file protection, picker interactions, app termination,
network permissions, host configuration, lock-screen behavior and energy use remain
unverified. These limits are not converted into unsupported host modifications.

**README maintenance rule:** keep this README and docs/features/settings-lifecycle.md
byte-identical. Record minimum/target/actually-tested OS separately, exact SDK/compiler,
installer/host versions when known, source commit/run, pass/fail/not-run scope, design
costs and remaining limits. Preserve old evidence with its own version. Do not equate
source/SDK/CI success with physical SideStore or LiveContainer validation.

Primary references (API contracts, not device-test evidence):
- https://developer.apple.com/documentation/swift/task/checkcancellation()
- https://developer.apple.com/documentation/swift/task
- https://developer.apple.com/documentation/foundation/nsdata/writingoptions/completefileprotectionuntilfirstuserauthentication
- https://developer.apple.com/documentation/swiftui/view/fileimporter(ispresented:allowedcontenttypes:oncompletion:)
- https://github.com/heiher/hev-socks5-server/blob/b3585289622561caf4b8789b436cc8820ecd6be0/src/hev-config.c
