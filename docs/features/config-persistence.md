# SOCKS5 for iOS: durable configuration and file management

`feature/config-persistence` owns permanent option storage, restoration, migration
and configuration-file import/export. It replaces the broad `feature/settings`
branch while retaining that branch's commit history as a parent. Its explicit
code dependency is `feature/server-runtime`, not an independent copied controller.

## Responsibilities and boundary

This branch adds `AppSettings`, `SettingsStore`, native JSON import/export and the
Settings screen. It stores the eleven server options, desired Start/Stop, both
Background choices and the selected tab in schema version 1. Unavailable tabs fall
back to Server for display without erasing their stored identifier. The standalone
app has Server and Settings; it does not implement audio/location keep-alive or traffic
statistics. The inherited server form/controller/validation/native lifecycle patch
are owned and tested by server-runtime.

`SettingsStore` never starts, stops or polls Hev. `AppRoot` bridges stored values to
`ServerController.apply(configuration, running:retry:)`. On launch or valid import,
stored intent is applied through that adapter. The server controller does not know
about storage or tabs. A valid file can change running services immediately, as
before; configuration errors are checked before disk or live-state replacement.

## Preserved persistence contract

One `Application Support/Socks5/settings.json` is atomically replaced on real edits,
not on a periodic timer or application termination. Identical values do not write.
Incomplete draft text can be retained while stopped; execution/import must satisfy
the shared server validator. File reads are bounded at 65,537 bytes and encoding/
decoding rejects files over 65,536 bytes. The schema, key names, defaults, credentials,
selected-tab identifiers and legacy background keys remain compatible with the
previous settings branch. No new JSON schema version or second store is introduced.

Failed loading preserves unreadable bytes and reports an error. Failed explicit
saving still updates live user intent so Stop/Off is not blocked; disk may retain
older intent until a later save succeeds. There is no automatic save retry or
power-loss durability guarantee at every instruction. Migration removes the two old
Background UserDefaults keys only after the first successful JSON save, including
a later recovery after initial storage failure.

File-provider access is security-scoped and coordinated off MainActor. A revision
and cancellation checks prevent slow/cancelled imports from undoing a newer Stop,
edit or import. Coordination already waiting inside the OS is not forcibly killed;
its stale result is rejected before applying. Files must be trusted: exported JSON
contains authentication credentials in plaintext. No keychain or hidden host storage
is added to the owner's single-file configuration contract.

## Why this branch depends on server-runtime

Settings validation and the standalone application's execution both need the same
server model and runtime. A declared parent dependency allows one copy and one owner
of those files, instead of parallel server forms/controllers or a new generic plugin
framework. The parent can run and be tested with no permanent storage. This branch
can replace its storage implementation without changing the parent state machine.
`docs/feature-membership.json` pins and byte-checks all inherited runtime files.

The former history is retained in Git and its last README is preserved in
`docs/history/settings-before-split.md` as historical evidence. That old combined
scope is not the current responsibility statement. Only model/error extraction and
root/view adapter signatures changed; the validated SettingsStore and SettingsView
production bytes remain identical to `16689f780f3e0e0c9344397273528697f197c9e5`.

## Support and validation

| Item | Scope |
| --- | --- |
| Minimum OS | Existing iOS 17.2, not a test claim for every intermediate release. |
| Intended use | Physical iOS 27.0, SideStore standalone installation or LiveContainer guest execution. |
| Build tooling | Xcode 27 / iPhoneOS SDK 27 for current full composition. |
| Settings location | Relative application-support path and standard guest/application defaults; no fixed signed Bundle ID or app-group entitlement dependency. |
| Installation evidence | No new physical SideStore/LiveContainer/file-provider test is implied by source or macOS CI checks. |
| Validation command | `bash Build/build.sh --checks-only`; no app archive or IPA for this feature's normal CI. |

Checks include the storage regression suite, controlled provider-order/cancellation
and migration tests, input boundaries, schema round-trips and real Foundation file
I/O. The server suite is inherited and separately executed, with real native
lifecycle/TCP/YAML tests supplementing its state-machine double. Linux compatibility
doubles do not simulate iOS permissions. Files/iCloud UI, device-lock file protection,
host sandbox mapping and actual shutdown timing require device testing.

The split adds no timer, polling, queue, persistent file or diagnostic service.
Root adapters preserve immediate user actions and existing error visibility. No
battery, throughput or latency improvement is claimed merely from reorganizing code.

README maintenance: mirror this file at `docs/features/config-persistence.md`.
Record minimum/target/tested versions separately, source/run/artifacts, known installer
versions, passed/failed/not-run checks and limits. Historical audit results remain
attached to their old commits. SDK compilation is not physical-device certification.
