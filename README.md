# Persistent settings — final review

## Completed review — 2026-09-30

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
persistence checks are included. Run 36638749884, attempt 1, passed both Linux and
Xcode 27 at source 6a3d23029c7bcf6d0eeaf2f36f8088f6138ccdaf. The actual Simulator
case passed in 158.123 seconds. Final evidence and the changed system-dialog test
budget are recorded below. README and the feature specification are identical.

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
Import/export sheets are opened, dismissed and reopened. Import uses its visible
Cancel control; export uses its actual Save page and interactive sheet dismissal.
Presentation requires an actionable control, not only an accessibility placeholder.
The first 10-second observation is recorded separately; only the newly added system
file-dialog presentation test has a 60-second total functional observation budget.
The original 5-second service/restoration/dismissal checks and 900-second runner
remain unchanged. This is not a 10-second performance guarantee or a provider transfer
claim. The runner also verifies the final full JSON and absence of leftover files.
Exact results, source identities, diagnostics and artifacts are recorded in
`docs/reviews/settings-final-20260930.md`.

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

## Final executed evidence

Tested source: `6a3d23029c7bcf6d0eeaf2f36f8088f6138ccdaf`, tree
`f53c01bb64f07060be4633baab7afa75275b4e45`, 102 tracked files.
Run `36638749884`, attempt 1, completed successfully at 2026-09-29T22:31:07Z.
Linux and Xcode 27 native jobs both passed; Apple also passed same-source iOS SDK
checking and the settings-specific Simulator suite. The separate standalone-server
UI step was intentionally skipped, not counted as a settings-composition execution.
No iPhone archive or IPA was generated.

| Verification layer | Actual result |
| --- | --- |
| Store and schema | 889 current assertions per host: 209 retained plus 625 file/model and 55 coordination-boundary assertions. These include 65,536/65,537-byte limits, all fields/tabs, invalid input, 256 mixed roundtrips and 20,000 no-op setters without changing file bytes, mtime or inode. |
| Import ordering | Actual store and regular files with controlled OS coordination/scope outcomes verify redirected accessor URLs, balanced access, cancellation and newer-intent protection. These fixtures are not external cloud-provider or physical security-scope trials. |
| Native integration | 16 actual file/store/controller/Hev records, 18 additional server records at workers 1/4/64 and 12 active-client cases pass; original authentication, delayed completion, initial cancellation and old-failure controls remain. |
| Controller and source | Seven scenarios, 84 assertions, 1,250 finite transition schedules/25,544 assertions, 512 configuration/YAML parity cases and required historical failures pass. The 32 inherited owner mappings, ancestry, pins, formatter18, clean index/worktree and exact native reversal pass. |
| Apple SDK | All eight production Swift files pass ARM64/iOS17.2 typechecking against same-HEAD native headers. Required SDK diagnostics are empty. Actual recorded Xcode is 27.0 (27A266a), iPhoneOS SDK 27.0. |
| Actual Simulator | One iPhone 16 / iOS 27.0 test passes, zero failures/skips, case 158.123 seconds; runtimeWarnings and cleanup are empty. Invalid draft, saved Start/Stop, both orientation paths, tab/field restoration and real dual-stack SOCKS replies are verified. |
| Actual stored file | 485-byte JSON exactly matches the expected full snapshot: workers 2, stopped, selected Settings, unchanged other defaults. The owned configuration directory contains only settings.json. This is not the full application's filesystem inventory. |
| Dialogs | Import and export open, dismiss and reopen twice without restarting services. The exporter filename is Socks5-settings. No file is selected from or written through an external provider by this UI test. |

Observed actionable-dialog times from the original button tap were 12.718289 seconds
(first Import), 5.962281 (first Export), 4.408139 (second Import), and 4.727287 (second
Export). The first Import did not meet the earlier 10-second observation. Its success
under the explicitly declared functional budget is not relabeled as a 10-second pass.
No second tap, cache warming, injected provider, host repair or product timeout was
used. The initial budget flags are observations, not hard real-time guarantees.

The earlier review attempts remain failures: an initial saved-Start deadline, a
Simulator setup/cleanup timeout, several incomplete Files presentations and an
incorrect Export Cancel-button assumption. Native/SDK successes in those attempts
do not make their UI results successful. Subsequent runs of identical production
passed saved Start, but do not establish a root cause for the first missed deadline.
The final test locates actual Import/Export controls, waits for actionability, and
requires genuine dismissal. Detailed source/run/diagnostic history is in the review.

| Original successful artifact | SHA-256 |
| --- | --- |
| Linux 11064924378 | 36aef9c1b661b5e5be7015b1c54ffb4c6e32ad9d2e8f23816ff07ba549dd4fba |
| macOS 11066740409 | f08952ac3533f7d450e8cf323857f321399dac525aa5fbeae78e3faea86eab80 |

Both original ZIP digests/CRCs and all three native/UI source archives were checked.
They contain the same 102 bytes-and-mode entries and reconstruct the tested tree.
The complete source manifests, native header identities, ten original screenshots
and exact 485-byte JSON were inspected. Its SHA-256 is
`67e8bc53e6d3079b97b3683fcf55fa92d2d152d9cbef2ec657ae7f8e23553118`.
Required compiler diagnostics are empty; retained AppIntents metadata notices have a
different scope and are not silently removed.

Supplemental archive-based Linux runs repeated the 889 assertions, actual native
integration and active-client checks. Three disposable mutations (stale import wins,
failed save blocks Stop, no-op writes) each fail the original checks. The native patch
reverse/reapply restores all 243 regular source files and 30 symlink targets. These
are supplemental results, not additional Apple CI or physical-device executions.

This closure changes only README, its identical feature specification and the dated
review. All other 99 of 102 paths retain the tested bytes and Git modes. Its parent
and Git tree identify the publication, not a new runtime test. All eight production
Swift files and the native patch remain unchanged from settings owner 472ef5a3.
There is no additional app CPU/RAM work from these test/document-only repairs; the
original storage and OS/provider costs and physical-deployment limits remain above.
No other branch, release, schema, default, permission, host or runtime is modified.
