# Background services: asynchronous audio and continuous coarse location

> **Local candidate only — not published or Apple-validated.** GitHub write
> operations for required test files were blocked by the tool. Remote
> `feature/background` remains `207214b41e0191345a46a820700b45d33dd7cb6e`.
> No commit/ref update, new CI run, iOS27 SDK compile, Simulator execution or IPA
> was completed for this candidate. The local results below are Linux tests using
> explicit platform doubles, not native iOS API execution.

`feature/background` adds independent, opt-in audio and location services to the
unchanged main app/server baseline. The current update replaces main-thread
synchronous audio activation/deactivation with serialized, completion-driven work.
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
| Verification status of this source change | Local scripted and optimized checks passed; new SDK and real Simulator verification is pending until its actual artifacts are inspected below. |
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
their existing re-entry checks. This fixes the identified activation/deactivation
boundary, not every possible expensive system call or all UI stalls.

## Serialized state and Off precedence

The existing restoration/re-entry and invalidation flags remain. Two bounded state
fields describe an optional activation/deactivation in flight and a required release.
They are not saved preferences or an unbounded operation queue. Exactly one system
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
iOS27 needs no added worker queue; earlier systems dispatch the blocking session
call to a shared utility worker. No dedicated thread, periodic task, extra timer,
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
