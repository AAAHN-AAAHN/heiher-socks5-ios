# Background services: asynchronous session candidate and continuous location

> **The audio responsiveness fix is not complete.** Initial uploads are published
> and the actual iOS27 SDK/controller checks passed. The actual Simulator UI test
> passed functionally, but its strict advisory gate FAILED. A diagnostic-only run
> localized the remaining warning to AVAudioPlayer.play(). A preparation-worker
> successor is locally tested but not published because its required test-double
> upload was blocked. Do not label this branch as an advisory-free release.

## Purpose, ownership and preserved behavior

`feature/background` adds independent, opt-in silent audio and continuous coarse
location to the unchanged main app/server baseline. The root supplies user intent;
the controller never handles Hev or JSON storage. The standalone root retains
`background.continuousLocation` and `background.silentAudio` AppStorage keys. The
integrated root can instead supply JSON bindings, not both stores concurrently.
There is no dependency on the settings/server-control features. Audio remains above
Location in the unchanged view. Main and release are not modified by this work.

The current published runtime changes only BackgroundKeepAlive.swift. It serializes
explicit audio activation/deactivation through completion callbacks. The original
location methods, notification registry, root, view, project/plist, native source
pins/framework, settings keys and WAV are preserved. The complete previous531-line
specification and dated evidence are byte-preserved in
`docs/history/background-before-async-20260925.md`. This README and
`docs/features/background.md` remain identical. Prior candidate text is still
reachable at commits 0f2b4534 and 9d9d8853; their local-only upload status is history,
not the present branch status.

## Versions and installation environments

| Boundary | Status |
| --- | --- |
| Configured minimum | iOS17.2, unchanged; not execution coverage of every OS version. |
| Intended environment | Physical iOS27 through SideStore standalone or LiveContainer guest, separately. |
| iOS27 explicit session transitions | Native activate/deactivate completion APIs, confirmed by the actual SDK declarations and typecheck. |
| Earlier supported OS | The same transition gate wraps synchronous setActive on a utility worker; locally tested with platform doubles, not an older iPhone. |
| Actual Apple toolchain | Xcode27.0 27A266a, iPhoneOS27.0, Apple Swift6.4, macOS27.0 26A428. |
| Executed UI environment | iPhone16 Simulator, iOS27.0 24A434; not physical SideStore/LiveContainer. |
| Current correction result | SDK/controller pass, functional UI pass, advisory gate failure. |
| Physical signing/host/background | Not performed. No installed installer/host version is certified. |

The Bundle ID remains hev.Socks5. There is no host patch, BGTask, NetworkExtension,
new entitlement, microphone request or Now Playing ownership. The checks-only
pipeline intentionally skips ordinary iPhone archive/IPA production. Simulator
products are not deployable physical-device IPA evidence. Existing integrated
build7 still contains the previous synchronous Background owner and was not updated.

## Published session-transition implementation

The existing MainActor controller retains player, timer, UI state and location
ownership. On iOS27 its explicit session changes use activate/deactivate callbacks.
Completion is reconciled on MainActor without a semaphore or synchronous wait.
The earlier-OS compatibility helper obtains AVAudioSession on a system utility
worker and calls setActive there. Wrapping a synchronous call in an actor-inheriting
Task was deliberately not used as a false nonblocking fix.

The new optional transition enum and pending-release Boolean bound work to one
outstanding session transition, including its result waiting for MainActor. They
are not saved settings or an operation history. No timeout pretends to cancel an
OS request that may still finish. Category/preference setup and player construction
and play remain on MainActor in THIS published candidate. The player-play boundary
is precisely where the remaining advisory was observed.

| Event | Required published behavior |
| --- | --- |
| Repeated On or restore during activation | Coalesce without a second session request or premature retry timer. |
| Off during activation | Stop/detach local playback and timer immediately; drain release after the pending activation; never play stale success. |
| On-Off-On | Finish the old release before starting the latest activation. |
| Invalidation during activation | Reject stale success and preserve the one-second recovery cadence. |
| Activation fails, including false without error | Preserve On and retry after one second. An error is not discarded merely because the Boolean is true. |
| Release fails while Off | Keep local playback stopped, show release failure, do not start an Off retry loop. Explicit repeated Off can retry. |
| Initial/repeated completed Off | Do not deactivate a host session this controller never used. |
| Controller released while activation is pending | Weak completion capture; best-effort release of an orphaned successful activation. |

Only one root-owned controller is the supported owner. This does not serialize
independent LiveContainer host code that shares AVAudioSession. Off denotes local
playback intent/state, not a fabricated completed system release. An in-flight
request may be delayed or denied by the OS.

Normal playback retains one AVAudioPlayer looping the same WAV, playback/default/
mixWithOthers and the best-effort system-alert preference. One common-mode one-shot
Timer provides one-second health checks or retries. Healthy playback does not
reactivate/recreate on every tick. New independent interruptions are processed
immediately when no system transition is outstanding. Repeated decoder failure
retains the existing retry deadline, with no spin, backoff, attempt cap or automatic
Off. Weak player identity and stale timer checks remain. Off during configuration
or retry disposal drains release when the enclosing re-entry guard unwinds.

The registry still includes13 iOS27 session signals and four lifecycle checkpoints,
with the existing 26/27 availability guards and legacy interruption handling.
The separate root app-active event restores both services. No new event observers,
remote-control ownership, recording events or per-packet logging were added.

Location stays continuous, not polling: three-kilometer accuracy, no distance filter,
background updates and indicator enabled, automatic pause disabled. Configuration
precedes delegate assignment. Requests require active state and are deduplicated.
New When-In-Use sessions wait for foreground; existing sessions are not restarted
on background entry. Always authorization keeps its prior behavior. Denial preserves
user intent; stale delegates are rejected. Only callback count/time, never coordinates,
are retained. Actual sensor use and delivery remain controlled by iOS.

Silence.wav remains844 bytes, mono8kHz signed16-bit,400 zero samples (50ms), SHA-256
`26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e`.
Header bytes are nonzero as required for a valid WAV; all decoded PCM samples are zero.

## Upload recovery, failures and actual validation

The complete63-file candidate was published as
`0f2b4534ac5bbd6075bdb2b1c7c7c91da22a8fbb`, tree
`3d52b98fb9beee5e6a464c3fe1ce4e13a9c1e025`. Run36094396388 failed. Its first
attempt also lost artifact upload to ETIMEDOUT. An explicit identical-source second
attempt recovered the failure evidence. All1193 existing assertions passed, but the
new test did not compile because Xcode27 diagnosed a never-mutated weak local under
warnings-as-errors. The immutable weak-capture predicate preserves the actual
controller deallocation and orphan-completion assertions; no warning was suppressed.

Tested commit `9d9d88538171dba069b424ade5abc76d6c5b54d5`, tree
`ef7086f2f3af5f0417c286439ba1f832161478a9`, ran in36094831198 attempt1.
Its audio-checks job passed all1193 retained assertions,38 delayed-session assertions
and3000 mixed transitions in debug/optimized builds, exact-old blocking controls,
actual legacy adapter with worker/main-run-loop progress,34 Combine deliveries and
cancellation, five real Timer/RunLoop conditions,400 decoded zero samples and the
actual SDK typecheck of five production Swift files with an empty diagnostic log.
The retained SDK header confirms the two session APIs' iOS27.0 availability.

The actual Simulator UI test passed once, zero failures,97.493s. It checked actual
playback status, repeated On/Off, saved intent after relaunch and tab navigation.
Cleanup succeeded. Nonetheless the UI job correctly failed its unchanged advisory
gate: the console and xcresult still contained the AVAudioSession main-thread
warning. No UI SUCCESS marker was produced. This is not a completed correction.

| Downloaded artifact | SHA-256 |
| --- | --- |
| Failure10847405501 | d8fb7bc60d1887895930647f671b64fb1c77d5f1c58167ad93562fa234116970 |
| SDK10846753389 | 3c8e18922aa1b54e1a198aaacfc74d758b01baf592523d0ed7b105cddcbb7c64 |
| UI/advisory failure10847227555 | 77ed41e4216ee85856723e6687b57ca7e6abff0ba5bc350f85cc004322dc5a8d |

ZIP integrity/digests and complete63-file source trees were checked. Both SDK and UI
artifacts'63-file manifests matched. The first failure artifact is not claimed to
contain a full manifest or a success marker it never produced. The two prior worker/
lifetime fixtures preserve their four/fifteen assertions with bounded main-run-loop
posting/draining. Scripted repetitions are not independent physical-device trials.

### Localized remaining warning

Commit `5ea0a764b285985e1798548ce4b8a596c78e31b1`, tree
`11447f13f9685bd1888b518c06d78214b2287a3b`, modified only the UI test driver to
bracket actual calls in a temporary source copy and capture filtered Simulator logs.
Run36095765226 attempt1 passed SDK/controller and functional UI but failed the same
advisory gate. This diagnostic run is not final uninstrumented product verification.

The warning repeatedly appears between same-thread before-player-play and after-
player-play markers, not the separately bracketed category/preference/initializer/
explicit-async-request boundaries. Apple documents that unprepared play implicitly
calls prepareToPlay, which activates the audio session. The trace localizes the
observed boundary and is consistent with that contract, without inventing an internal
stack. Inline activation completion was also observed; completion is not assumed
always deferred. Instrumented Simulator timing is not physical-device latency.

Diagnostic UI artifact10847363977, SHA-256
`0a1a1a8dcea5c88ae083be6efd726e65f6673a8f42cddb9fad0a20b80a362d93`, passed
ZIP/tree/manifest checks. Its temporary source, trace, original xcresult, screenshots
and clean cleanup are retained as failure evidence. This status commit restores the
uninstrumented UI driver byte-for-byte to9d9d8853, blob
`73ab512035973418d6203b5fdc244dca96784985`. No diagnostic instrumentation is left in
the current script or product, and the advisory gate remains unchanged.

## Unpublished preparation successor and precise remaining work

A locally tested successor explicitly prepares a player on a utility worker behind
the same transition gate. While preparing, it is removed from the controller's
player reference and has no delegate; Off/event/timer handlers cannot concurrently
use it. On completion, MainActor rejects Off/invalidated/failed preparation before
playback and drains any pending release. The same enum adds a preparing state,
not a new saved field, scheduler or unbounded queue. No arbitrary concurrent use
of AVAudioPlayer is assumed safe. Category/preference setup still remains synchronous;
this would not certify all possible UI stalls even if the observed warning disappears.

Local Swift6.2.1 tests passed the retained1193 assertions,38 session assertions/3000
mixed transitions,22 preparation assertions/3000 mixed transitions in debug and
optimized builds. A real utility-helper test with delayed preparation verifies main-
run-loop progress. The exact first async controller is an implicit-preparation
negative control. A scriptable utility scheduler exists only in test doubles;
default/main/labeled dispatch remain real. These are NOT Apple SDK or Simulator
results for the preparation successor.

The required updated `Tests/Background/PlatformMocks.swift` upload was blocked twice
by the tool's undetermined safety status. Its expected blob is
`f4243209df5faa22777a7ad715c30a61a7b20386`. No alternative endpoint, encoding,
renamed payload or transport was used after those denials. Other successor objects
were stored, but no partial successor tree or branch commit was published. The local
source/patch/checkpoint retain the work. Normal upload of the complete successor and
actual SDK/Simulator verification, including the retained advisory gate, remain
required. Earlier Apple results cannot be assigned to this different successor code.

The current branch still contains the SDK-tested but advisory-failing first async
implementation. Main, release, the other five features and eight-branch count remain
unchanged. Existing build7 is not updated. No IPA or iPhone archive was produced.
The requested audio responsiveness correction remains OPEN.

## Costs, unverified limits and maintenance

Published runtime cost is two bounded state fields and completion scheduling per
actual session transition, plus a utility dispatch on older systems. The proposed
successor also dispatches one preparation per actual start/recovery, not per healthy
timer tick. No dedicated thread, periodic task, additional timer/observer, disk log
or per-packet work is introduced. Energy, throughput and latency improvements are
not measured. Native async APIs cannot force faster activation or OS permission.

Physical SideStore install/signing, LiveContainer loading/session arbitration,
telephone/Siri/Bluetooth interruptions, permissions, lock-screen survival, VPN/
hotspot, process termination, protected-data and power remain untested. Saved On is
intent. Suspended/killed code cannot execute retries or relaunch itself. A system
operation that never completes is not safely canceled by inventing a timeout and
starting an overlapping operation. Older OS/iPad runtime tests are also unperformed.

Maintain the README/specification pair identically. Record minimum, target, actual
build and executed environments separately, with exact source/tree/run/attempt,
artifacts and hashes. Preserve failures and costs. Release must explicitly inherit a
completed Background owner and revalidate before a later IPA can contain this fix.

Primary contracts, not execution evidence:
- https://developer.apple.com/documentation/avfaudio/avaudiosession/activate(options:completionhandler:)
- https://developer.apple.com/documentation/avfaudio/avaudiosession/deactivate(options:completionhandler:)
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/preparetoplay()
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/play()
- https://developer.apple.com/documentation/xcode/improving-app-responsiveness
