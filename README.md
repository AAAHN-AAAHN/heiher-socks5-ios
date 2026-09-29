# Background services — continuous audio and location

## Final-review checkpoint — 2026-09-30

Reviewed owner: `9d87d7cf3c5be3a96e1b36b5a14b944cf80a35c1`. The complete prior
specification, source/run identities and retained failure history remain at that
immutable Git revision's README and in the existing `docs/history` files. They are
historical results, not execution evidence for this changed controller.

This review reproduces one additional ownership defect: if initial category setup
fails before any activation request, Off still deactivates the shared audio session.
That can affect a session this controller never activated. It is reproduced with the
exact production controller and scripted platform failures, not a physical host.
The repair uses the existing `ownsAudioSession` flag at the release boundary. When
no activation was requested, clear local pending release without calling the platform;
if a reentrant Off-On requested fresh work, service only that latest On. After an
activation request, keep the existing serialized release and failure behavior.

The production change is confined to this release decision: no new state, API,
allocation, timer, queue, lock, notification or retry interval. New tests preserve
all earlier input cases and add pre-activation failure/reentry, owned failure and
healthy dual-service reuse. One old async expectation explicitly required the
unowned release; its scenario is retained with the corrected no-release/one-latest-
activation invariant. No timeout, warning policy or physical claim is relaxed.
Fresh full-history native/model, Apple SDK and actual Simulator results are required
before this checkpoint is closed. README and `docs/features/background.md` match.

## Environment, responsibility and immutable inputs

The primary target is physical iOS27/iPadOS27, installed independently through
SideStore or run as a LiveContainer guest. Signing, process/session ownership,
container, permissions and host arbitration differ; SDK and Simulator do not certify
either physical deployment. Configured minimum remains iOS17.2, not proof of execution
on every intervening version. `docs/top-level-principles.md` applies unchanged.

One root-owned MainActor controller manages independent audio/location choices.
Server Start/Stop and tab visibility do not own these services. The root persists
`background.continuousLocation` and `background.silentAudio` through the same AppStorage
keys; the controller never reads storage or the Hev engine. Multiple independent
controllers sharing the process audio session are outside the supported contract.
The ownership flag records this controller's activation requests, not an OS lease
or a lock against unrelated LiveContainer host operations.

AppRoot, view, server code, project/plist, source pins, committed unpatched native
framework, permissions, all notification memberships and Silence.wav are unchanged.
No UDP/statistics/settings/server-control/icon/release merge, IPA, microphone,
NetworkExtension, BGTask, PiP, host patch, cache deletion or packet log is introduced.
The previously removed cyclic-audio branch remains absent; finite playback cycles,
intentional gaps, spare players and forced operation cancellation are not added.

## Continuous location contract

One CLLocationManager uses `kCLLocationAccuracyThreeKilometers`, no distance filter,
background updates and the visible indicator, with automatic pausing disabled.
Configure before assigning its delegate. Permission requests occur only while active
and are deduplicated. A new When-In-Use session waits for foreground; an already
started session is not restarted when entering background. Always-authorized starts
retain their existing behavior. Reset/denied/restricted authorization stops obsolete
updates without changing saved On. A valid new authorization can resume the manager.

Off stops updates, detaches/releases the manager and rejects all stale manager
callbacks. Temporary errors retain intent. Only nonempty authorized update callbacks
increment Reads and update the last-read date; coordinates/history are never stored
or transmitted. There is no location polling timer. iOS controls update cadence;
coarse accuracy and disabled pausing do not imply zero power or guaranteed execution.

## Continuous audio and event policy

One AVAudioPlayer loops the original 50ms silent WAV with `numberOfLoops = -1`.
The session is `.playback`, `.default`, `.mixWithOthers`. A best-effort system-alert
preference is not an override of OS interruption priority. The same nonrepeating
common-mode Timer uses `audioCheckInterval = 0.5` for health, retry and unavailable-
service probes. One deadline remains scheduled; Off has no automatic timer.

| Event/state | Established response |
| --- | --- |
| Healthy timer or route/rendering/mute/lifecycle checkpoint | Check isPlaying/category/mode/options; retain healthy player and session. No periodic player recreation or reactivation. |
| First unexpected stop, decoder error, infinite-player completion or actual interruption | Try immediate recovery unless an uncancelable operation is already owned. |
| Repeated failure before a healthy sample | Keep the failure episode and existing 0.5-second deadline; do not spin or renew it on every event. |
| End/positive or unknown resumption advice | Availability checkpoint, not automatic object invalidation. One opportunity may expedite a failed episode; duplicates cannot reset its budget. |
| Negative shouldNotResume | Keep On and healthy playback, but do not bypass a pending retry. It is not an explicit Off. |
| Reset or invalidated activation/preparation | Drain the actual operation, reject its stale result, then service any recorded fresh request. |
| Media services lost | Stop local output, invalidate work, preserve On and existing retry. If no deadline exists, use the same 0.5-second interval. |
| Missing end/reset | Serialized availability probes can recover when the platform accepts work. |
| Own active/category echo | Do not cancel valid work or reset failure pacing. |
| Explicit Off | Stop local player/timer immediately; drain outstanding work before releasing an activation requested by this controller. |
| Off before any activation request | Do not deactivate an unrelated shared session, including failed setup and reentrant Off-On. |
| Owned release rejected while Off | Show failure, no automatic retries; another explicit Off may retry. |
| Destruction | Stop local resources; best-effort release only for requested activation. Weak orphan completions clean up late work. |

MainActor owns state and ordering. iOS27 session activation/deactivation use completion
APIs; earlier OS setActive and preparation use their existing utility-worker adapters.
A preparing player is detached from delegate/controller access until completion.
Off-On cannot allow an old release to finish after the new activation. Weak player
identity rejects obsolete delegate callbacks, including across worker/MainActor hops.

Timer intervals are scheduling requests, not deadlines on OS completion. A suspended
or terminated process cannot run them or relaunch itself. A platform operation that
never returns cannot safely be canceled by pretending it completed. isPlaying plus
configuration is not a physical-output monitor; sampling the 50ms loop position at
0.5seconds would alias, so no false stall detector is added. Persistent On is user
intent, not permission, proof of playback or unlimited server execution.

Apple's general media-player guidance can require fresh user action after a reset.
This project's explicit persistent-On policy deliberately keeps best-effort automatic
recovery; it is not described as the universal Apple recommendation. Physical calls,
Siri, route changes, services resets and host coexistence still need actual tests.

## Resource cost and minimal-change rationale

Healthy checks reuse the same player/manager. The ownership repair adds only an
existing-Boolean branch on release and removes unnecessary session calls. No extra
per-packet or per-location-update work is introduced. The existing timer still creates
one replacement deadline per tick; no new timer source or frequency change is hidden.
The 0.5-second setting costs more wakeup opportunities than the older 1-second design;
this review does not claim measured energy/throughput improvement or zero footprint.

Failure-only tests include a preexisting active shared-session double, initial category
rejection, reentry at category/preference setup, Off-On without prior activation,
post-request activation/initialization/preparation/play failures, delayed release and
explicit failed-release retry. Ten thousand healthy audio checks interleaved with
location callbacks require one player/manager, unchanged activation/configuration
counts and one timer. These are allocation/call-count invariants, not device RSS,
physical audio continuity or an independent host-arbitration experiment.

## Verification and reproduction

Use a clean full-history checkout with Swift and the actual Apple SDK where required:

```sh
python3 Tests/Background/run_checks.py
python3 Tests/Background/check_async_session.py
python3 Tests/Background/check_interruption_policy.py
# Includes original policy/mixed/final histories and the new ownership driver.
bash Tests/Background/check_audio_sdk.sh
python3 Tests/Background/check_async_ui.py
```

The new `check_session_ownership.py` uses the exact prior controller blob
`0224ecec67a7c454d7943affc1790542dee13386` as a negative control. Only framework
imports are substituted; production method bodies and existing PlatformMocks remain.
Current debug and optimized results must pass; the old unowned-release scenarios
must still fail. Native API behavior, worker hops, real Combine/RunLoop scheduling,
WAV decoding, source scopes, stale markers and Apple SDK checks remain separate.

Existing 35 policy scenarios, 98 reentry combinations, 1,352 ordered pairs, 69,984
ordered triples and 65,536-event histories with 1,024 automatic liveness checkpoints
are retained. Assertion totals can vary with fewer unnecessary release transitions;
no input history or assertion is deleted for that reason. Existing historical negative
controls retain their original timing assumptions. The unchanged Simulator XCTest
keeps its original On/Off, saved-On relaunch, tab and advisory/cleanup requirements.
Prior failed Playing waits and helper/setup failures remain failures of their runs;
a future pass cannot establish their internal cause or a universal latency bound.

A source snapshot cannot replace missing Git history. Archive-based Linux replays
are supplemental, not full-history CI, Apple runtime or physical-device evidence.
The `[audio-checks-only]` workflow deliberately skips generic native/archive/IPA jobs.
No new release product is implied by a successful feature-check run.

Primary contracts, not execution evidence:
- https://developer.apple.com/documentation/avfaudio/avaudiosession
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/preparetoplay()
- https://developer.apple.com/documentation/corelocation/cllocationmanager/allowsbackgroundlocationupdates
- https://developer.apple.com/documentation/corelocation/cllocationmanager/pauseslocationupdatesautomatically

## Explicit deployment limits

Physical SideStore signing/install/run, LiveContainer guest and shared-process audio,
manual permissions/first unlock, actual call/Siri/Bluetooth/service-reset sequences,
long locked-device/background survival, OS suspension/termination, device CPU/RAM/
energy and maximum throughput remain unperformed until actual evidence exists.
Location mocks and Simulator audio do not certify these paths. No finite suite proves
all possible OS, scheduler, input and resource-failure histories defect-free.
