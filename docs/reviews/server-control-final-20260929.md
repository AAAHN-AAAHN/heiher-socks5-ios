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

## Local checkpoint

Prior run36225969482 artifacts10900532603/10901051463 match their GitHub SHA256
and ZIP CRC. Their actual source archive is reconstructed and the current owner
README/history restored; the 72-file before tree is81d0e5c670eb3c49839feef214cb0cc307ba5082.
The runtime has no direct github.com DNS access. Local native input was therefore
restored by reversing the seven exact patches from authenticated statistics source,
then applying only this owner's one patch. This is not an invented Git history.
Local current Swift scenarios, 84 assertions, transition matrix, 18 native records
and 12 active-client cases pass. Full old-history/formatter18 and Apple checks still
require the connected CI. No existing assertion, deadline or warning gate is relaxed.

## Completion criteria and deployment boundaries

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
