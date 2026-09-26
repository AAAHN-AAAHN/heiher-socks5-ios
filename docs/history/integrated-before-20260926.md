# Integrated SOCKS5 for iOS — current six-feature composition

## Status and target

This revision integrates the six pinned owners below into `release/integrated`.
Run `36082323598` at `8982c26418988af8461b29426ec3a41cdd084ad6` passed the
combined native, SDK, ARM64 archive/package and Simulator checks. The completed
evidence, prior failures and retained audio-session advisory are recorded below.
Physical SideStore/LiveContainer and background execution remain unperformed.
The old 1.1.0/build 6 IPA is not relabeled as this new 1.1.0/build 7 package.

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

## Completed integrated verification (2026-09-25)

Tested commit: `8982c26418988af8461b29426ec3a41cdd084ad6`.
Tested tree: `344b5751df098eeb0cf74179558f0811ce0e78d2`.
Actions run `36082323598`, attempt 1, completed successfully on both Linux and
Xcode 27. Native checks, the iPhone archive, package inspection, preseeded Simulator
cases, actual UI tests, result export and cleanup all completed. The Linux job's
Apple-only steps were skipped, not counted as Linux execution. The final result is
not inferred from an earlier SUCCESS marker or from successful individual features.

### Combined executable coverage

The unchanged feature tests were executed against the seven-patch combined engine,
not merely reused as six separate historical green badges. Linux used independently
identified buffered and splice objects; Darwin used buffered objects. Each of the
three modes passed 58 mandatory UDP profile cases, eight peer/queued-continuation
cases and 20 statistics network executions. Counter stress, partial/error/retry I/O,
ASan/UBSan, Darwin counter TSan, exact formatting and reverse-patch checks passed.
The eight-writer/800000-update input is synthetic counter stress, not a claim of
that many independent device tests or petabytes transferred over a real network.

Real controller/engine and JSON/store/controller/engine tests passed in each mode:
14 controller comparison records, 12 active-client cases, 16 delayed-completion
old/current records, 16 persistence records and four delayed-persistence records.
Expected old-code failures remain negative controls, not current-version failures.
The retained model suites passed: seven server scenarios, 84 revalidation assertions,
512 option/YAML parity cases, 209 settings assertions, 1193 Background assertions
and 10000 generated statistics samples. Apple-only checks included 34 real Combine
deliveries and cancellation, five real Timer/RunLoop cases and 400 decoded zero WAV
samples. Exact icon integrity and all 13 mutation methods, including 30728 single-bit
mutations, passed. These counts contain repetitions and controlled boundaries.

All 12 production Swift files passed the actual iPhoneOS 27 ARM64 typecheck at the
configured iOS17.2 minimum, with warnings-as-errors and an empty compiler diagnostic
log. The ARM64 iPhoneOS app was also built and archived; this is separate from type
checking and the Simulator product. The archive/package checks verified the stats
and prepare definitions, app/dSYM UUID pairing, icons, original WAV, permissions,
absence of app extensions and IPA/source correspondence. No installer signing or
physical-device permission is inferred from those checks.

The preseeded Simulator harness passed ten original/remapped identity cases covering
saved tabs, saved Start/relaunch with real TCP payload echo, and saved Stop. A separate
actual XCTest passed one test with zero failures in 115.257 seconds. It scrolled and
tapped Start/Stop in portrait/landscape, checked real SOCKS greetings, restored Start
in a new process, visited Statistics, toggled and restored saved audio intent, turned
it Off, and restored the Settings tab with saved Stop. Six complete screen attachments
were inspected. Both Simulator cleanup records are empty, and xcodebuild returned
success before the unchanged 900-second limit. Exported final JSON has server Stop,
audio Off and location Off. Audio intent restoration is not proof of background
survival, uninterrupted playback or physical phone/Bluetooth events. Import/export
button presence is not a test of every native file-provider UI operation.

### Failures, corrective scope and remaining advisory

Run `36076700939` failed the first actual UI audio assertion: the test tapped a
labeled outer SwiftUI row, not its separate actionable switch. The captured hierarchy
and subsequent source review identified this test-selection error. Commit
`0281aa9bc742eb089e8861da739b0112627fc2d2` selects the descendant switch and also
requires it to be hittable, retaining value, relaunch, Off and native assertions.
No production controller, layout or audio setting changed.

Run `36079054645` did not complete the whole workflow. In its inspected attempt 2,
the corrected test reported zero failures in 102.337 seconds, but xcodebuild remained
in asynchronous diagnostic finalization after the test runner exited and exceeded
the 900-second command limit. That is retained as a failed workflow, not promoted to
a completed UI result. The precise lower-level diagnostic stall cause is unproven.
The final commit adds `-collect-test-diagnostics never` only to this test invocation
to avoid optional bulk system diagnostics. It does not disable test assertions,
runtime issue reporting, screenshots, xcresult verdicts, exit checking or cleanup.
It reduces verbose sysdiagnose/log-archive collection; that evidence trade-off is
explicit. The previous failure evidence and supplied screenshots remain historical.

The successful result still contains an AVAudioSession runtime warning that its
synchronous activate/deactivate path can cause UI unresponsiveness on the main thread
and suggests the asynchronous API. This is an observed performance advisory, not a
silenced message and not proof of a crash. Actual taps completed, but absence of all
main-thread stalls or smooth interaction in every environment is NOT established.
The exact Background owner is retained instead of introducing a release-only
asynchronous state machine that would change Off/retry/re-entry ordering without
separate validation. This advisory remains a known limitation of this release.
AppIntents and Simulator/debugger diagnostics are likewise retained in the logs.
This is not a completely warning-free execution or a universal no-defect certificate.

### Inspected source and deliverable identity

Both downloaded original artifact ZIPs passed integrity and digest checks. Their
154-file Git source archives reconstruct the tested tree, including executable modes,
and all 154 recorded source hashes match. The build-source and independently recorded
source ZIPs agree. All 97 membership entries match their exact owner bytes, modes
and hashes. The six pinned feature heads are actual ancestors through integration
commit `271c1ea75cccbd0302ee0caaf61293a0199439e5`, whose parents include the old
release and all six owners; the later test corrections retain that ancestry.

- Linux artifact `10842436334`: `4ac09c2af1899c6f97291fbccaf219c317c408b8d58439c9313d2162275e2379`.
- macOS artifact `10843236261`: `4cb65fff159df58d9d253f6df1973c713cac66052cf3fc320616e54e090617cf`.
- Unsigned 1.1.0/build 7 IPA: `a420c24e35b7e05a41788b7f667bb3861d4ad71cbdfd27be35413412a3598c80`.
- ARM64 app/dSYM UUID: `DBD0D43E-98D6-331F-9FA7-C2AB5A570FEF`.

The IPA is the exact output from tested commit 8982c264, not rebuilt from this later
completion text. Independent ZIP/plist/Mach-O/dSYM inspection confirmed ARM64,
iPhoneOS platform, SDK27.0, minimum17.2, version1.1.0/build7, no signature load command,
matching UUID and both stats/prepare symbol definitions. Signing/import will change
package bytes; this hash identifies the distributed unsigned input, not a user's
subsequently signed copy. Source framework bytes remain the committed baseline;
the compiled patched framework belongs to the generated build, not a silent source
replacement.

Actual environment: Xcode27.0 `27A266a`, iPhoneOS SDK27.0, Apple Swift6.4
(`swiftlang-6.4.0.34.1`), macOS27.0 `26A428`, iPhone16 Simulator with iOS27.0
`24A434`. Physical SideStore independent installation, LiveContainer guest loading,
installer/host versions, lock-screen execution, real interruptions, VPN/hotspot,
protected-data and energy remain unperformed. Configured minimum, intended support,
build environment and actual executed environment are deliberately not conflated.

### Documentation completion without changing the tested product

The resumed review found five dated UDP/statistics review files referenced by the
preserved feature specifications but absent from the release tree. They are restored
byte-for-byte at their original paths from the same pinned owners. The two UDP
reviews come from 66e7196e; the two statistics reviews and alignment review come from
24d5fdeb. This repairs traceability, not runtime behavior. The 97-entry membership
and all build/test inputs remain unchanged; the five supplemental document blobs
are independently checked against those owner trees:

| Restored review | Git blob |
| --- | --- |
| `docs/reviews/udp-compat-20260922.md` | `a769d33197ca2c07f8e56eeb66f03b5bd1378f3b` |
| `docs/reviews/udp-compat-20260923.md` | `c49c505f32fe30fef1e2fcabc685bae23c4a5c25` |
| `docs/reviews/traffic-statistics-20260922.md` | `07f767f6e26c54abfd908f5fa92ba56af803d99c` |
| `docs/reviews/traffic-statistics-20260923.md` | `1cca8306c54ca40a74823eae9d367bb63c69c814` |
| `docs/reviews/udp-statistics-alignment-20260923.md` | `a78283e2bc42c094fc9a57f17d7308e05d5cd36b` |

An old `settings-lifecycle.md` path appears only inside the verbatim pre-split history;
it describes that historical commit, not a new current feature or a reason to
restore the removed mixed-responsibility branch. Current ownership remains server
control plus downstream persistence. Native fixed-port/unknown-client observation
failures remain outside the required profiles under the accepted port-zero policy.
No full protocol/security or all-network deployment certification is claimed.

This completion changes only README, its identical integrated specification and
those five historical document files: 159 source files in the final tree versus
154 in the tested tree. Every production, test, workflow, manifest and source pin
remains byte-identical to the successful run. The final tree is separately recorded
and is not misrepresented as the original 154-file CI checkout. Main, all six feature
heads, the eight-branch count and the old build6 artifact remain untouched. No new
runtime cost is introduced by these documentation changes.
