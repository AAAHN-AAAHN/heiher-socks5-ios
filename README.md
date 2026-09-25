# Background services: asynchronous audio and continuous coarse location

> **Unpublished preparation successor.** This local source includes worker-side
> prepareToPlay in addition to native async session transitions. Its local tests
> pass, but the required test-double upload is blocked. Actual Apple SDK and
> Simulator verification of THIS preparation code has not run. Historical
> published-candidate results below do not validate this successor.

`feature/background` adds independent, opt-in audio and location services to the
unchanged main app/server baseline. The current local update replaces main-thread
synchronous audio activation/deactivation with serialized, completion-driven work,
and explicitly prepares the player on a utility worker before MainActor playback.
It does not change the server, native patches, settings schema, app identity,
background modes, WAV or view/root bindings. `release/integrated` is not updated by
this feature change; its build 7 still contains the previous audio implementation.

The four top-level project principles apply: preserve established behavior and
minimize changes; target physical iOS27 SideStore and LiveContainer separately;
maintain complete implementation/environment documentation; use only actual,
revision-linked evidence for completion claims.

## Versions and evidence boundaries

| Boundary | Contract |
| --- | --- |
| Configured minimum | iOS17.2, unchanged; not certification of every intervening OS. |
| Primary target | Physical iOS27 iPhone, either SideStore standalone or LiveContainer guest. |
| Native asynchronous path | iOS27 `AVAudioSession.activate` / `deactivate` completion APIs. |
| Earlier supported OS | The original synchronous `setActive` runs on a utility worker, behind the same single-transition gate. |
| Build toolchain | Xcode27 / iPhoneOS27 SDK; exact SDK declarations and compiler output are retained by CI. |
| Verification status of this source change | Actual iOS27 SDK and functional Simulator UI passed, but the strict advisory gate failed. The warning is NOT fixed in this branch. |
| Physical installer/host evidence | Not performed. No installed SideStore/LiveContainer version or physical interruption behavior is certified. |

The original deployment target, Bundle ID `hev.Socks5`, source pins, baseline
XCFramework, plist and project remain unchanged. There is no host patch, BGTask,
NetworkExtension, added permission or Now Playing ownership. No IPA is built in the
checks-only workflow. Its Simulator app is a distinct test product, not a signed
physical-device installation or guest execution.

## Responsibility and independent configuration

One MainActor-owned `BackgroundKeepAlive` manages one player, one health/retry timer
and one location manager. The app root supplies user intent; the controller never
reads or writes settings files or controls Hev. The standalone root retains the two
existing AppStorage keys `background.continuousLocation` and `background.silentAudio`.
The integrated root may instead supply JSON-backed bindings, without running both
persistence systems in parallel. This feature does not depend on the settings or
server-control branches. The Audio section stays above Location and Location state.

The view/root, original delegate identity checks and fixed notification registry
are preserved. The runtime source change is confined to the existing controller.
The previous full specification and all its historical results are preserved
verbatim in `docs/history/background-before-async-20260925.md`; dated successful
runs there describe the earlier synchronous implementation, not this revision.
This README is identical to `docs/features/background.md`.

## Why the session transition changed

Build7's actual Simulator execution reported that synchronous audio session calls
on the main thread could make the UI unresponsive. That warning did not measure a
particular call's latency or prove a physical crash. The old controller nevertheless
called both activation and deactivation synchronously on MainActor. Wrapping the
same blocking call in an actor-inheriting Task would not remove that blocking.

The new controller initiates native async transitions on iOS27. It handles their
completion on MainActor, without a semaphore or synchronous wait. On iOS17.2-26,
only the compatibility session call runs on a system utility worker; it obtains
AVAudioSession there rather than transferring the player/controller off actor.
Category/mode/preference setup and player creation/play remain on MainActor with
their existing re-entry checks. After activation, the player is temporarily removed
from controller ownership with its delegate detached. A single utility operation
calls prepareToPlay, then returns exclusive access to MainActor. Off/reset while
preparing vetoes playback; no handler concurrently uses the worker-owned player. This removes the explicit main-thread setActive calls, but the actual Simulator
revealed another synchronous activation inside player.play(). The overall advisory
fix is therefore incomplete, not a successful UI responsiveness certification.

## Serialized state and Off precedence

The existing restoration/re-entry and invalidation flags remain. Two bounded state
fields describe an optional activation/deactivation in flight and a required release.
They are not saved preferences or an unbounded operation queue. Exactly one session/preparation
transition may be outstanding, including the time its result waits for MainActor.
No transition timeout invents cancellation of an operation the OS can still finish.

| Situation | Required behavior |
| --- | --- |
| On while idle | Configure the existing playback session, start one activation, create/play only after accepted, noninvalidated completion. |
| Repeated On/restore while pending | Coalesce; never add a second activation or a premature retry timer. |
| New interruption/reset while activating | Mark that result unusable for playback; process completion and schedule the existing one-second recovery. Do not overlap uncancelable OS transitions. |
| Off while activating | Immediately cancel local monitoring and stop/detach the player. After activation completes, release the session; never play the stale success. |
| On-Off-On | Drain the earlier release before starting the latest activation, so a late deactivation cannot disable the new session. |
| On while deactivating | Record intent and start only when that release completes. |
| Activation failure, including false with no error | Preserve On, display Waiting and retry after one second; an error is not ignored when a success flag is also present. |
| Deactivation failure while Off | Keep local playback stopped, display the release error, and do not create a timer or retry loop. An explicitly repeated Off may retry this controller's failed release. |
| Initial/repeated completed Off | Do not deactivate a host session the controller never used. |
| Controller released during activation | Weak completion ownership avoids retaining the controller; an orphaned successful activation receives best-effort async release. |

Only the single root-owned controller is a supported execution owner. The app does
not serialize independent LiveContainer host code or unrelated controllers sharing
AVAudioSession. System completion may be delayed or denied; UI Off means local
playback stopped, not a forged successful OS release. The failed-release message
and the transient Activating message are status strings, not new UI controls.

## Recovery and cost

A single AVAudioPlayer still repeats the original WAV indefinitely using playback,
default mode and mixWithOthers. The system-alert interruption preference remains
best effort. Healthy playback never reactivates/recreates the player on each tick.
One common-mode, one-shot Timer supplies one-second health checks or failed-recovery
retries. New independent stop/invalidation is processed immediately when no system
transition is outstanding; repeated player failure in the same recovery episode
keeps the pending retry deadline rather than spinning or postponing it. A healthy
sample resets this pacing. There is no backoff, attempt limit or automatic Off.

Player callbacks retain weak object identity across their actor hop; canceled timer
callbacks retain the existing identity guard. Off during configuration, player
creation/play/disposal or callbacks remains authoritative. The old player is detached
before stop can call back. Invalidations inside the attempt cannot publish healthy
playback. Own category/activation echoes do not bypass failure pacing.

The new cost is two fixed state fields and completion handling per actual transition.
All OS versions dispatch player preparation to a shared utility worker once per
actual recovery/start. Earlier systems also dispatch the blocking session call there.
Neither operation runs on each healthy timer tick. No dedicated thread, periodic task, extra timer,
new observer, disk log or per-packet workload is introduced. Completion hops have
normal allocation/scheduling costs; no measured battery or throughput improvement
is asserted. Native async activation does not force the system to grant activation
faster or allow execution while suspended.

## Signals and location preserved

The same registry supplies subscribers and handlers. iOS27 session signals are the
legacy interruption; didBecomeInactive; resumptionRecommendation; mediaServicesLost;
mediaServicesReset; routeChange; didBecomeActive; silenceSecondaryAudioHint;
spatialPlaybackCapabilitiesChanged; renderingModeChange; renderingCapabilitiesChange;
outputMuteStateChange; and userIntentToUnmuteOutput. The 26/27 names retain runtime
availability checks. The four audio lifecycle checkpoints are willResignActive,
didEnterBackground, willEnterForeground and protectedDataDidBecomeAvailable.
The separate existing app-didBecomeActive root event restores both services.

Legacy interruption metadata and shouldResume advice do not erase saved On.
Invalidation discards stale playback, while ordinary checkpoints preserve a healthy
player. Route-category drift repairs the original category/mode/options. Mute hints
do not override user volume. Recording/input notifications and remote-command
ownership are not added to fabricate coverage of undelivered OS signals.

Location remains continuous, not polling: one MainActor CLLocationManager uses
three-kilometer accuracy, no distance filter, background updates and indicator On,
automatic pause Off. Configure it before assigning the delegate. Permission requests
occur only while active and are not duplicated. A new When-In-Use session waits for
foreground, an already-started session continues without restarting, and Always
retains its existing behavior. Denial stops updates without erasing intent; stale
manager callbacks are rejected. Only callback count/time are retained, not coordinates.
The OS chooses delivery and sensor use; coarse accuracy is not a GPS-off command.

The unchanged WAV is 844 bytes, mono8kHz, signed16-bit, 400 zero samples (50ms), with
SHA-256 `26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e`.
Raw and Apple-decoder checks distinguish the valid nonzero header from zero PCM.

## Verification design and commands

Use a full Git checkout: old-code controls and source parity read exact Git objects.
`python3 Tests/Background/run_checks.py` retains all 1193 previous assertions. The
two worker/lifetime fixtures now use the actual main run loop with bounded worker
posting/draining; no postcondition, deallocation check or repetition was removed.
Mock session completions can be inline or explicitly delayed. Existing synchronous
boundary cases remain, and `check_async_session.py` adds 38 named delayed-transition
assertions plus 3000 deterministic mixed transitions, in debug and optimized builds.
It runs the exact old controller as a blocking negative control and directly tests
the unchanged legacy helper with a delayed worker and a responsive main run loop.
These are scripted boundaries, not actual phone calls or native API timings.

`bash Tests/Background/check_audio_sdk.sh` retains source/framework checks, all prior
controller/Combine/real-Timer suites, actual WAV decoding and the iOS27 five-file
ARM64 typecheck. It also runs the new async tests and records SDK declarations.
The separate `check_async_ui.py` builds only a temporary Simulator copy with a UI
test target. It exercises actual system activation/playback, repeated On/Off, saved
intent and tab responsiveness, then inspects XCTest console/runtime results for the
previous advisory. It records source/product hashes, xcresult and cleanup results.
It does not alter the tracked app project or link test code into production.

The checks-only workflow has two validation jobs. Its ordinary archive/IPA job is
skipped. The existing controller-job timeout is unchanged; the new Simulator job has
its own bounded execution. Optional bulk test diagnostics are not collected, following
the prior verified test-runner setup; assertions, runtime issues, screenshot attachments,
result verdicts, process exit checks and cleanup remain enabled. No warning is hidden
by a compiler flag. Preserve every failed attempt under its own source/run/attempt.

## Unverified conditions and maintenance

Physical SideStore signing/install, LiveContainer loading/session arbitration,
actual telephone/Siri/Bluetooth interruptions, lock-screen survival, VPN/hotspot,
permissions, process termination, energy, all earlier OS versions and iPad UI remain
separate unperformed tests. Simulator and scripted passes cannot certify them.
Saved On is intent; retries require the process to execute, and the app does not
relaunch itself or override OS audio priority. A system request that never completes
is not safely canceled by starting overlapping requests or inventing a timeout.

Record tested source/tree, run/attempt, toolchain, artifacts/digests, success/failure/
not-run scopes and residual warnings below only after actual inspection. Keep this
README and its feature copy identical. The release must explicitly inherit the
completed new owner and be revalidated before a later IPA includes this change.

Primary API contracts (not execution evidence):
- https://developer.apple.com/documentation/avfaudio/avaudiosession/activate(options:completionhandler:)
- https://developer.apple.com/documentation/avfaudio/avaudiosession/deactivate(options:completionhandler:)
- https://developer.apple.com/documentation/avfaudio/avaudiosessiondeactivationoptions
- https://developer.apple.com/documentation/xcode/improving-app-responsiveness

## Local candidate verification (2026-09-25; remote publication blocked)

Linux Swift6.2.1 compiled the actual controller body after framework-import
substitution, using Swift5 language mode and warnings-as-errors. All retained
1193 assertions passed. The new delayed-completion suite passed 38 named assertions
and 3000 deterministic mixed transitions in both debug and optimized builds.
Both configurations also passed the exact old-controller blocking negative control
and the actual private legacy worker adapter check. The legacy test uses a delayed
platform double and real main-run-loop heartbeat, not an older iOS installation.

An additional candidate-only re-entry defect was reproduced before correction:
Off raised while retryAudio was disposing a player left its required release behind
the outer restoration guard. The final defer restores that guard then drains the
pending release. Pre-activation checkpoints also stop when an Off-On during setup
has left a release pending. Four added postconditions cover these transitions and
their final playback/session/timer state. The failing candidate log is retained as
failure evidence; the current regression and async logs both passed afterward.

Only BackgroundKeepAlive.swift changes among production files. The entire location
section, signal registry, root/view, project/plist, WAV, native sources/framework,
source pins and existing settings keys remain unchanged. The old full README is
retained byte-for-byte in the dated history file. Two existing scheduling fixtures
were adjusted to exercise real worker posting and the main run loop with the same
checks; their four and fifteen assertions were not deleted or relaxed.

A safety-status check in the GitHub write tool blocked the remaining test upload.
Some unreferenced Git objects were created, but no complete candidate commit or
branch change was made. No alternative transport or encoded retry was used after
the repeated denial. The candidate ZIP/patch and logs preserve the work, not a
claim of successful remote publication. Actual SDK availability/type compatibility,
real audio activation/deactivation and removal of the observed runtime advisory
remain unverified until the prepared Apple checks execute successfully.

## Resumed publication and actual Apple findings (2026-09-25)

The historical upload block above describes the earlier local-only checkpoint.
A subsequently available normal GitHub write path published the full 63-file
candidate as `0f2b4534ac5bbd6075bdb2b1c7c7c91da22a8fbb`, tree
`3d52b98fb9beee5e6a464c3fe1ce4e13a9c1e025`. Its run `36094396388` failed.
Attempt 1 additionally lost artifact upload to ETIMEDOUT; an explicit same-source
attempt 2 recovered the failure artifact. The retained 1193 assertions passed,
but Xcode27 rejected the new never-mutated weak local under warnings-as-errors.
Only that test declaration became an immutable weak-capture predicate, preserving
controller deallocation and orphan-completion assertions. No warning was suppressed.

Commit `9d9d88538171dba069b424ade5abc76d6c5b54d5`, tree
`ef7086f2f3af5f0417c286439ba1f832161478a9`, ran in `36094831198` attempt 1.
The audio-checks job succeeded: all 1193 retained assertions, 38 new delayed-session
assertions and 3000 mixed transitions in debug and optimized builds; exact-old
blocking controls; actual legacy helper with worker/main-run-loop progress; 34
Combine deliveries and cancellation; five real Timer/RunLoop conditions; 400 zero
PCM samples; five actual production Swift files with an empty SDK typecheck log.
The retained SDK header declares both async APIs available on iOS27.0.

The actual Simulator XCTest reported one passed test, zero failures in 97.493s,
including repeated audio On/Off, playback state and saved intent after relaunch.
Cleanup succeeded. Nevertheless the UI job correctly FAILED because the console
and xcresult retained the original AVAudioSession main-thread advisory. No SUCCESS
marker was published for that UI job. The whole run is not a successful fix.

| Artifact | SHA-256 |
| --- | --- |
| First candidate failure, attempt 2: 10847405501 | d8fb7bc60d1887895930647f671b64fb1c77d5f1c58167ad93562fa234116970 |
| Passed SDK/controller: 10846753389 | 3c8e18922aa1b54e1a198aaacfc74d758b01baf592523d0ed7b105cddcbb7c64 |
| Functional UI pass / advisory failure: 10847227555 | 77ed41e4216ee85856723e6687b57ca7e6abff0ba5bc350f85cc004322dc5a8d |

All downloaded ZIPs passed integrity/digest checks and their 63-file source archives
reconstructed the matching Git tree. The successful SDK and failed-UI artifacts'
complete 63-file manifests matched. The failure artifact does not manufacture a
full source manifest or a success marker it never produced.

### Evidence-based localization, not a guessed host workaround

Diagnostic commit `5ea0a764b285985e1798548ce4b8a596c78e31b1`, tree
`11447f13f9685bd1888b518c06d78214b2287a3b`, changed only the UI audit script.
It inserted before/after markers in a temporary source copy and captured a narrowly
filtered Simulator log. The tracked controller, calls, order, warnings, assertions
and timeouts were not changed. Run `36095765226` attempt 1 again passed the SDK and
functional UI but failed the unchanged advisory gate. It is diagnostic failure
evidence, not a passing final-product test.

The warning repeatedly appears between the same thread's before-player-play and
after-player-play markers. It does not appear between the separately bracketed
category/preference/initializer/explicit-async-request boundaries. Apple's play()
contract says an unprepared player implicitly invokes prepareToPlay(); preparation
activates the audio session. The trace localizes the observed call boundary and is
consistent with that documented behavior; it does not supply an unavailable internal
system stack or measure physical-device latency. An inline activation completion
was also observed; the controller must not assume every completion is deferred.

Diagnostic UI artifact `10847363977`, SHA-256
`0a1a1a8dcea5c88ae083be6efd726e65f6673a8f42cddb9fad0a20b80a362d93`, was
downloaded, ZIP/hash/tree/manifest checked. Its temporary controller, traces,
original xcresult, full-screen attachments and clean Simulator cleanup are retained.
Both the published and successor UI scripts are restored byte-for-byte to the uninstrumented 9d9d8853
script (blob `73ab512035973418d6203b5fdc244dca96784985`). No production logging or
permanent diagnostic feature remains. The strict warning gate is not weakened.

### Successor work is not yet in this branch

A locally tested successor explicitly prepares the player on a utility worker,
with exclusive temporary ownership behind the existing transition gate. During
preparation the controller holds no player reference/delegate for concurrent use;
Off prevents playback and drains release when preparation returns. Only successful,
noninvalidated preparation is handed back for MainActor play/Off ordering. This
extends the same bounded transition enum, not a second operation queue or timer.
It also requires preparation failure, delayed Off-On, reset and orphan cleanup tests.

Local Swift6.2.1 tests passed all retained1193 assertions, the existing38 session
assertions/3000 transitions and22 new preparation assertions/3000 transitions in
both debug and optimized configurations. A real utility-worker helper test verified
main-run-loop progress using a delayed preparation double. The exact first async
controller remained a negative control for implicit main-thread preparation.
These are not iOS SDK/Simulator results for the successor.

Publishing its updated `Tests/Background/PlatformMocks.swift` was blocked twice by
the tool's undetermined safety status. No alternate transport, encoding or renamed
payload was used. The required blob is `f4243209df5faa22777a7ad715c30a61a7b20386`.
Other successor objects were stored, but no partial successor commit/ref was made.
Do not combine the successor's local test results with this branch's earlier Apple
results to claim completion. After normal publication is possible, its complete
source must undergo all existing SDK, real Timer/Combine and uninstrumented
Simulator checks, retaining the advisory gate. Release and build7 remain unchanged.

Observed Apple environment: Xcode27.0 `27A266a`, iPhoneOS27.0, Swift6.4,
macOS27.0 `26A428`, iPhone16 Simulator iOS27.0 `24A434`. The iOS17.2 minimum,
physical SideStore/LiveContainer target, permissions, real phone/Bluetooth events,
lock-screen execution and energy are separate, unperformed execution boundaries.
This status completion changes only the README pair and removes temporary test-copy
instrumentation. All runtime code remains the SDK-tested but advisory-failing
9d9d8853 candidate. Main, release, all other feature refs and eight-branch count stay
unchanged. The audio responsiveness correction remains OPEN.

Additional primary API contracts:
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/preparetoplay()
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/play()

## Local successor implementation scope

In this ZIP, SessionTransition includes preparing, and audioPrepared validates the
latest Off/invalidation state before playback. Failed preparation never falls back
to an implicit prepare in play. This separation avoids concurrent player mutation;
it is not a claim that arbitrary AVAudioPlayer operations are thread-safe. No
unchecked Sendable annotation, lock, semaphore, new persistent setting or dedicated
thread is added to production. Category/preference calls still have their original
synchronous behavior; no universal UI-latency guarantee is made.

The utility scheduler is scriptable only in PlatformMocks.swift. Main/default and
labeled dispatch remain real for worker/delegate tests. Separate adapter tests set
the utility double to real forwarding and exercise the unchanged production helper
with a main-run-loop heartbeat. The original synchronous and first async controllers
are exact-Git-blob controls. All such doubles remain outside the app target.

Current local source contains64 files. These bytes are not the published63-file
SDK-tested source. The companion checkpoint and patch distinguish the states.
