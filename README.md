# Persistent settings and JSON file management

This branch is `feature/settings-persistence`, replacing the former mixed-purpose
`feature/settings`. Its incremental responsibility is permanent option storage,
restoration, migration and JSON file import/export. It depends on the exact
`feature/server-control` commit in `docs/feature-membership.json`.

## Division of responsibility

Inherited, unchanged: ServerSettings, ServerController, the shared server editor,
native startup/stop patch and server-specific tests. This branch adds AppSettings,
SettingsStore, SettingsView and the root wiring that applies saved intent to the
server. It does not implement another engine controller or duplicate validation.
The server API accepts server options plus running intent, not the whole app model.

AppSettings retains JSON schema version 1, all eleven server fields, serverRunning,
both Background choices and all tab identifiers. The extracted ServerSettings is
still encoded under the same `server` key. Original defaults, file names and data
format are unchanged. ServerRunning is saved user intent, not the runtime status.

SettingsStore retains the audited contracts with the narrowly scoped corrections below: atomic bounded
JSON, save-on-edit rather than save-on-exit, already-saved unchanged-value write suppression,
64-KB maximum, fail-closed loading, legacy Background migration with cleanup only
after the first successful save, canceled/stale import protection and visible save
errors. A failed save still applies Stop/Off in memory. Import validates and writes
before committing live values. A slow provider cannot undo newer edits, explicit
Stop or a newer import. Security-scoped reading and file coordination remain off
MainActor. Cancellation prevents applying the result; it does not forcibly end a
provider operation already blocked inside the OS.

SettingsView remains byte-identical, using the native JSON importer/exporter.
Exports include configured passwords in plaintext; keep files private and import
only trusted configurations. No second keychain persistence path is introduced.
The standalone root has Server and Settings; unavailable Background/Statistics tab
identifiers survive JSON exchange and display Server without rewriting the value.
Background choices are retained, not implemented in this standalone composition.

## Why the dependency is intentional

An independent storage implementation would still need a server-option schema and
an integration adapter. Reusing the existing pure server model avoids duplicate
validators and controllers. Removing this persistence layer leaves a functional,
memory-only server app. The reverse dependency does not exist. The integration root
owns the relationship; neither the store nor the editor starts Hev on its own.

## Source continuity and verification

The former settings HEAD `16689f780f3e0e0c9344397273528697f197c9e5` is retained as a
merge parent, not discarded history. Its full review is preserved verbatim in
`docs/history/settings-before-split.md`, with its original test scope and commit.
The old branch name is removed only after the replacement and integrated build
are verified. The final repository has eight requested branches, not an audit branch.

Original settings assertions, controlled import/migration ordering and validation
checks remain. Only test input paths change for ServerSettings extraction; server
state tests move to Tests/ServerControl. Local Linux re-execution passed 39 original,
116 boundary and 15 import/migration checks. New CI results, exact source refs and
artifact hashes are recorded after completion, not inferred from old evidence.

## Versions, storage and remaining limits

Target: physical iOS 27.0 through SideStore independent installation or LiveContainer
guest execution. Minimum iOS remains 17.2, Bundle ID `hev.Socks5`. Application Support
path remains `Socks5/settings.json`; all migrations/keys are unchanged. Reinstalling
into a different container does not automatically copy options. LiveContainer's
sandbox/UserDefaults mapping and native file-picker permissions remain host/runtime
conditions, not modifications made by this feature.

No actual SideStore/LiveContainer installation or provider UI test is claimed by
SDK, Foundation or Simulator tests. If a disk write fails, the last successful file
may retain earlier intent until a later explicit save succeeds. Repeating the same
choice retries a pending failed save; there is no automatic retry timer. Atomic replacement is not a
proof against every power-loss timing. Exports remain plaintext. The split adds no
periodic save, extra timer, socket, background task, host patch or new persistence
file. CPU/battery/storage performance has not been benchmarked.

Build/check commands are in docs/build-and-validation.md. Current source ownership
and pinned dependency files are enforced by Build/check_ownership.py. Keep this
README and docs/features/settings-persistence.md identical. Always separate
minimum/target/tested OS, SDK, device/installer versions, tested commits/runs and
pass/fail/not-run scope; never replace physical validation with compilation claims.

## Completed extraction verification (2026-09-23)

Tested commit: `2c186d71be950fd258cfc1fc0dcaebc31388480e`.
Tested tree: `40a7d92ce0ea88c28a9a917295d4ed766d8880b8`.
Actions run `35843705592`: Linux and Xcode-27 jobs both succeeded on their first
run. Each passed the retained 39 settings, 116 boundary and 15 import/migration
assertions, plus the inherited seven server scenarios and 512 exact model/YAML
parity cases. Native parser, TCP and 40 pre-start cancellation cycles also passed.
The macOS job used Xcode 27.0 `27A266a`, iPhoneOS SDK 27.0 and typechecked all eight
production Swift files with warnings-as-errors and an empty diagnostic log.
No standalone IPA or app archive was built. These are not installer/device tests.

Downloaded Linux artifact `10742562023` SHA-256:
`4a10a9335d076d3bf9a308202dd04187198e56a6198b04c803ea314ece4caa6e`.
Downloaded macOS artifact `10741664357` SHA-256:
`a6612c66486f86fdec858c4dccadaa531d497026b21cbc8086a4c3fa1c65e9d1`.
Both digests and all 67 source hashes were checked against the exact tested Git
commit. This section is a later documentation-only update; runtime and tests remain
the successful source. Historical settings and the server dependency are both
retained as actual commit ancestors, not merely named in this document.

## Latest server dependency and persistence revalidation (2026-09-24)

Input persistence: `633c04905ed7ca4acd7272fb040c8d1c66cb38e3`.
Updated server dependency: `011f7f61b2969f7a85708d535d3ad466a9ac148e`.
The latter is an actual merge parent/ancestor, not only a label. All 17 declared
server-owned files, including model, controller, editor, extended lifecycle patch,
server documentation and server tests, are copied exactly from that commit and
hash-checked. The server branch itself is not changed. This includes raw UTF-8
option equality and the pre-yield worker Stop correction. The inherited code and
native test suites run again in this two-feature composition.

The root still owns one store and one server controller. ServerControl does not
access the store. AppSettings equality now inherits the byte-exact server model:
canonically equivalent but byte-distinct credentials are saved and reach the normal
reconfiguration path. Schema v1, option names/defaults, YAML validation, file path,
error strings, bindings and plaintext export are unchanged. Store and file-management
fixes do not modify the inherited server files.

### Reproduced persistence boundaries and corrections

| Boundary | Minimal correction |
| --- | --- |
| fileExists can return false for an inaccessible existing file, which the old initializer treated as first launch and used to restore legacy Background On values. | Read directly and migrate only for the two documented Cocoa absence codes (fileReadNoSuchFile or fileNoSuchFile). Other read/decode failures leave safe defaults, report the error and do not remove the original file or old keys. Unknown access is not absence. |
| After a failed explicit save, memory contained the user's Stop but disk still contained Start. Once storage recovered, repeating Stop was skipped because memory already matched. | Track one pending-save Boolean. An explicit identical choice retries only when an earlier save remains pending; success clears that state. Already durable identical choices still perform no write. |

Pending initial migration saves use the same state. Migration keys are removed
only after a successful write, including an explicit retry of an identical choice.
A rejected import never changes live settings or marks an otherwise clean snapshot
unsaved. A corrupt or access-denied load does not set pending-save merely because
an error is visible: an unchanged setter must not erase the unreadable original.
Existing stale-import revision/cancellation checks are preserved. An already blocked
provider call is not forcibly canceled; only its late application is prevented.

These corrections add one Boolean and reuse the existing synchronous, bounded,
atomic write path. No new timer, task, queue, socket, file, host identifier,
entitlement, UI control or automatic retry loop is added. A direct read replaces an
existence preflight; actual energy and filesystem latency have not been measured.
The import/migration test's failure fixture is now a genuinely absent file inside
a readable but unwritable directory, not a non-directory parent that yields a
read error. All 15 assertions and the historical 13-failure negative control remain.
Tests run unprivileged; a root local container drops child privileges so permission
checks cannot silently pass with root bypass. This is POSIX access testing, not an
iOS locked-device file-protection test.

### Verification layers

The unchanged 39 settings, 116 boundary and 15 controlled import/migration assertions
are retained. New tests exercise 33 persistence assertions and six access assertions
with real files, JSON, UserDefaults and bindings (Linux UI/provider APIs are small
doubles). Their exact previous store is a negative control: four persistence
postconditions and one access postcondition fail there and must pass in the current
store. Two hundred sequential byte-sensitive snapshots are checked, not claimed as
power-loss/crash injections. Historical evidence remains under its own source/ref.

The new NativePersistenceHost links the actual store, model and server controller
to real patched Hev. Sixteen recorded checks span one/four workers: coordinated file
import, binding credential-byte edits, complete imports, old-byte rejection, 255-byte
credentials, invalid-import preservation, storage-failed Stop, identical Stop save
retry, and restoration of Start/Stop in fresh native processes. The command adapter
mirrors the root's snapshot application; it does not execute SwiftUI onChange, tap
buttons or operate the iOS file picker. On macOS regular reads use NSFileCoordinator;
Linux uses a provider double. Network sockets, JSON and file writes are real.

The inherited server checks retain seven state scenarios, 84 assertions, 512 exact
configuration parity cases, old-model/old-worker negative controls, native controller
authentication and pre-start/active Stop cycles. The existing CI uses BUILD_IPA=0
and iPhoneOS 27 ARM64 type checking; it never archives an app in this verification.
Actual run/toolchain/artifact outcomes are recorded only after inspection below.

No physical iOS 27 SideStore/LiveContainer installation, file-provider UI, host
sandbox mapping, device file-protection behavior, VPN/hotspot or energy test is
claimed. Existing iOS 17.2 minimum, Bundle ID, project, Info.plist and permissions
are preserved. There are still eight branches. Only settings-persistence is updated;
release/integrated remains at its old pins, and its existing IPA is not rebuilt or
relabeled as including this update.

Primary API contracts (not device-test results):
- https://developer.apple.com/documentation/foundation/filemanager/fileexists(atpath:isdirectory:)
- https://developer.apple.com/documentation/foundation/cocoaerror/code/filereadnosuchfile
- https://docs.swift.org/swift-book/documentation/the-swift-programming-language/stringsandcharacters/


### Completed dependency update and verification

Tested commit: `680c28cbff108ad31b92720a09cb2a7ec4722a7e`.
Tested tree: `86b5315b9cd71ed76064f917e6da984534c775bd`.
Merge commit `6d3c05a2f8ce8952758cc405d176a5690975242b` has the original
persistence and latest server-control commits as its two actual parents. All 17
server-owned files, their hashes and ancestry checks pass without editing them.
The historical server report's downstream-pin warning describes its own checkpoint;
the current dependency for this branch is the explicit 011f7f61 pin above.

Run `35914811946` completed successfully on Linux and Xcode-27. Each job passed the
retained 39 settings, 116 validation and 15 coordinated-import/migration assertions,
plus 33 persistence and six access-boundary assertions: 209 in these five suites.
The same previous store failed four persistence and one access postconditions as
expected; the earlier pre-audit store still failed the original 13 import conditions.
The denied-access test ran without root bypass and confirmed fileExists=false did
not establish absence. Actual FileHandle missing-file observations were Cocoa 260
on Linux and Cocoa 4 on macOS, for both an absent leaf and absent parent.

The first run `35913936943` had passed Linux and the real native integration on both
hosts, but failed macOS first-file migration: the first correction recognized only
Cocoa fileReadNoSuchFile (260), not Apple's fileNoSuchFile (4). That was a flaw in
this candidate, not a CI infrastructure failure. The follow-up recognizes both
explicit absence codes, retains access-error fail-closed behavior, and reruns all
checks. No original assertion was removed. The first workflow remains a failure
and its two source/log artifacts are retained; no failed SDK step is called a pass.

Both final jobs linked the real SettingsStore, AppSettings, ServerSettings and
ServerController with the actual patched Hev library. All 16 expected records per
platform completed: coordinated import, binding credential replacement, byte-exact
network authentication, fresh-process durable Start/Stop restoration, rejected
import preservation, real Stop despite failed save and later explicit same-value
save retry. File/provider and UI distinctions above still apply. These are native
host programs, not an iPhone app or a SIGKILL durability experiment.

The inherited seven server scenarios, 84 assertions, 512 configuration parity cases,
old-model/worker negative controls, 14 native controller records, 40 active Stop/restart
and 40 pre-start Stop cycles also passed per platform. Existing parser/TCP tests,
forward/reverse patch application, formatting, source locks and composition checks
passed. Repetitions are not independent physical-device trials. The local Swift 6.2.1
Linux recheck used the same final store and repeated the 16 real native persistence
records; it is separate from the CI and SDK evidence.

Xcode 27.0 build `27A266a`, iPhoneOS SDK 27.0 typechecked all eight production Swift
files for ARM64 at the unchanged iOS 17.2 minimum with warnings-as-errors; the
compiler diagnostic log is empty. Exact native-host OS build and Swift compiler
version were not captured by this workflow, so none are inferred. No Simulator,
physical iOS runtime, installation, app archive or IPA was executed or produced.
SideStore/LiveContainer versions and host permission behavior remain untested.

Downloaded and verified final artifacts:
- Linux `10774936556`: `40135d0038aa0973266bc32ccd929ea82b5039b3e4226e67f9023357dce7a753`
- macOS `10775066097`: `91d2e05d32630f28a35029039a0cbaf3eeb54891dfbdfa68a9ebded285066951`
First-run artifacts, retained with their failure scope:
- Linux `10774406306`: `15b0a561630901d58f1c85da7b3d3fd4699070d6dd7144018e086231418afc2d`
- macOS `10773854349`: `1c4f01f48e57daf80d964d22ac84bcd968be59e57afd8387a43630aa88cda0be`

Both final source archives and all 75 source hashes match the tested tree. Relative
to the previous persistence head, 12 existing files change and eight test files are
added (four inherited server tests, four persistence tests); 55 old files remain
byte-identical. The only persistence-owned production edit is SettingsStore:
nine inserted/three deleted lines, including comments. The two other product
changes are exact inherited ServerSettings equality and the native lifecycle patch.
AppSettings, SettingsView, root/editor, schema, default settings, project, Info.plist,
minimum OS, baseline framework and native source pins remain preserved.

The final completion commit changes only this README and its byte-identical feature
specification; product/build/test bytes remain the successful tested commit's bytes.
Only feature/settings-persistence advances. There are still eight remote branches,
and the other seven heads, including server-control and release/integrated, are not
changed. The existing integrated IPA contains neither these persistence fixes nor
the new server dependency; no new IPA is implied by this branch verification.

There is no new Save/Retry button and no changed Start/Stop enabled-state policy.
The pending-save correction operates when the existing setter is explicitly called
again (same or changed value); it does not automatically retry after access returns
or promise that a disabled Stop button can be pressed. A valid import remains another
explicit replacement path. If no later successful save occurs, disk may still hold
older intent. A corrupt/inaccessible initial load is not itself marked as a pending
save, so an unchanged value cannot silently destroy the unreadable original.

No failing condition remains in the executed current-version checks. File-provider
UI, iOS protected-data timing, host-container mapping, actual app relaunch after a
crash, remote interface/network permission and energy remain outside the tested
scope. These limits do not justify private APIs, host edits or unrelated features.
