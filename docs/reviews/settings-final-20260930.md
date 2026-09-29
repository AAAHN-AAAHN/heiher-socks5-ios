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

## Evidence pending before closure

Fresh Linux and Xcode27 CI, same-source8-file SDK checks, actual Simulator results,
source archives and original artifact digests remain required before final closure.
Old executions remain historical; no assertion, existing timeout, compiler flag,
source gate or failure condition has been weakened. Physical SideStore standalone,
LiveContainer guest, actual external provider/protection, background, power-loss,
device memory/energy and iPhone IPA/release integration are not performed here.
