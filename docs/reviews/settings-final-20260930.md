# Settings persistence final review — 2026-09-30

## Source, ownership and scope

Start from settings472ef5a3ec5626539e4649341d9b7d1bc4a57a9f and inherit completed
server368aa4cf89436651414a8885a2a171f5cff9abd5 as a real merge parent. Main remains
75335d201cb1e541bb153e9899badbc11ccf1973. The manifest tracks32 exact server-owned
files, including final transition/native tests and historical/current server review.
The existing settings-specific build stages and all negative controls are retained.
Only test/build wiring, dependency metadata and documents change; all8 production
Swift files, native patch, schema/defaults, project/plist/assets/framework and pins
are preserved. The preceding complete README is copied without change to history.

Read the entire model, store, view/root, inherited settings/controller/editor and
native prepare/Stop patch. No new production defect was reproduced. Keep the small
existing store rather than add a writer thread, retry timer, cache, host workaround
or a second service controller. This does not claim every possible input or operating
system state has been proved safe.

## Additional tests and observed local results

FinalPersistenceTests uses real Foundation files and actual AppSettings/SettingsStore.
625 assertions cover regular-file imports at the exact65536 limit and rejection at
65537, missing/null/schema/root/trailing-data failures with byte-for-byte preservation,
unknown-key behavior, all11 fields and four tabs,256 complete mixed import/recreation
cycles, stopped invalid drafts, and20000 no-op setters/bindings. Those no-op requests
retain exact bytes, modification time and inode; elapsed time is recorded only as a
host observation, not device performance. On Apple this suite uses actual Foundation
NSFileCoordinator. Linux lacks that API and uses the existing immediate provider shim.

FinalCoordination adds55 assertions with bounded, explicitly controlled OS boundaries:
redirected accessor URL, balanced original-URL security-scope acquisition/release,
no-accessor, coordinator/read errors, false scope access on an otherwise readable file,
pre-cancellation and8 overlapping-newer-action cases. Store revision/cancellation/
decode/commit bodies remain exact; only the two URL security-scope member names are
redirected to counted fixture methods. Provider coordination is substituted just as
in the existing import fixture. Actual files and MainActor application remain real.
These are not tests of a real remote provider or physical sandbox authorization.

Existing209 current assertions passed locally before changes and again alongside
625+55 new assertions. The first new fixture compilation failed because Swift's
short-circuit expression required try on the complete expression, not only its RHS.
The test expression was corrected; no production or warning rule changed. The new
complete local suite passes. Real store/controller/Hev16 records, final server18
records at workers1/4/64, and12 active-client cases also passed locally. The native
input came from an authenticated prior CI archive; its source is not fabricated Git
history, and local version lookup warnings do not replace full-history CI.

## Simulator verification design

The latest server owner's temporary test-target builder is reused. Only the generated
test-target names/source are changed in the disposable product; no test target or
injected environment switch is added to production. Same-HEAD native/SDK success and
unchanged production guards precede the Simulator-only native rebuild. The entire
originally declared patch is reapplied and reversed with cleanup recorded on failure.

One new XCTest drives the real persistence root. It changes workers to0, requests
Start, relaunches and confirms the persisted invalid intent cannot listen, then
stops and changes workers to2. In portrait and landscape, Start and the Settings tab
are saved, the app process is relaunched and both actual IPv4/IPv6 SOCKS greetings
must return. Stop releases both listeners. Import/export sheet cancellation is checked;
a final relaunch keeps Settings selected with the server stopped. The host runner
reads the actual app-container JSON, compares every field and requires settings.json
alone in its owned directory. No network/provider/UI values are mocked.

## Initial evidence requirements (historical)

Fresh Linux and Xcode27 CI, same-source8-file SDK checks, actual Simulator results,
source archives and original artifact digests remain required before final closure.
At that checkpoint the original assertion, timeout, compiler and source rules were
retained. The later system-dialog observation change is explicitly documented below. Physical SideStore standalone,
LiveContainer guest, actual external provider/protection, background, power-loss,
device memory/energy and iPhone IPA/release integration are not performed here.


## Executed closure — 2026-09-30

Final tested source is `6a3d23029c7bcf6d0eeaf2f36f8088f6138ccdaf`, tree
`f53c01bb64f07060be4633baab7afa75275b4e45`. Run `36638749884`, attempt 1, passed
both native hosts and the Apple SDK/actual persistence Simulator path. Terminal run
metadata was updated at 2026-09-29T22:31:07Z. This final run is separate from all the
failed attempts below; a documentation-only follow-up is not another execution.

The merge d56dbe8bc1bf808c0b9c8c598c903d9ad67b1f10 has actual parents settings
472ef5a3 and server 368aa4cf. Subsequent changes are test-only. The resume examined
all eight production Swift sources and the import/decode/write/root/controller
interaction. No additional production defect was reproduced. The final CI's exact
32-file inherited ownership check and the unchanged production source guard pass.
Other feature branches, one-way responsibility and default settings remain unchanged.

### Results and resource scope

Both hosts pass 889 current persistence assertions: the original 209, the new 625
file/model assertions, and 55 controlled coordination assertions. The real-file
cases cover all server fields and four portable tabs, boundary/invalid JSON, byte-
sensitive credentials, missing/inaccessible/corrupt files, failed migration retry,
transactional imports and no-op writes. The coordination fixture changes OS outcomes,
not store bodies; scope balance, redirected accessor URLs, cancellation and eight
newer-intent cases are exercised. It is not a cloud-provider integration certificate.

All inherited server suites remain: seven scenarios, 84 revalidation assertions,
1,250 finite four-intent schedules/25,544 assertions, 512 configuration/YAML parity
cases, 22 required old-equality failures, original native records, active Stop and
pre-start/legacy/prepared cancellation. The composed real-file/controller/native
driver reports 16 records, additional server boundary driver 18 at workers 1/4/64,
and active-client driver 12. Counts include repeats and negative controls, not that
many physical-device tests. All source/marker/header, main ancestry/pin, formatter18,
entry/final worktree/index and exact native reversal checks remain required.

All eight production Swift files pass the same-HEAD native-header iPhoneOS27 SDK
ARM64/iOS17.2 check, with a zero-byte compiler diagnostic log. Xcode's recorded version
is 27.0, build 27A266a. The test summary identifies iPhone16, iOS27.0/24A434, arm64
Simulator, built with macOS27.0; no absent tool version is inferred from another run.
AppIntents metadata-extraction notices remain in the UI build log. Standalone server-
control UI was skipped in this settings composition; the settings-specific test ran.

The actual persistence XCTest passes one case, zero failures/skips, in 158.123 seconds;
runtimeWarnings=[] and cleanup=[]. It exercises invalid workers0 saved intent across
restart, cancellable invalid Start, workers2 and saved running/stopped state with real
IPv4/IPv6 SOCKS greetings in portrait and landscape. It verifies the old process no
longer answers before crediting restored Start. Repeated imports/exports are opened
and dismissed through real controls/gestures; final process restart keeps Settings
selected and the server stopped. Ten original screenshots and the exact saved JSON
are retained. The case does not perform an external provider's save/read transfer.

The final Application Support/Socks5 directory has only settings.json. Its 485 bytes
contain version1, workers2, serverRunning=false, selectedTab=settings and unchanged
other defaults; the entire snapshot is compared, not just a subset of fields.
SHA-256: 67e8bc53e6d3079b97b3683fcf55fa92d2d152d9cbef2ec657ae7f8e23553118.
Physical data-protection state is explicitly untested, despite the unchanged iOS
write-option request. Atomic replacement is not a claim of power-loss durability.

No production allocation, timer, loop, socket operation, thread, permission or
persistence schema changed. The existing bounded 65,537-byte read detects the 65,536
JSON limit; encoding/write occurs only on changes or explicit pending-save retries.
Clean no-op requests retain bytes, modification time and inode in the tests. The
local 20,000-call observation was 0.119705 seconds of wall time, not device CPU cost,
RAM footprint, peak cost or a throughput guarantee. No synthetic benchmark speedup
is inferred from unchanged application code. Slow storage/provider blocking remains
an explicit cost. A detached synchronous coordination already underway is not forcibly
cancelled, and multiple user imports can temporarily retain multiple such tasks.

### UI failures, test corrections and the changed observation bound

The original new UI test made two assumptions that were not valid for the observed
system document interface: it required Export to expose a Cancel Button, and it
used existence at 10 seconds as sufficient readiness. The actual Export page has
Save and its filename field; a non-Button Cancel accessibility node is not a visible
cancel button. The import picker can initially expose only its empty Files surface.

The final test checks Import's actual Cancel and Export's actual Save/filename, waits
for exists AND hittable, then cancels Import by its control and Export by dragging
its navigation bar to dismiss the real sheet. Both dialogs are reopened and must
disappear while saved Stop remains. This adds no production diagnostic or workaround.
It does not choose a file, force-close the app for success, install a mock provider,
retap a failed button, warm caches, or alter OS permissions/host state.

The newly added external-dialog presentation check now has one total 60-second
functional observation budget measured from the original tap. This is an explicit
change from its initial 10-second requirement, not an unchanged-gate claim. The first
10-second outcome is retained separately. Native/restore/dismissal checks remain at
5 seconds and the outer runner at 900 seconds. The final Import first becomes
hittable at 12.718289 seconds and initial10s=false. Export1 is 5.962281 seconds,
Import2 4.408139 seconds, Export2 4.727287 seconds, all with initial10s=true. Thus the
functional current suite passed, but the first Import did not satisfy the old 10s
observation. Neither threshold is a device performance or hard real-time guarantee.

| Source/run | Recorded unsuccessful result |
| --- | --- |
| d56dbe8b / 36618355354 | Saved-Start check missed its deadline on the second running relaunch; case failed at 181.092s. Subsequent identical-production runs passed this path; the first root cause is not established. |
| 466e4a26 / 36621531352 attempt1 | Simulator setup failed before case execution; read-container and shutdown/delete diagnostics also timed out. No UI success is inferred. |
| Same / attempt2 | Import Cancel lookup failed; case 114.972s, earlier restored Start/Stop passed. |
| Same / attempt3 | Import Cancel lookup failed; case 182.389s, earlier restored Start/Stop passed. |
| 072a0ac8 / 36633455310 | Import cancellation passed, Export wrong-class Cancel lookup still failed after experimental 60s. Actual Save/filename were visible; case 190.846s. |
| d07fa5ca / 36636208781 | After fixing Export control selection and restoring 10s, Import was not actionable; empty Files surface in recording, case 118.649s. |

All six original macOS ZIPs were downloaded, matched to GitHub SHA-256 metadata and
CRC checked. Their failure logs/recordings and snapshots were inspected and kept.
Later Xcode diagnostic collection/900-second runner timeouts are distinct from the
initial assertion times. No prior failed source is relabeled as a passing source.
The final source 6a3d2302 combines the actual-control fix with actionability waiting;
it passes under the explicitly documented functional contract. A single green run
is not proof that OS/provider startup can never delay or fail again.

### Supplemental execution, negative controls and exact correspondence

The resume rebuilt the authenticated native source locally and reran the 889 store
assertions, the 16-record persistence/native path, 18 server records and 12 active-
client cases. Three disposable source mutations each fail their unchanged assertion:
allow stale import to override newer intent, let save failure block Stop, and remove
the clean no-op write guard. None is committed. Local archive-based execution does
not supply missing historical Git objects or an Apple runtime; the snapshot version
lookup's not-a-repository diagnostic and connectivity failure are retained.

| Original successful artifact | SHA-256 |
| --- | --- |
| Linux 11064924378 | 36aef9c1b661b5e5be7015b1c54ffb4c6e32ad9d2e8f23816ff07ba549dd4fba |
| macOS 11066740409 | f08952ac3533f7d450e8cf323857f321399dac525aa5fbeae78e3faea86eab80 |

Both original digests/CRCs, full source manifests and native-header revision identities
match. Linux native, Apple native and Simulator source archives contain identical
102 files/modes, all with the tested SHA; independently reconstructed tree=f53c01bb.
The final native archive has 243 regular files and 30 symbolic-link targets. Native
reverse/reapply restores their exact source. The original eight production files,
single patch, schema, project/plist/resources/framework and pins are unchanged.

This closure publishes README, its identical feature specification and this review
only. The other 99 tested paths are unchanged. Its direct parent is the tested
6a3d2302; Git metadata identifies its final commit/tree. It is a documentation-only
commit, not a new CI execution. No failing required case remains in the executed
current functional suite. The initial 10-second dialog observation, historical
failures and unestablished causes remain visible rather than being deleted.

Physical iOS27 SideStore standalone and LiveContainer guest installation/execution,
Files/iCloud provider transfer and security scope, first-unlock protection, real
background/suspension, crash/power-loss, shared-process arbitration, device resource/
energy limits and a release IPA remain separate unperformed layers. No finite test
suite proves all arbitrary scheduler, storage and OS histories to be defect-free.
