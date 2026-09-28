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

### Preceding audit execution status (8fc29ed4)

Implementation and scoped validation are complete for tested commit
`8fc29ed478846828486ad9afcb69fe08ad52f63a`, Git tree
`8d400532a6fa1f8e00aadc6125b334fbcc6a4e5a`. Run `36365407358` is successful
on attempt 2. The closing commit changes only this README and the identical feature
specification. The remaining 72 of 74 tracked paths, including production, tests,
workflow and assets, are byte/mode-identical to that tested source. Controller blob:
`0224ecec67a7c454d7943affc1790542dee13386`; controller SHA-256:
`c6217c53f37251ab3cde42fc978512a281abd1c86adb555050ec157f74c280a7`.

| Evidence | Actual result and boundary |
| --- | --- |
| Exact-source recovery policy | All 35 current scenarios pass in debug and optimized modes, including 98 reentry combinations, 12000 mixed transitions and the separate 12000-event/300-history automatic recovery sequence. |
| Mixed-notification regressions | Deadline, storm and 1352-pair matrix pass with 9, 611 and 23896 assertions per compiler mode. Exact pre-audit source fails deadline/storm with 3/4 observed failures; those are retained negative controls, not current-source failures. |
| Earlier negative controls | Ten build9, two first-repair and one pre-interval-change scenario per mode retain their expected failures and historical timing assumptions. |
| Existing regression suites | Controller/delegate, recovery, lifecycle, callback lifetime and 49 current authorization checks pass. Async session 38 checks/3000 transitions and preparation 22 checks/3000 transitions pass in both compiler modes. Historical authorization control retains 28 expected failures. |
| Foundation/Combine and worker boundaries | All 34 main/worker deliveries and cancellation pass. Real scheduling fixtures cover failure pacing, immediate opportunity, healthy preservation, lost-service probing and Off. Observed activation times 0.00137/0.50858/1.05069 seconds and loss-probe times 2.72847/3.25339/3.88186 seconds are host observations, not exact 500ms guarantees. Original blocking/implicit-preparation and utility-helper controls pass. |
| Apple SDK and asset | Five production Swift files typecheck for ARM64/iOS17.2 against iPhoneOS27 with warnings-as-errors and empty diagnostics. AVAudioFile validates all 400 silent PCM samples. |
| Guards and provenance | The 46 common input/marker cases, 37 audit-entry cases, original marker controls, source pins, main ancestry, composition and clean worktree/index checks pass. |
| Uninstrumented Simulator | iPhone 16, iOS27.0 build24A434: the original XCTest passes with 0 failures and 0 skips, 111.254 seconds case time. On/Off, rapid choices, tabs and saved-intent relaunch are checked; original Playing/Off screenshots were inspected. |
| Advisory/cleanup | The targeted main-thread audio advisory is absent in the completed console and xcresult. runtimeWarnings and cleanup are empty; other tool/framework diagnostics are not claimed absent. |
| Native archive/IPA | The generic verify/archive job is intentionally skipped by audio-checks-only, not counted as passing. No IPA or release merge is produced. |

SDK and Linux results are from attempt 1; only the Simulator job was rerun on
attempt 2. All original ZIP digests/CRCs and the three matching source archives were
independently checked. The complete 74-file Git tree was reconstructed using Git
file-type/executable modes, with unspecified regular ZIP modes normalized to100644;
a raw-ZIP-mode draft did not match and was corrected before accepting the result.
Local Linux/Swift6.2.1 additionally recompiled the exact controller (framework imports
only substituted) for all35 policies, all three mixed groups and both pre-audit
negative groups in debug/optimized modes, plus eight existing current fixture
executables in debug. This supplemental offline replay does not replace the complete
original CI drivers, historical Git checks, SDK, or Simulator execution.

Recorded Apple host: Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428. The uninstrumented source contains no temporary
tracing helper, altered UI predicate, relaxed timeout or suppressed advisory gate.

| Original artifact | SHA-256 |
| --- | --- |
| SDK 10947083221 | 6591092244ff0a72bc8b4277d82a9109b506534fcaa3e83d2fa2342b1eaa3a75 |
| Linux 10946762860 | 909aedc8657b1370c1633193e8133a82f30291c064b77201e1902820b1aa0937 |
| UI attempt2 10947518070 | f701d6278ac86ccb094f6c0656d015ccf2d122a2859a6b503801fc39eefd428f |
| Retained UI attempt1 10947077665 | 5f7bcc837d659b003345b1232d5e8db83e2ea283300b3a18cec730ff0b9616a2 |

Attempt1 failed the original Playing-state wait (one failed XCTest,87.199seconds)
with cleanup completed. The identical-source attempt2 passed the original gates.
This retry does not erase the first failure, establish its internal cause, or repair
all external startup latency. The earlier10.78837second prepareToPlay observation
belongs to its separate diagnostic run, not this attempt. No speculative overlap,
new player pool, high QoS or timeout relaxation is introduced to manufacture a pass.

No further controller defect was reproduced within the inspected source and finite
recovery scenarios after the mixed-signal repair. This is scoped code/validation
completion, not proof of every possible platform event history, fixed maximum
recovery time, continuous physical output, or unlimited background execution.
The previous interval-only completion record is now posted above; no documentation
upload remains pending. Only feature/background advances; the deleted cyclic ref
stays absent and the other seven branches and build9 release/IPA remain unchanged.

Physical iOS27 SideStore installation, LiveContainer guest execution, real calls,
Siri, Bluetooth, actual media-service resets, long locked-iPad operation, power,
latency and throughput remain unperformed. Neither mocks nor Simulator replace them.

Primary API contracts (not execution evidence):
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptionrecommendation
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptioncontext
- https://developer.apple.com/documentation/avfaudio/avaudiosession/mediaserviceswereresetnotification
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/preparetoplay()
- https://developer.apple.com/forums/thread/685525

## Final independent re-review — 2026-09-28

The review baseline is `cbb82a6cdcda981abb1f41a64d2656bb823f0af2`. The new tested
commit is `1911d5bc21d719cc57f21c658310dcade144148b`, tree
`a2a70dea7adcb8da0c02bbfd614ea42329538328`. No additional production defect was
reproduced in this review. All app code, notification membership, UI, project/plist,
assets, native framework, workflow, timing and QoS remain byte/mode-identical to
cbb82a6c. Existing recovery behavior was not rewritten merely to produce a change.
Controller blob/SHA-256 remain `0224ecec67a7c454d7943affc1790542dee13386` /
`c6217c53f37251ab3cde42fc978512a281abd1c86adb555050ec157f74c280a7`.

Only three test paths changed before validation: `FinalRecoveryTests.swift` and
`check_final_recovery.py` were added under `Tests/Background`; three lines connect
the latter to the existing policy driver. They share the existing PlatformMocks,
not another recovery implementation. These files are not part of the app target.
The closing documentation commit changes only README and the matching feature
specification; the other 74 of 76 tested paths are preserved. Device runtime cost
from these test additions is absent; host/CI test work increases.

Additional tests enumerate all 69,984 ordered triples from 18 inputs, six initial
phases and accepting/rejecting platform responses. Inputs include timer delivery
and operation completion between invalidations, missing/malformed advice, On/Off,
configuration drift, decoder/finish callbacks and silent stops. A separate set of
65,536 events from 16 seeds contains 1,024 checkpoints that must recover saved On
using only existing timers/completions after simulated failures end. It also covers
missing assets, initialization/play/category failures, stale callbacks and a
contradictory success/error response. Per compiler mode the two groups perform
3,536,982 and 313,371 assertions. These are finite modeled histories, not independent
physical interruptions or a proof over every possible history.

The timer guard scans all production Swift: one 0.5-second constant, five calls to
one scheduling helper, one Timer constructor using that constant, no per-state
interval override or alternative app polling timer. A test-copy mutation to 1 second
must fail this guard's runtime invariant. It is intentionally invalid test input,
not a production change or a newly discovered production bug. Off and uncancelable
operations still do not create repeated platform calls. Native I/O timeouts and test
process deadlines are unrelated and unchanged.

Fresh run `36369375869` results:

| Evidence layer | Result and scope |
| --- | --- |
| Added ordered-triple and long-history tests | Both compiler modes pass all 69,984 histories and 65,536 events/1,024 liveness checkpoints on the CI Linux and Apple hosts. |
| Mutation and historical controls | A deliberate 1-second source copy fails the half-second invariant in both modes. All prior recovery and mixed-signal negative controls retain their expected failures. |
| Existing regression suites | The original 35 policy scenarios, 1,352-pair matrix, reentry/mixed sequences, controller/delegate/lifetime/authorization, async-session/preparation and source-scope drivers pass. |
| Foundation/Combine | 34 main/worker notification deliveries and cancellation pass. Failure-pacing and loss probes use the real RunLoop with mocked audio: activation times 0.00157/0.51396/1.14685s and loss times 2.29441/2.84106/3.36004s are host observations, not a real-time guarantee. |
| Apple SDK and WAV | Five Swift files typecheck for ARM64/iOS17.2 against iPhoneOS27, warnings-as-errors, empty diagnostic log. AVAudioFile confirms all 400 silent PCM samples of the unchanged 50ms asset. |
| Uninstrumented Simulator, attempt 3 | Original iPhone16/iOS27.0 build24A434 XCTest passes: 1 case, 0 failures, 0 skips, 114.623 seconds. Playing/Off screenshots inspected. Targeted audio advisory absent; runtimeWarnings and cleanup empty. |
| Overall scoped run | Run36369375869 concludes success on attempt3. SDK/Linux are original attempt1 results; only the failed UI job was rerun. |
| Native archive/IPA and physical targets | Generic verify/archive intentionally skipped by audio-checks-only. No new IPA/release merge; physical SideStore/LiveContainer and actual device interruptions not performed. |

The original SDK and Linux ZIPs came from attempt 1; only the failed Simulator job
was rerun. Every downloaded original ZIP was SHA-256/CRC checked. Source archives
were compared against all 76 tested paths and modes, and the Git tree above was
independently reconstructed. Local Linux/Swift6.2.1 additionally passed the new
debug/optimized tests and mutation controls, existing current fixtures and policy/
mixed regressions. A clean extraction of the CI source ZIP reran the new standalone
driver in both modes. Offline tests do not substitute for actual Apple execution.

| Original artifact | SHA-256 |
| --- | --- |
| SDK 10948676773 | a47257c98d704c4c7c272357c400fad7fd4c0d06900476f0bae308bebadd9446 |
| Linux 10949140923 | 912ffb84e8dfffe3481f32cb8dbdd01497f38b965f0f2dcb491efd2a0a1e7e01 |
| Retained UI attempt1 10948219710 | 1ee2f4127a83178169922707c38bc27a3b18dd947448cd8ee86a23cf987939ac |
| Retained UI attempt2 10949300216 | 3c300f720ecb2aa58a7a6279113e08584d885e698a308cbbba9815044e7a6d35 |
| Successful UI attempt3 10949431169 | 7336625d70955a33629f47b58694a3e2433df6249a87718e6ca22f6b6a8427ce |

Attempt 1 passed initial repeated On/Off and Playing observation, then failed the
original Playing wait after saved-On relaunch: one XCTest failure, 111.949 seconds,
cleanup empty. No internal cause was established by that uninstrumented log. The
previous 10.78837-second prepareToPlay observation belongs to its separate historical
diagnostic and is not presented as this failure's cause. Attempt 2 instead lost the UI snapshot/helper connection at the initial switch lookup before audio On (one failure, 89.916 seconds, cleanup empty). Its termination cause was not established. Attempt 3 passed the unchanged source and original gates.

No timeout, predicate, advisory scan or production source was changed for the retry.
A passing retry does not erase the failed run or establish bounded startup latency.
No fixed 500ms execution/recovery guarantee, physical-output certification, or
unlimited background execution is claimed. Physical iOS27 SideStore and LiveContainer
runs, actual calls/Siri/Bluetooth/service resets, long locked-iPad operation and
performance/power comparisons remain unperformed. Other seven branches and build9
release/IPA remain unchanged; the rejected cyclic branch stays absent.

Standalone reproduction (Swift compiler required, Git history not required):

```sh
python3 Tests/Background/check_final_recovery.py all
```

The existing full policy/ancestry drivers still require historical Git objects.
