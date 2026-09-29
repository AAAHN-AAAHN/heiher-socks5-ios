# Persistent settings — final review

## Review checkpoint — 2026-09-30

This review starts at settings `472ef5a3ec5626539e4649341d9b7d1bc4a57a9f` and
inherits completed server-control `368aa4cf89436651414a8885a2a171f5cff9abd5` as
an actual merge parent. Main remains `75335d201cb1e541bb153e9899badbc11ccf1973`.
All 32 mapped server-owned source, test and document files are exact owner bytes.
The complete preceding README is preserved at
`docs/history/settings-before-final-review-20260930.md`. Earlier reports and negative
control references describe their own revisions, not this new execution.

No production change has been required by this review. All eight Swift files,
schema, defaults, project/plist, native prepare/Stop patch, baseline framework and
source pins remain identical to the starting settings owner. The latest controller
verification is inherited; additional file/provider-boundary and actual Simulator
persistence checks are included. Fresh CI and original artifacts must be inspected
before this checkpoint is closed. README and the feature specification are identical.

## Target environment and ownership

The primary target is a physical iOS 27 iPhone, installed independently with SideStore
or running as a LiveContainer guest. These are distinct signing, container, identity,
file-protection, provider and shared-process environments. A successful native host,
iOS SDK or Simulator test does not certify either physical installation path.
The configured minimum is iOS 17.2, not proof of execution on every intervening OS.
The four original instructions remain unchanged in `docs/top-level-principles.md`.

Ownership is one way: main -> server-control -> settings-persistence. One root-owned
SettingsStore supplies bindings and intent to one MainActor ServerController.
ServerSettings, ServerController and ContentView never read JSON or own persistence.
There is one independent native engine per process; a LiveContainer host's process
arbitration is not implemented or overridden here. No UDP/statistics, Background or
custom icon feature is merged. Background preferences are portable data only here.

The standalone screen contains Server and Settings tabs. Portable statistics or
background tab values render as Server without rewriting the stored value simply
for display. The full four-case tab enum remains for downstream integration. The
standalone server owner starts stopped, whereas this persistence root reapplies
saved Start intent when the app actually executes. Saved intent is not automatic
process relaunch, background permission or confirmed native listen readiness.

## Complete configuration and validation

Schema 1 includes the eleven ServerSettings options, serverRunning, continuousLocation,
silentAudio and selectedTab. Defaults remain workers4, TCP address::/port1080, empty
UDP address/port1080, bind IPv4 0.0.0.0, bind IPv6 ::, empty bind interface and both
credentials, IPv6-only false; serverRunning and both Background switches are false,
and the portable selectedTab default is statistics.

Workers must be 1-64, TCP port 1-65535 and UDP port 0-65535. Seven text options must
be single-line/control-free and at most 255 UTF-8 bytes. Authentication is both empty
or both supplied; YAML quote escaping and byte-sensitive string equality are retained.
Canonically equivalent strings with different credential bytes are not equal.
A stopped invalid draft can be saved and restored, but validation prevents starting
it. Import requires a complete executable server configuration before any commit.
Unsupported schema version, missing required values and invalid required types fail.
Unknown keys are ignored within schema 1, not a promise of future-schema migration.

## Storage, errors and costs

The sole persistent file is Application Support/Socks5/settings.json. JSON is sorted
and pretty-printed; decoding and output are bounded to 65,536 bytes. The read requests
at most 65,537 bytes to detect oversize input. Writes use atomic replacement and,
on iOS, completeFileProtectionUntilFirstUserAuthentication. These APIs do not guarantee
power-loss durability, secure deletion, a fixed physical memory footprint or separate
credential encryption. JSON and exports contain plaintext authentication; keep them
private and import trusted files. No extra keychain or encryption policy is introduced.

Only explicit file absence triggers migration of the two legacy Background keys.
A denied, corrupt or unknown existing file leaves the original untouched and reports
an error without restoring legacy On. Legacy keys are removed only after a successful
new write, including an explicit later retry. Existing JSON never triggers migration.

A setter supersedes pending imports even when the requested Stop is unchanged.
Equal clean values do not write. Failed explicit writes preserve savePending and a
visible error but still publish the live choice: storage failure cannot prevent
Stop/Off. The same choice can explicitly retry the pending save. Until successful,
disk can retain old Start/On intent; this is visible and not silently called durable.
An unchanged clean choice after load failure does not authorize overwriting the source.
Export uses current in-memory values, potentially different from disk after failure.

The store has no packet-related operations, polling, save timer, debounce, background
writer, redundant serialized cache or unbounded packet history. Small synchronous
startup reads/writes and equality comparisons still consume resources and may block
on slow storage. This review adds test work, not runtime CPU/RAM work. Repeated no-op
sets are checked against exact bytes, modification time and inode; host elapsed times
are observations, not an iPhone energy or worst-case latency guarantee.

## Import ordering and provider boundaries

ImportData decodes and validates everything, then writes the complete file before
publishing live values. A failed import does not partially replace either snapshot.
ImportFile coordinates on a detached worker, reads the accessor URL supplied by
NSFileCoordinator and balances acquired security scope using defer. Cancellation and
an import revision are checked before application. Stop, a changed or unchanged set,
a direct import, or a newer file import supersedes an older blocked result.

A provider already blocked inside synchronous OS coordination cannot be forcibly
stopped by discarding its result. Overlapping user imports may keep their workers
alive until the provider returns; this is not per-packet work or a background-service
promise. Changing host/cache/permissions or adding a new scheduler is not justified
by these tests. The actual Files/iCloud picker and protection behavior on a physical
device are distinct from regular-file and controlled-provider checks.

The root applies restored/imported intent through the existing controller. Replacing
configuration or stopping asks the previous engine to quit once; a replacement waits
for native return and MainActor completion. Repeated identical intent does not create
parallel engines or retry a failed start indefinitely; explicit Start can retry.

## Verification and reproduction

Use a clean full-history checkout. Run `BUILD_IPA=0 bash Build/build.sh`, then on
Xcode 27 `bash Build/check_swift_sdk.sh` and `python3 Tests/Settings/ui_audit.py`.
`python3 Build/record_evidence.py` records the tested source. The workflow performs
these stages with original source/index/pin/ownership, formatter18, old failure and
same-HEAD header guards. A source ZIP cannot replace the historical Git objects.
The optional generic archive/IPA path is not invoked by this review.

All original 209 store assertions and exact-old import/save/access failures remain.
All inherited server cases run on this composition, including the final transition
matrix and actual native workers1/4/64 driver; they are not borrowed success badges.
Additional tests cover exact 65,536/65,537-byte inputs, full field reconstruction,
256 mixed roundtrips, 20,000 no-op requests, coordinated accessor remapping, security
scope balance, provider errors, cancellation and eight newer-intent races. Boundary
fixtures redirect OS outcomes only; store/decoder/write bodies and files remain real.
The native integration still checks real authenticated listeners, relaunch, failed
save Stop and explicit retry, plus delayed completion.

The settings-specific Simulator target is generated only in a disposable product
using the completed server owner's target builder. The tracked project and framework
are never overwritten. Tests use the actual app root, file and patched native engine,
not injected runtime settings: invalid draft relaunch, saved Start auto-application,
saved Stop, tab/field persistence and dual-stack replies in both orientations.
Import/export sheets are opened and cancelled; this is not an iCloud file-transfer
claim. The runner also verifies the final full JSON and absence of leftover files.
Exact results, source identities, diagnostics and artifacts are recorded in
`docs/reviews/settings-final-20260930.md` after execution.

## Deployment and remaining boundaries

No new IPA, release integration or physical SideStore/LiveContainer execution is
claimed. Physical signing/loading, Files/iCloud security scope, file-protection timing,
lock/suspension, crash/power-loss durability, long-running behavior, shared-process
signal state and device CPU/RAM/energy remain separate evidence levels. The committed
unpatched framework does not contain the native prepare symbol: a product must rebuild
the declared patch before linking. Other feature owners and release are not advanced.

Apple API references describe contracts, not results of this revision:
- https://developer.apple.com/documentation/foundation/nsfilecoordinator/coordinate(readingitemat:options:error:byaccessor:)
- https://developer.apple.com/documentation/foundation/nsdata/writingoptions/atomic
- https://developer.apple.com/documentation/foundation/nsdata/writingoptions/completefileprotectionuntilfirstuserauthentication
