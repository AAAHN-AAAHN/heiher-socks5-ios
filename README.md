# Background services — continuous audio and location

## Completed final review — 2026-09-30

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
if a reentrant Off-On requested fresh work, consume that recorded request and service
only the latest On. Clear its deferred-resume flag before starting new work, so a
failure cannot consume the same request twice. After an activation request, keep the
existing serialized release and failure behavior.

The production change is confined to this release decision: no new state, API,
allocation, timer, queue, lock, notification or retry interval. New tests preserve
all earlier input cases and add pre-activation failure/reentry, owned failure and
healthy dual-service reuse. One old async expectation explicitly required the
unowned release; its scenario is retained with the corrected no-release/one-latest-
activation invariant. No timeout, warning policy or physical claim is relaxed.
The final source `ef334cfbda66b12fad6c6c8e9a7294e6da559720` passed the fresh
full-history Linux, Apple SDK/host and actual Simulator jobs in run `36646138081`,
attempt 1. The exact results and earlier failed candidate are recorded below.
README and `docs/features/background.md` match. Physical execution remains untested.

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

## Final exact-source evidence — 2026-09-30

Run `36646138081`, attempt 1, completed successfully; terminal metadata updated at
2026-09-29T23:46:13Z. The executed commit is
`ef334cfbda66b12fad6c6c8e9a7294e6da559720`, tree
`1065326f1b8b32d022fbc3874d8de7a819081e8a`, with 78 tracked files.
Linux recovery, Apple audio/SDK, and the separate actual Simulator job all passed.
The generic native/archive/IPA job was deliberately skipped by the unchanged
checks-only workflow. It is not a new native server build or IPA success.

| Layer | Inspected result |
| --- | --- |
| New ownership boundaries | 135 current assertions in both debug and optimized modes on Linux and macOS. Setup rejection, reentrant Off-On, sixteen immediate/delayed post-request failure combinations, failed owned release, and 10,000 healthy dual-service reuse iterations passed. Exact prior controller fails 13 of 30 unowned assertions as required. |
| Existing recovery | All 35 policy cases, 98 reentry combinations and 1,352 mixed ordered pairs remain. Both modes pass 69,984 ordered triples/3,536,977 assertions and 65,536 events/1,024 recovery checkpoints/313,217 assertions. Deliberate one-second mutation remains rejected. |
| Delayed operations and lifetime | Existing 38 asynchronous-session assertions and 22 preparation assertions, each including 3,000 mixed transitions, pass in both modes. Existing controller/delegate/recovery/lifetime/location suites and old authorization-reset control remain successful. |
| Actual host scheduling | Real Foundation/Combine delivers all 17 registered names from main and worker, 34 deliveries total. Cancellation detaches the subscriber. Real RunLoop retries and queued advice, Off priority, controller release and independent location pass with audio/location doubles. This is not a real telephone interruption. |
| WAV and SDK | Apple AVAudioFile decodes all 400 samples as zero, mono 8kHz/50ms. All five production Swift files pass iPhoneOS27/ARM64 minimum17.2 typechecking with warnings-as-errors; the diagnostic log is empty. |
| Audit integrity | 46 common baseline controls, 37 audit-entry boundaries and three original marker controls pass; exact ancestry/source pins, source scope, worktree/index and whitespace gates pass. |
| Actual Simulator | Unchanged XCTest on iPhone16/iOS27.0 passes one case, zero failures/skips, in108.037s. Repeated On/Off, saved-On relaunch, final-Off relaunch and tab navigation retain their existing requirements and timeouts. |
| Runtime evidence | Two original Playing/Off screenshots inspected. runtimeWarnings=[], cleanup=[]. No matching synchronous-audio main-thread advisory in the completed console or result object. AppIntents extraction notices remain in the raw build log; this is not a universally warning-free claim. |

Finite histories and scripted platform failures are not physical deployment trials.
The Simulator test does not exercise actual location permissions, calls, route/service
failures or another process/host's audio session. Its app executable SHA-256 is
`f28d40a9655e11b982ec68c7a5a661100120497721578994ad4e4b64fa9969d2`.
The source/archive/runtime values identify this execution, not a user-installable IPA.

The real host failure-retry observations were at 0.002039, 0.507877 and 1.014083s;
service-loss observations were at 2.627838, 3.146110 and 3.717973s. These actual
intervals include scheduling delay and do not turn the 0.5-second timer into an OS
completion deadline. Healthy checks did not recreate or reactivate the player.
Recorded tools: Xcode27.0 27A266a, iPhoneOS27.0, Apple Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428; Simulator iOS27.0 24A434.
Linux CI used Swift6.4; supplemental local replay used Swift6.2.1, not the Apple SDK.

### Retained development failures and negative evidence

The initial exact-old probe showed zero activations but one deactivation after failed
category setup and Off; the preexisting active session double became inactive.
The first repair at `3bf3ece42aa22a79b740a54ff91c2be4da936be3` removed that release.
A stricter local rejected-activation probe then found it left a deferred On flag,
causing two immediate activation attempts. The final version clears the already
consumed flag and passes sixteen corresponding failure/reentry combinations, without
new state or a changed retry interval. That intermediate candidate is not a final pass.

Run `36645555618` also failed the new ownership fixture's Apple compilation because
a local weak variable was never mutated and warnings are errors. A weak-capture
closure replaces that test-only declaration, retaining its release check. Earlier
policy successes do not make the failed Apple job or skipped UI successful. Its
original failed ZIP and first Linux ZIP are retained; the final run is a new source,
not a relabeled retry. No host setting, cache, timeout or diagnostic suppression was
used to obtain the final success.

The earlier async test had explicitly expected an unowned deactivation during
configuration Off-On. Its input case remains, but now asserts zero unrelated release
and one latest activation. All other old input cases and deadlines are preserved.
The prior review's saved-On Playing wait and Simulator helper failures remain in the
immutable old README; they are not assigned an unproved cause or erased by this run.

| Original archive | SHA-256 |
| --- | --- |
| Final Linux11068811485 | 486924f8ca96882cb2c7c8ecf3628679829972597238227fee1b2860c9f33408 |
| Final Apple SDK11067873729 | 762d0d3babc834559a26256fab6c9093fb4fc75d0e88ed38e0ac91453466c12a |
| Final Simulator11068664473 | ccd8f69855ff509e67220140f3aa36fff67fe8bd2032c9c041ee0c5c6f4365d3 |
| First failed Apple11068717036 | 32021e4c6b8fd4f3a82557f22b8c570d78e46bde81547e9ca6ed81b6a1889468 |
| First Linux11067688592 | 6ad03c37f6c267a0e8a6741ab2da25d3765fc9e6910d9ce0b02c64909c7db80e |

All five original ZIP digests/CRCs were checked. Final Linux/SDK/Simulator source
archives contain identical 78 file bytes and Git modes; the SDK/UI full manifests
agree and the tree was independently reconstructed. The starting 76-file tree and
its complete README were also reconstructed from authenticated prior sources and
matched to the original Git objects. Local snapshot replays do not invent full Git
history or replace the connected CI. The original controller and first candidate
negative probes and corrected results remain in the companion evidence package.

### Final source and publication boundary

The complete production delta since `9d87d7cf` is seven added lines and one removed
line, including two comments, only in `deactivateAudio()`. Every other byte of that
controller is unchanged. Root/view/server, notifications, timing, WAV, project/plist,
framework, all pins and the other four production Swift files are preserved.
Four test/driver paths and the identical README/specification complete the seven-path
review delta, including two new test files. No native patch or feature merge is added.

The closing commit changes only this README and its identical feature specification.
The other 76 of 78 paths retain the exact tested bytes and Git modes. Its own parent,
commit and tree identify publication; the executed source and run above identify the
runtime evidence. A documentation-only closure is not a new execution. Other seven
branch heads and release/build9 are unchanged.

All reproduced ownership defects and required current-suite failures are resolved
within this executed scope. Source guards are checkpoint comparisons, not a proof
against every transient tool/filesystem change. Physical SideStore/LiveContainer,
actual interruptions/location/background survival and device resources remain the
explicit unperformed layers above; this finite audit is not an unconditional
zero-defect guarantee for every possible deployment or scheduler history.
