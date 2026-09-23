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

SettingsStore remains the audited implementation byte-for-byte: atomic bounded
JSON, save-on-edit rather than save-on-exit, unchanged-value write suppression,
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
may retain earlier intent until a later save succeeds. Atomic replacement is not a
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
