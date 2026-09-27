# Continuous Background audio — interruption recovery revision

This revision retains the build9 design: one AVAudioPlayer loops the unchanged
50ms silent WAV indefinitely (`numberOfLoops = -1`), with one common-mode main
RunLoop timer for health checks or recovery. No finite 0.5s playback, 25ms gaps,
prepared-player pool, new QoS, or periodic player replacement is used.

The user-rejected `feature/background-cycled-audio` ref was removed in operation
run36347191102 from its observed68fa715f revision. This branch continues directly
from `feature/background` at bfc4656ad197aa8b8f0266d032ec72e964c25ba9; the cycled
implementation is not merged. Other feature refs, main, release/integrated and the
previous build9 IPA are not updated by this recovery revision. Branch removal is
not a rewrite of historical Git objects or deletion of old failure artifacts.
The temporary ref-removal workflow is replaced by read-only verification again.

## Environment and unchanged responsibility

Primary target: a physical iOS27/iPadOS27 device, separately installed with SideStore
or run as a LiveContainer guest. Configured minimum remains iOS17.2. A compiler's
accepted deployment target is not proof of runtime support across all versions.
Standalone signing/container/permissions and guest shared-process/session state are
different. Xcode direct installation and Simulator are not substitute environments.
The original four instructions remain exact in docs/top-level-principles.md.

Only Background owns this change. Its location methods, notification registry,
AppRoot, existing two AppStorage keys, event subscriber, server source, project/plist,
permissions, framework and source pins are preserved. No microphone, NetworkExtension,
BGTask, host patch, coordinate history, second persistence system or packet tracing
is added. Audio On/Off and continuous coarse location remain independent of each
other and the server. This standalone feature is not the six-feature integrated app.

The prior full specification and execution record remain at the immutable bfc4656a
README/docs/features/background.md and earlier history files. They are historical
results, not proof of this changed controller. README and this revision's feature
specification are kept identical.

## Why recovery changed

The exact build9 audit on2026-09-28 reproduced two policy defects: availability advice
unnecessarily discarded a healthy player or valid activation/preparation result;
general hints and repeated invalidations bypassed the nominal one-second retry.
The old tests encoded some of those policies, so merely rerunning them was not an
optimality proof. The new tests distinguish unchanged invariants from explicitly
superseded policy expectations, and retain exact-build9 negative controls.

Additional reviewed boundaries are lost/reset distinction, an absent reset/end
notification, configuration drift with a true isPlaying flag, late completions,
Off/reentry, and steady owner destruction. The response is a small extension of the
existing single-player/transition machinery, not a new audio engine or dispatcher.

## Event policy and immediate recovery

| Input | Current response |
| --- | --- |
| Healthy timer or ordinary rendering/mute/lifecycle hint | Keep the same player and session; inspect category/mode/options as well as isPlaying. |
| First decoder failure, unexpected completion, unnotified stop, actual inactive/began/unknown interruption | Recover immediately when no uncancelable operation owns the transition. A second failure before a healthy sample shares the existing retry budget. |
| Interruption ended or a resumption recommendation | Availability checkpoint, not resource invalidation. Preserve a healthy player and valid in-flight work. The first meaningful opportunity can expedite an existing failed episode; duplicates cannot spin. |
| iOS27 shouldNotResume recommendation | Do not erase saved On or stop healthy audio; do not bypass the ordinary retry deadline. Missing context preserves the existing explicit-On best-effort policy without forcing recreation. |
| Reset or resume after an invalidated in-flight operation | Mark old work unusable, drain its completion, then start at most one fresh attempt without an additional unnecessary one-second wait. |
| Media services lost | Stop old local output and cancel the normal timer. No immediate activation on loss or every duplicate hint. Retain On and one slow five-second availability probe. |
| Media services reset, positive resumption advice, foreground/explicit On after loss | Reevaluate immediately; stale resources never become valid merely because an old operation completed. |
| Missing media-reset notification | The five-second probe makes one serialized activation attempt. Failure retains slow probing; a fresh accepted activation returns to ordinary preparation and one-second health checks. |
| Own category/activation echoes | Do not duplicate work, cancel a retry or restart healthy playback. |
| Repeated failures/hints | One retry timer, unchanged deadline, no attempt limit or automatic Off; no event-frequency activation loop. |
| User Off | Stop locally now; cancel timer, reject stale results, and serialize release after outstanding activation/preparation. Off-On cannot overtake that release. |
| Off release rejected | Show failure without an Off retry loop; a repeated explicit Off can retry. |
| Owner destruction | Stop owned player and timer; best-effort release only after this owner requested activation. Pending operations use weak orphan cleanup. |

All normal health/retry intervals remain one second. Five seconds applies only to
known media-service unavailability: it avoids both high-rate futile calls and an
end/reset-only permanent latch. A resumed system normally sends an immediate event;
without it, availability may wait until that probe. The interval is a bounded policy,
not a measured Apple recovery latency. One Timer is reused, not two polling systems.

A first valid interruption is not intentionally delayed for a whole second. The
pacing applies to repeated failures before a healthy observation. Genuine user On
can retry deliberately. Duplicate automatic hints cannot repeatedly consume that
privilege. A successful healthy timer sample ends the failed episode. Explicit On received
after an in-flight operation was invalidated records a follow-up request: it waits
for that real completion, then retries immediately instead of adding another timer
delay. Repeated On during valid work still coalesces without duplication.

## Concurrency, resource use and limits

MainActor retains player/control state and On/Off ordering. iOS27 activation/release
uses native asynchronous completion APIs; pre27 synchronous setActive and player
prepareToPlay use the unchanged utility worker adapters. Preparation exclusively
owns the detached player until completion. No callback is treated as canceled merely
because it is late. A resumption during valid pending work does not invalidate it;
a reset during that work does. Local Off always wins over a late success.

Category/preference setup, player construction, play and stop remain in their existing
execution context. This task does not claim that every Apple call is nonblocking or
that all main-thread latency is removed. Actual SDK/UI advisory checks are separate
from the source/model results. A system call or completion that never returns cannot
safely be replaced by a concurrent duplicate operation; no speculative timeout opens
the in-flight gate. No host-wide session arbitration is introduced.

The healthy path adds only configuration reads and small state checks; it does not
create players, reactivate the session or emit logs each second. The five-second
probe runs only in known service loss. Additional state and owner cleanup are bounded.
No energy, throughput, thermal or latency improvement is claimed without measurement.

isPlaying plus configuration is not a physical output meter. Sampling the looping
50ms currentTime would alias with the one-second timer and is not added as a false
stall detector. User mute, rendering hints or system audio priority are not overridden.
The OS may refuse activation; an unscheduled/suspended/killed process cannot execute
its timers, replenish work or relaunch itself. Silent audio is not a general public
API guarantee of unlimited SOCKS server execution. Saved On is intent, not permission.
Apple's ordinary media-player guidance can require new user action after reset;
automatic best-effort continuation here deliberately retains this project's explicit
persistent-On contract rather than claiming that guidance mandates auto-resume.

## Verification contract

Reproduce from a full clean Git checkout:

```sh
python3 Tests/Background/run_checks.py
python3 Tests/Background/check_async_session.py
python3 Tests/Background/check_interruption_policy.py
# Xcode27 host:
bash Tests/Background/check_audio_sdk.sh
python3 Tests/Background/check_async_ui.py
```

The current-controller body is unchanged in tests apart from substituting the three
framework imports. Existing controller/delegate/lifecycle/authorization/async suites
remain. Expectations that every end/advice/loss forces immediate recreation were
replaced explicitly; Off, single-operation, one-player, stale-callback and independent
location assertions were not removed. The old read-only audit probes remain external
historical observations, not passing current correctness tests.

New scenarios cover healthy/in-flight positive and negative advice, repeated generic
and inactive events, missing metadata/end/reset, unavailable-service probes, drift,
first/repeated silent and decoder stops, reset storms, reentrant Off, cleanup, and
98 boundary/action/delivery combinations. A 12000-step deterministic sequence checks
single-operation/player/timer and eventual explicit recovery. A separate 12000-event
sequence ends 300 finite histories using only completions and existing timers:
saved On must recover without another explicit user request once the platform accepts
work. The policy driver has 34 current scenarios, ten exact-build9 negative controls,
and two exact-first-repair negative controls per Swift compiler mode. Repetitions are not
independent device trials. Exact-build9 negative controls must fail the repaired
properties; old failures are never counted as new-source failures.

Actual Foundation/Combine tests keep worker delivery and cancellation checks and
add a burst of ordinary notifications between real timer deadlines. The five-file
iPhoneOS27 SDK check retains warnings-as-errors and records the actual declarations.
The existing uninstrumented Simulator UI test, original deadlines and advisory scan
remain. Input/index/marker guards and common46-case native-input fixture remain.

### Execution status for this implementation

The first repair73e36a5b passed SDK/model checks in36348760076. Attempt1 of its
Simulator job failed during simulator readiness/cleanup before app execution;
attempt2 failed the unchanged initial Playing deadline. The early diagnostic commit
message incorrectly grouped both as Playing failures; their original artifacts take
precedence. Test-copy tracing in f33cf831/run36351187140 passed UI, with native
activation and off-main preparation completions observed. That instrumented success
neither proves the prior delay's internal cause nor replaces final uninstrumented
validation. The trace helper is removed; no tracing is linked in this candidate.

Local current suites, 34 recovery scenarios and both compiler modes pass. The exact
first repair fails the two new explicit-On-after-invalidation cases; this candidate
passes them without overlap or loss of Off priority. Actual final SDK/Simulator/CI
results must still be recorded against their tested commit and original artifacts. A successful earlier build9 or rejected cycled source is not
reused as this revision's result. No new IPA or release merge is part of this scoped
branch-only repair. Physical SideStore/LiveContainer installation, real calls/Siri/
Bluetooth, actual service resets, long-duration locked iPad behavior, power and
network throughput remain unperformed until explicitly recorded.

Primary contracts:
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptionrecommendation
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptioncontext
- https://developer.apple.com/documentation/avfaudio/avaudiosession/mediaserviceswereresetnotification
- https://developer.apple.com/documentation/avfaudio/avaudiosession/activate(options:completionhandler:)
- https://developer.apple.com/forums/thread/685525
