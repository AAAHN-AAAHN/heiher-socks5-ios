# Server-control final review — 2026-09-29

## Scope and invariant inputs

Starting owner: be4bdd14d46b6bcd35dfad0c4923edda771c6ac6. Main remains the actual
75335d201cb1e541bb153e9899badbc11ccf1973 ancestor. All five production Swift files,
eleven settings/defaults and byte-sensitive equality, public interfaces, native
prepare/Stop patch, project/plist/resources, baseline framework and source pins
remain byte-identical. No UDP, statistics, persistence, Background or icon merge.
No new production allocation, copy, timer, polling, thread, log or socket call.
The existing root-owned MainActor controller and blocking native dispatch remain.

The review covers validation/YAML, stopped/desired/current/attempted ownership,
Stop coalescing, delayed native completion, latest-intent replacement, explicit
retry, lifetime retention/release, native pre-start cancellation and active-client
termination. No new runtime defect has been reproduced. Tests are strengthened
rather than inventing a refactor to imply progress. Historical standalone native
signal/process limits remain; one independent engine per process is the contract.

## New complementary verification

TransitionMatrix executes the actual controller with a held dispatch/engine-return
boundary and real MainActor completion. Every four-command suffix from five intents
(same, explicit same retry, changed, invalid, Stop) runs with two native return codes:
1250 schedules, plus five return-before-actor-delivery schedules and a weak-owner
lifetime check. 25544 assertions check no overlapping dispatch, one prepare/quit,
latest valid configuration, invalid/exited no-retry, Stop authority and owner release.
These controlled schedules are not native network or parallel-actor trials.

The additional real Swift/Hev host uses workers1/4/64. Eighteen records cover an
actually occupied port, unchanged-intent suppression after releasing the port,
explicit retry, quoted UTF-8 authentication, 100 no-op retries retaining a live
session, invalid replacement shutdown, clearing authentication and 100 stopped
invalid intents. Existing fourteen native records, 12 active-client cases, delayed
schedules, YAML parity and historical regression controls remain mandatory.

The new Simulator runner reuses this repository's isolated test-target construction
pattern. It requires native and SDK success at the same HEAD; verifies unchanged
production inputs; reapplies the declared patch to the exact temporary native tree;
builds a Simulator-only framework; and adds XCTest only to a disposable app copy.
The tracked framework/project never changes. XCTest exercises all eleven controls,
invalid workers/Start/Stop, actual dual-stack SOCKS greetings, disabled editor state,
portrait/landscape reachability and stopped default restoration after process restart.
It uses real application state, not mock controller values. The runner records
source, native source, binary hashes, XCTest results, screenshots and cleanup.
It does not build an iPhone archive or IPA.

## Local checkpoint before CI (historical)

Prior run36225969482 artifacts10900532603/10901051463 match their GitHub SHA256
and ZIP CRC. Their actual source archive is reconstructed and the current owner
README/history restored; the 72-file before tree is81d0e5c670eb3c49839feef214cb0cc307ba5082.
The runtime has no direct github.com DNS access. Local native input was therefore
restored by reversing the seven exact patches from authenticated statistics source,
then applying only this owner's one patch. This is not an invented Git history.
Local current Swift scenarios, 84 assertions, transition matrix, 18 native records
and 12 active-client cases pass. Full old-history/formatter18 and Apple checks still
require the connected CI. No existing assertion, deadline or warning gate is relaxed.

## Original completion criteria and deployment boundaries

Fresh Linux and Xcode jobs, same-source SDK, actual Simulator results and artifact
identity must be inspected before closure. The application has no added runtime
work from these test-only changes, but the original server/UI and OS still consume
resources; no measured CPU/RAM/energy improvement is claimed.

The configured minimum remains iOS17.2; the intended environment is physical iOS27,
with SideStore standalone and LiveContainer guest treated separately. SDK/native/
Simulator evidence does not establish signing, permissions, shared-process/host
arbitration, actual background survival, lock/suspension, power-loss or device energy.
No host, entitlement, cache, background API, release or other branch is modified.
A successful finite suite is not proof over every OS/scheduler/input history.


## Exact-source completion — 2026-09-30

The interrupted review is now closed. Run36574631457, attempt1, completed with both
Linux and Xcode27 jobs successful; terminal run metadata was updated at
2026-09-29T13:31:43Z. The tested commit is
`78fb9e1521c3f57d76385617a97b6f5f2c626fea`, tree
`46d0c110c74d1622a8ca6c862378eee0538aa3a9`. No runtime source was changed.
This documentation-only closure is not a new runtime execution.

The resume read all five production Swift files, the complete native prepare/Stop
patch and its surrounding proxy/worker/main implementation, the added controller
and native tests, and the Simulator runner and XCTest. Ownership remains with one
MainActor controller and one blocking invocation; validation precedes prepare,
Stop is coalesced, and replacement waits for native return plus actor delivery.
Running continues to mean invocation ownership, not confirmed listen readiness.
The tests therefore use real protocol replies, not only status labels.

| Layer | Inspected result |
| --- | --- |
| Original Swift checks | Seven scenarios,84 revalidation assertions,512 extracted configuration/YAML parity cases and22 required old-equality failures passed on both hosts. Old negative failures are not current regressions. |
| Transition matrix | 1250 four-intent schedules, five return-before-actor-delivery schedules and weak-owner release;25544 assertions on each host. Dispatch/native return are controlled; the production controller and MainActor completion execute unchanged. |
| Real native control | 18 additional records per host across workers1/4/64: occupied-port failure, no unchanged-intent retry after port release, explicit retry, quoted UTF-8 credentials,100 repeated no-op Starts preserving an active connection, invalid replacement shutdown, no-auth restoration and stopped-invalid suppression. |
| Existing native regression | 14 original/current native records,12 active-client records, eight current delayed-completion schedules with six old failures/two old Stop controls,100 legacy/prepared cancellations,40 original pre-start cycles, worker-yield controls and TCP/parser checks remain successful. |
| Source and SDK | 46 common fixtures,26 native/header entry cases and six marker cases passed; formatter18, exact ownership/ancestry/pins, clean index/worktree and native reversal passed. Five production Swift files passed ARM64/iOS17.2 checks against same-HEAD native headers; the SDK diagnostic log is empty. |
| Actual Simulator | One iPhone16/iOS27.0 XCTest passed, zero failures/skips; case time92.845s. Eleven controls, invalid input, IPv6-toggle values, actual IPv4/IPv6 SOCKS greetings, running-state editor disabling, Stop port release, portrait/landscape reachability and memory-only process restart were checked. |
| UI evidence | Six original screenshots opened; runtimeWarnings=[], cleanup=[]. Native Simulator library and app executable hashes are recorded separately. A Simulator result is not a physical installation result. |

The new state-machine tests model finite schedules, not every arbitrary scheduler
history. The native records include repetition and negative controls, not independent
device trials. Existing defaults, validation and retry semantics were not relaxed.
The standalone root remains stopped after process launch and does not store settings.

## Retained first UI failure

Run36571798495 at b0dc520357a4b23dc03e67827dd7246ae22ecb50 passed native/SDK work
but failed its XCTest after13.330seconds: app.switches.count was2, not1. One SwiftUI
Toggle exposed more than one accessibility node. Commit78fb9e15 changes only that
test to identify the logical Listen IPv6 only setting, check0/1 transitions and
enabled states. Field-count, native-protocol, validation, Stop/Start, orientation
and timeout requirements are retained. The final successful execution used those
same production bytes. No host, cache, application or timeout workaround was added.

The first run subsequently reported a600second Simulator diagnostic-collection
timeout. That is a separate failure observation, not the duration or cause of the
initial assertion. Cleanup/reversal succeeded and no UI SUCCESS marker remained.
The original failed archive is retained rather than relabeled as a success.

## Supplemental resume execution and resource review

The resume independently rebuilt the native source carried by the successful
Simulator archive on Linux, explicitly disabling splice for this additional build.
Actual current ServerTests and RevalidationTests passed. A test-only extension of
the matrix from four to five commands passed6250 schedules and152576 assertions,
with the same completion/lifetime controls and unchanged production controller.
The extended fixture is supplemental evidence, not a new committed CI test count.
The actual native18-record and active-client12-record drivers passed again.

The archive-only build lacks historical Git objects; its version lookup emitted
not-a-repository diagnostics. The local Python environment also emitted a nonfatal
spreadsheet-runtime startup traceback, outside these stdlib test drivers. Actual
driver exits were0 and the expected native records exist. These local diagnostics
are preserved, not called clean Apple/full-history evidence. The original complete
Git CI above is authoritative for source controls, historical tests and SDK/UI work.

No new production instructions, clocks, allocation policy, timer, thread, log,
persistent storage or socket operation was added by this review. Current/desired/
attempted values and the existing dispatch remain bounded by one controller's state.
Repeated no-op intents do not enqueue engines, and the weak-owner test confirms
release after completion. This is structural and finite-test evidence, not a
device CPU/RAM/energy benchmark or a proof that the underlying OS uses no resources.
The native process-global signal/engine assumptions remain as previously documented.

## Original artifact and source correspondence

| Original archive | SHA-256 |
| --- | --- |
| Final Linux11035379912 | 8ac805d13de2c6705b2b91ebe99b72dedeb7e1a5b08951535e0a02420bebab00 |
| Final macOS11038175306 | ccfbc48d125d013284fb5947aba9ea8a64f0a74f25309a5e139b6530189bd533 |
| First failed UI11036313120 | b301a2b9c570d97683df0f83e878c288f0211ab4697584955947aab43306c96b |

All three downloaded ZIP digests match GitHub metadata and all CRCs pass. Linux,
macOS native and Simulator source ZIPs identify78fb9e15 and agree on every one of
78 file bytes and Git modes. Both full source manifests match. Independent tree
reconstruction equals46d0c110. The failed source differs from the final tested
source only in ServerControlUITests.swift. Both final native-header identities
point to78fb9e15; SDK input/final worktree and index checks remain empty.
The exact native patch was reversed and reapplied in a disposable local copy;
all243 regular source files match the authenticated native archive afterward.

The final publication changes only README, the identical feature specification and
this review; the other75 tested paths are unchanged. Its Git commit/tree and parent
identify the documentation closure; no new test run is attributed to that commit.
The original be4bdd14 runtime, patch, assets, framework, project/plist, settings,
source pins and public interfaces remain unchanged. Other seven branch refs,
settings-persistence and release/build9 are not advanced. Downstream owners must
deliberately inherit and verify this owner rather than silently mix revisions.

## Final boundaries

No new failing required case or reproduced runtime regression remains in this
review's executed scope. The prior assertion defect and pending evidence/document
closure are resolved. Physical iOS27 SideStore signing/install/run, LiveContainer
guest/shared-process behavior, real permissions, background/suspension, power loss,
device footprint/energy/maximum throughput and a final release IPA remain untested.
Native, SDK and Simulator results do not substitute for those separate layers.
No finite test suite warrants an unconditional zero-defect claim for every possible
input, resource failure, OS event, deployment environment or scheduler interleaving.
