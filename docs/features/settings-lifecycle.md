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

## Data model and schema

`AppSettings.swift` is a Codable, Equatable value type. Version 1 contains all eleven
original server fields, `serverRunning`, `background.continuousLocation`,
`background.silentAudio`, and `selectedTab`. Server fields are strings where the UI
edits text, allowing an incomplete value to be retained as a draft while stopped.
Settings do not contain byte counters, location coordinates, diagnostic states,
error strings, or secrets outside the user's configured authentication values.

`ServerSettings.configuration()` validates before execution. Workers must be 1-64,
the TCP listen port 1-65535, and the UDP listen port 0-65535. Text is single-line,
with bounded UTF-8 sizes; username and password must be both empty or both present
and each at most 255 UTF-8 bytes. Single quotes are doubled when constructing YAML.
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
migrated. Old keys are removed only after a successful file write. An unreadable
saved file fails closed with a visible error and is not overwritten during load.
If a later explicit edit cannot be persisted, the error remains visible, but the
in-memory choice is updated so storage failure cannot prevent Stop or Off.

`SettingsView.swift` uses native file import/export. Security-scoped provider access
is coordinated off MainActor; reads are limited to 65,537 bytes so the decoder can
reject oversized input without allocating arbitrary file contents. Import validates
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
are shown. An attempted-configuration guard added in this audit prevents unrelated
tab/foreground changes from repeatedly starting an already-failed configuration.
Explicit Start, a new configuration, or a completed Stop/Start can try again. This
is deliberately not the infinite retry policy used for silent audio.

## Real startup cancellation defect corrected in this review

The previous mock engine remembered a Stop before Start, but the real Hev path
could hang when workers > 1. A pending SYNC_STOP made `hev_socks5_proxy_run()` return
before SYNC_CONT; initialization had cleared SYNC_ABRT, leaving worker threads
waiting forever while finalization joined them. The actual native probe timed out
before the correction, although the old Swift mock tests passed.

`Patches/hev-server-startup-stop.patch` sets SYNC_ABRT immediately before that early
return. It is a two-line net change inside the existing branch; no new readiness
API, polling loop, thread, callback, or state machine is added. It is separate from
UDP/statistics patches and belongs to this feature. The final release therefore
has six patch files: two UDP, three statistics, and this lifecycle fix.

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
The integration suite verifies single-window ownership, binding of all fields,
and complete feature wiring. Tests are not application resources.

See `Build/features.json`, `docs/build-and-validation.md`, and the CI artifact logs
for exact source revisions and executable commands. These tests do not simulate
an iOS process kill at every filesystem instruction or guarantee startup with an
unavailable network interface.
