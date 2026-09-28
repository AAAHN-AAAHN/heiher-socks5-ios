# Continuous Background audio — 0.5-second recovery audit

One AVAudioPlayer loops the original 50ms silent WAV indefinitely
(`numberOfLoops = -1`). Normal checks, failure retries and media-service availability
probes use one common-mode RunLoop Timer and one `audioCheckInterval = 0.5` constant.
There are no finite-playback cycles, intentional gaps, reserve-player pools, additional
runtime timers/queues, high-QoS changes or periodic replacement of healthy playback.

## Environment, baseline and scope

The primary target is a physical iOS27/iPadOS27 device installed independently with
SideStore or executed as a LiveContainer guest. These are distinct execution and
signing environments. Configured minimum OS remains iOS17.2; SDK acceptance is not
runtime certification for every supported version. Xcode/Simulator execution does
not substitute for either physical target. Exact user instructions are preserved in
`docs/top-level-principles.md`.

Only `feature/background` is updated. The reviewed baseline is
`30518abdaa43d0c20c4af5fbab65a6e8572b0160`. Original Background at bfc4656a, the
six-feature release at8577bb1f and the old build9 IPA are separate snapshots.
`feature/background-cycled-audio` was removed in operation36347191102 and is not
merged here. Deleting that ref did not rewrite Git history or erase failure artifacts.
Main, the other five feature branches, native framework/pins and release are unchanged.
No new IPA or release merge is part of this branch-only audit.

All location methods, the audio-notification membership and root subscriber,
AppStorage keys, server code, project/plist, permissions and original WAV are
preserved. Location and audio choices remain independent of each other and the server.
No microphone, NetworkExtension, BGTask, host patch, extra persistence or packet log
is added. Only one root controller is supported; unrelated LiveContainer host session
operations are not serialized by this controller.

Earlier full specifications, hashes and execution histories remain available at:
- `7c410b973181ea8acfeab46a695098268f854498`: preceding 1-second/5-second repair.
- `30518abdaa43d0c20c4af5fbab65a6e8572b0160`: unified half-second revision.
These historical results are not used as proof of this audit's changed controller.
README and `docs/features/background.md` contain the same current specification.

## Event policy

| Input or state | Response |
| --- | --- |
| Healthy timer or ordinary route/rendering/mute/lifecycle checkpoint | Retain the player; check isPlaying and category/mode/options. Do not recreate or reactivate healthy output. |
| First unexpected stop, decoder error, completion of the infinite player, or actual inactive/began/unknown interruption | Attempt recovery immediately when no uncancelable platform operation is in flight. |
| Repeated failure before a healthy sample | Retain the same failed episode and scheduled 0.5-second retry instead of spinning. |
| Interruption ended or positive/unknown resumption advice | Reevaluate availability, not resource validity. Preserve healthy playback and valid in-flight work. One automatic opportunity may expedite a failed episode; duplicates cannot continually renew it. |
| Negative shouldNotResume advice | Retain saved On and healthy output, but do not bypass a pending retry. This is not a user Off command. |
| Reset or resume after an invalidated activation/preparation | Reject the old result, drain its real completion, then service the recorded fresh request without an extra unnecessary timer wait. |
| Media services lost | Stop owned output, invalidate old work, retain On and an existing 0.5-second deadline. If none exists, schedule the same interval. Do not activate on every loss/hint. |
| Missing reset/end notification | The serialized half-second availability probe can recover once the platform accepts work, without waiting forever for a notification. |
| Media reset, meaningful resumption, foreground or explicit On | Reevaluate immediately within the same operation/budget rules; old invalidated objects do not become valid again. |
| Own normal category/active echoes | Preserve valid work and pending retry; no self-triggered recreation loop. |
| Explicit Off | Stop local playback/checks immediately, reject stale results, and release after any outstanding activation/preparation. Off-On must drain the earlier release first. |
| Release rejected while Off | Show the failure without automatic Off retries. A repeated explicit Off may retry release. |
| Controller destruction | Stop owned player/timer; best-effort release only after this owner requested activation. In-flight work retains weak orphan cleanup. |

All scheduled audio checks use 0.5 seconds, including media-service loss. Immediate
handling is not delayed to the next tick. Off deliberately has no timer. An in-flight
activation/preparation/release is not duplicated every0.5seconds. The single timer's
interval is a scheduling request, not a real-time guarantee or a bound on Apple API
completion. Retaining an existing deadline can make a check occur less than0.5seconds
after a new notification; it does not change that timer's configured interval.

## Defect reproduced and minimal repair

The baseline handled single-kind notification storms, but a mixed sequence still
reset the automatic-resumption budget and canceled the only pending timer. With
activation rejected, twenty alternating loss/resumption pairs raised the activation
count from1 to21 without any timer firing. Further mixed loss/advice/reset/inactive
signals could keep replacing the retry deadline instead of allowing it to run.

This revision removes both resets from the media-loss handler. All timer purposes
already use0.5seconds, so a previously scheduled check is valid for probing lost
services as well. The first meaningful resumption may still expedite recovery, but
subsequent events in the same failed episode preserve the budget and deadline. A
healthy sample ends the episode; explicit user On retains its deliberate retry path.
The same inputs now produce only the initial attempt and one immediate opportunity
until a timer runs. This is model-observed control flow, not a measured iPad call rate.

The registry name changes from `invalidatingAudioNotifications` to
`sessionLifecycleNotifications`: its members include availability advice, not only
invalidations. Membership and subscriptions are unchanged. The production diff is
5 added and8 removed lines in one controller; no new runtime state or API is added.
Location, concurrency adapters, infinite playback and all other controller code are
byte-preserved. Fewer conditionals replace the faulty reset logic; no separate
per-notification retry mechanism is introduced.

## Concurrency, cost and technical limits

MainActor owns intent, player/control state and ordering. iOS27 activation/deactivation
uses completion-based APIs; pre27 setActive and prepareToPlay retain their utility
worker adapters. A preparing player is detached from controller/delegate ownership
until its worker returns. Category/preference setup, object creation, play and stop
remain in their existing contexts. Not all possible system-call latency is eliminated.

Normal checks do not allocate new players or reactivate the session. This audit does
not change the frequency from the already selected0.5seconds. Relative to the older
1-second/5-second design, requested normal wakeups are twice as frequent and lost-
service probes ten times as frequent; actual energy/throughput was not measured.
The repair avoids extra event-frequency activation attempts and timer replacements.

isPlaying plus configuration is not a physical output monitor. Polling the50ms
loop's currentTime at0.5seconds would alias and is not added as a false stall detector.
No system volume/mute, interruption priority or host policy is overridden. A suspended
or terminated process cannot run timers or relaunch itself. A never-returning Apple
operation cannot safely be treated as canceled to start an overlapping replacement.
Persistent On is intent, not permission or a guarantee of unlimited server execution.

Apple's general media-player guidance may require fresh user action after service
reset. Automatic best-effort continuation here deliberately preserves this project's
explicit persistent-On policy; it is not claimed to be Apple's universal auto-resume
recommendation. SideStore and LiveContainer permissions/arbitration still need separate
physical tests. Lock-screen ping growth and UDP-load latency are not diagnosed or
claimed fixed by this audio-policy change.

## Verification and reproduction

Use a full clean Git checkout with historical blobs:

```sh
python3 Tests/Background/run_checks.py
python3 Tests/Background/check_async_session.py
python3 Tests/Background/check_interruption_policy.py
# The preceding driver includes the new mixed-notification suite.
# Xcode27 host:
bash Tests/Background/check_audio_sdk.sh
python3 Tests/Background/check_async_ui.py
```

Existing35 policy scenarios,98 reentry combinations,12000 mixed transitions and a
separate12000-event/300-history automatic-recovery test remain. Historical negative
controls retain their original interval assumptions rather than passing solely due
to a new interval. Original UI deadlines, predicates, advisory and cleanup gates are
unchanged. Only framework imports are replaced when testing with platform doubles;
production function bodies are not rewritten.

The new suite adds deadline and mixed-storm regressions plus all1352 ordered pairs
(13 inputs, four transition phases, accepting/failing responses). Its three groups
perform9,611 and23896 assertions respectively per compiler mode. Both debug and
optimized must pass. The exact pre-audit blob cfd8398d45f7eb1c7558455cbbcd71f574cd0855
must fail the two regression groups. These finite combinations are not independent
physical interruption trials and not proof about every possible event history.

### Previous interval-only validation, now recorded

Run36361433857 at30518abd succeeded on attempt1: Linux recovery, Apple SDK and
uninstrumented Simulator UI. The original XCTest passed with0failures/0skips in
147.366seconds. The targeted main-thread advisory, runtimeWarnings and cleanup gates
passed. SDK accepted five Swift files for ARM64/iOS17.2 using iPhoneOS27 with warnings
as errors. Raw asset decoding and source/pin/composition guards passed. This records
the previously pending documentation result, not a new execution of that old source.

Original artifact digests:
- SDK10946235322: 9aafa8d23dadf928980355cc396c3a39d2563fb57f78de03f5a4ed36abbc4d44
- Linux10945129982: 05037e4836faaea80d8918bc113d099ae18d97d229d851879934f5333b206732
- UI10945729721: 133bb65b3693e64e2dbd058c71026af1ff9bd14dac007ef67503621b790fb77f

The earlier36361208332 failure was an obsolete1second composition assertion; it is
not relabeled as success. Earlier Simulator readiness/Playing-wait failures likewise
remain historical failures. A separate diagnostic run36356990709 observed one
prepareToPlay call taking about10.78837seconds and returning true after successful
activation, without an overlapping operation or retry loop in that segment. Its
internal cause and relation to other timeouts remain unestablished; no speculative
forced restart, host/QoS change or timeout relaxation is added here.

### Current audit execution status

Local exact-controller tests, all35 current policy scenarios and the new mixed-signal
suite pass their stated expectations, including exact pre-audit negative controls.
Fresh Apple SDK/Combine/live scheduling and uninstrumented Simulator validation are
pending for the audit candidate and must be recorded against its actual commit.
The generic native/archive/IPA job is outside the audio-checks-only scope and must
not be labeled passed. No new IPA is created by this request.

Physical iOS27 SideStore installation, LiveContainer guest execution, real calls,
Siri, Bluetooth, actual media-service resets, long locked-iPad operation, power,
latency and throughput remain unperformed. Neither mocks nor Simulator replace them.

Primary API contracts (not execution evidence):
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptionrecommendation
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptioncontext
- https://developer.apple.com/documentation/avfaudio/avaudiosession/mediaserviceswereresetnotification
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/preparetoplay()
- https://developer.apple.com/forums/thread/685525
