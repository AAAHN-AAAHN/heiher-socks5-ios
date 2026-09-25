# Integrated SOCKS5 for iOS — current six-feature composition

## Status and target

This revision integrates the six pinned owners below into `release/integrated`.
Verification of this candidate is pending until the completed run and inspected
artifacts are recorded in the completion section. A configured CI job is not an
executed pass. The old 1.1.0/build 6 IPA is not relabeled as this source.

The target is a physical iPhone on **iOS 27**, either installed independently through
**SideStore** or executed as a **LiveContainer guest**. Those are different signing,
container, permission and host-session boundaries. The configured app minimum stays
**iOS 17.2**; it is not proof of execution on every intervening OS. Xcode/SDK, host
native tests, Simulator, SideStore, LiveContainer and real background execution
remain separate evidence categories. No physical installer or host version is
claimed tested here. The exact owner instructions are in `docs/top-level-principles.md`.

## Immutable owners and one-way responsibilities

| Branch | Pinned commit | Responsibility |
| --- | --- | --- |
| feature/udp-compat | 66e7196ef5faccc43d9b154cab21a94e4466a77e | Port-zero, address normalization, peer filtering and receive-queue continuation. |
| feature/traffic-statistics | 24d5fdeb2258d196125e24b9ae374543fd578d5c | External socket byte counters and visible/active Statistics sampling; includes the exact UDP owner. |
| feature/server-control | b4d20f8402cdcd5ee687d17f46bf71d38a9febb5 | Executable options, YAML, serialized Start/Stop/reconfiguration and native cancellation boundaries. |
| feature/settings-persistence | f7713811c9668c5bb9000b1f9ec32523e5c7bc67 | JSON durability, restoration, migration and import/export; includes the exact server owner. |
| feature/background | 207214b41e0191345a46a820700b45d33dd7cb6e | Independent coarse location and single-player/single-timer silent audio recovery. |
| feature/app-icon | 1beaefa4e068a3b4e9473bab478b27526b88defd | Preserved opaque icon and standard asset metadata. |

The unchanged common base is `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
The previous release is `2dcfce074e288c942bd6582b3b77d4763c516a25`.
It and all six completed owners are retained as actual ancestors, not only README
labels. No feature head or main is moved and no branch is added or removed.

`docs/feature-membership.json` maps 97 owner files to exact commits, original paths
and SHA-256 values; the checker also verifies executable modes. Feature tests,
patches and documents are inherited rather than edited to fit the release. The
original feature root READMEs are in `docs/branches/`; full feature specifications
are in `docs/features/`. The old release README is preserved byte-for-byte in
`docs/history/integrated-before-20260925.md` and remains historical evidence.

The existing AppRoot is preserved byte-for-byte. It owns one SettingsStore, one
ServerController and one BackgroundKeepAlive, connects bindings and orders tabs as
Statistics, Server, Background, Settings. It does not duplicate their state machines.
The server module has no storage dependency. Background has no SettingsStore
reference: the release root supplies its bindings instead of running parallel
AppStorage/JSON systems. Statistics and icon introduce no reverse dependencies.

## Exact implementation changes relative to the old release

The current UDP owner adds its corrected peer/queue patch. The current server owner
adds raw UTF-8 option equality, pre-yield Stop handling and the idle prepare boundary.
The current store distinguishes absence from access failure and retries a pending
failed save on a later explicit equal-value setter. All are exact owner bytes, not
new release-specific implementations. Existing Background, statistics accounting,
icon, WAV, root, project, app entry point, Info.plist and defaults are preserved.

Seven native patches are applied exactly once: three UDP, three statistics, then
one server-control patch. The upstream app/server/submodule pins and committed
unpatched baseline XCFramework remain unchanged. A production build rebuilds the
framework from all seven patches before linking the app; the baseline framework
alone does not export the new prepare API. Packaging verifies both stats and prepare
symbols, ARM64/iPhoneOS metadata, resources, archive UUID/dSYM pairing and IPA bytes.

No extra production timer, queue, scheduler, observer, permission, host patch,
NetworkExtension, BGTask or resolver is introduced. The added release work is build,
source verification, test wiring and documentation. The retained owner changes have
their documented costs (peer comparisons/syscall, per-start prepare, one save flag);
no measured CPU, energy or throughput improvement is asserted.

## Operating and installation conditions

The build identifier for this new integration is **1.1.0 (build 7)**. Bundle ID
`hev.Socks5`, JSON schema v1 and `Application Support/Socks5/settings.json` stay the
same. Build metadata is set by the build commands; the source project's deployment,
identity and signing configuration are not rewritten. An unsigned IPA is input to
the user's signing/import workflow, not a file that iOS will execute unsigned.

For SideStore, use the existing independent app signing/install workflow. For
LiveContainer, import/update the guest through that host's existing workflow; guest
execution is not SideStore standalone execution. Preserve the existing identity and
data container to retain automatic settings restoration. Export JSON before an
installation replacement when preservation is uncertain; exports contain plaintext
credentials. No speculative host Bundle ID override, host IPA patch or new signing
entitlement is required by this integration. Actual admission and permissions still
need verification in the user's respective environment.

Use **UDP Listen Port = 0** for multiple unknown-client associations. The selectable
fixed-port constraint is retained, not repaired or made into a silent fallback.
Defaults are not changed. Peer filtering is not cryptographic authentication or
protection from every same-IP first-port race. Existing fragmentation, datagram-size,
address-family and routing limits remain those of the owner specifications.

Counters mean successful external socket I/O, not radio usage or remote delivery.
They are process-lifetime values, not settings. A failed disk write still permits
live Stop/Off but can leave older disk intent until a later successful explicit save.
Running status is invocation state, not listen-readiness certification. An OS-blocked
provider operation cannot be forcibly ended by canceling its late application.

Saved Background On is intent: callbacks/retries run only when iOS schedules the
process and permits audio/location use. No timer can execute after process suspension
or termination; no automatic relaunch is promised. Phone/Bluetooth/Siri, VPN/hotspot,
local-network permission, protected-data timing, lock screen and energy remain
physical-device/host test boundaries, not inferred from host unit tests.

## Validation plan and evidence separation

`bash Build/build.sh` validates pinned composition and the combined native library.
Linux explicitly builds buffered and splice modes, identified from object symbols;
Darwin uses buffered mode. The latest inherited native/model tests run against the
integrated sources, including UDP peer/queue cases, stats counter/error/sanitizer
checks, actual controller/Hev authentication and Stop races, and real JSON/Hev tests.
Background controller/lifetime tests run on both hosts; Apple Combine, real Timer/
RunLoop and AVAudioFile checks run on macOS. The full icon mutation suite runs in an
isolated exact-owner fixture while the integrated actual icon is independently
validated. This does not pretend an icon-only source gate accepts a combined app.

Build/integration_checks.py reuses the owner's exact shell failure tests against the
release entry points. Old success markers and package attestations are invalidated
at the start of a new attempt, diagnostic logs and nonzero failures are preserved.
No assertion is removed, warning suppressed or native timeout extended. Standalone
source gates remain in the original feature files; composition tests do not falsify
the integrated feature declaration to invoke them.

On Xcode27 the actual iPhoneOS archive is created and inspected, then the production
Simulator app is installed under original/remapped test IDs to verify saved tabs,
saved Start/relaunch/TCP and saved Stop. A separate temporary XCTest target drives
portrait/landscape controls, real native greetings, durable Start/Stop, Background
audio intent and Settings tab persistence in the unchanged integrated app. The
modified test bundle/project exists only in the audit workspace. Source files are
not added to the production target. Intent/taps are not OS interruption tests.

The workflow is read-only and no longer has the historical branch-deletion job.
History-maintenance scripts are preserved as history, not invoked by release builds.
All test exits, cleanup, logs, source archives and package evidence must be inspected
before completion. Job-level SUCCESS markers cover their own phase; only a complete
workflow and matching artifacts establish the whole executed matrix. Physical
SideStore/LiveContainer/background checks remain unperformed unless separately
recorded. No Simulator screenshot is a physical-install certificate.

Keep this README and `docs/features/integrated.md` byte-identical. Record exact
source/tree, run/attempt, toolchain, artifacts and their hashes, passed/failed/not-run
scope and remaining limitations after every relevant code or verification change.
