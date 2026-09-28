# Continuous Background audio — unified 0.5-second checks and retries

This revision retains the build9 design: one AVAudioPlayer loops the unchanged
50ms silent WAV indefinitely (`numberOfLoops = -1`), with one common-mode main
RunLoop timer with one 0.5-second interval for health checks, failure retries and
media-service availability probes. No finite 0.5s playback, 25ms gaps,
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
| Reset or resume after an invalidated in-flight operation | Mark old work unusable, drain its completion, then start at most one fresh attempt without an additional unnecessary retry wait. |
| Media services lost | Stop old local output and cancel the normal timer. No immediate activation on loss or every duplicate hint. Retain On and one 0.5-second availability probe. |
| Media services reset, positive resumption advice, foreground/explicit On after loss | Reevaluate immediately; stale resources never become valid merely because an old operation completed. |
| Missing media-reset notification | The 0.5-second probe makes one serialized activation attempt. Failure retains the same interval; a fresh accepted activation returns to ordinary preparation and 0.5-second health checks. |
| Own category/activation echoes | Do not duplicate work, cancel a retry or restart healthy playback. |
| Repeated failures/hints | One retry timer, unchanged deadline, no attempt limit or automatic Off; no event-frequency activation loop. |
| User Off | Stop locally now; cancel timer, reject stale results, and serialize release after outstanding activation/preparation. Off-On cannot overtake that release. |
| Off release rejected | Show failure without an Off retry loop; a repeated explicit Off can retry. |
| Owner destruction | Stop owned player and timer; best-effort release only after this owner requested activation. Pending operations use weak orphan cleanup. |

All scheduled audio health checks, recovery-failure retries and media-service-loss
availability probes use the single `audioCheckInterval = 0.5` constant. No state
retains a one- or five-second override. Immediate event-driven recovery remains
immediate: 0.5 seconds is a scheduling interval, not a delay imposed on every event.
Off still has no retry timer; an uncancelable pending operation must finish before
another can start. One Timer is reused, not multiple polling systems.

A first valid interruption is not intentionally delayed for a timer interval. The
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
create players, reactivate the session or emit logs on each check. Service availability probing
still runs only in known service loss. Additional state and owner cleanup are bounded.
No energy, throughput, thermal or latency improvement is claimed without measurement.

isPlaying plus configuration is not a physical output meter. Sampling the looping
50ms currentTime would alias with the 0.5-second timer and is not added as a false
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
work. The policy driver has 35 current scenarios, ten exact-build9 negative controls,
two exact-first-repair negative controls and an exact pre-interval-change control
per Swift compiler mode. Historical recovery controls retain their original interval
expectations so timing differences cannot falsely satisfy a recovery-defect check. Repetitions are not
independent device trials. Exact-build9 negative controls must fail the repaired
properties; old failures are never counted as new-source failures.

Actual Foundation/Combine tests keep worker delivery and cancellation checks and
add a burst of ordinary notifications between real timer deadlines. The five-file
iPhoneOS27 SDK check retains warnings-as-errors and records the actual declarations.
The existing uninstrumented Simulator UI test, original deadlines and advisory scan
remain. Input/index/marker guards and common46-case native-input fixture remain.

### Execution status for the 0.5-second revision

This interval-only revision is based on `7c410b973181ea8acfeab46a695098268f854498`.
Production changes are confined to the shared scheduling constant/helper and the
Audio footer. State classification, immediate recovery, notification coalescing,
Off priority, infinite playback, all location code, source pins and QoS are unchanged.
Compared with the preceding policy, requested healthy/retry wakeups double (1s to
0.5s), and unavailable-service probes increase tenfold (5s to 0.5s). Actual operation
completion and scheduling can extend these intervals; these are not measured CPU,
battery or recovery-speed improvements. No busy loop or overlapping work is added.
Current local and remote validation results will be recorded for the exact changed
source after execution. Previous results below are historical, not current evidence.
No new IPA or release integration is requested by this interval-only change.

### Historical evidence — preceding 1-second / 5-second revision


Implementation and the scoped Background validation are complete at tested commit
`6f1ab4fcdd1073b18711112224ef990ab9281cc0`, tree
`7a412e5347b90b6725343c822c5fc17888e05a39`. Workflow `36357672450`
finished successfully on attempt 2. The final documentation commit changes only
README.md and this feature specification: the other 70 tracked paths, including
production, tests, workflow and assets, remain identical to the tested 72-file tree.
The controller blob is `44bf6de00a9d769adbae2d1a0a7e0c4a832d4379`;
its SHA-256 is `15a6f853ff7ca0e00fb15976203308c024e5d631d59c499b161cd605f14eba4c`.

| Evidence layer | Actual result and scope |
| --- | --- |
| Exact-source Linux recovery policy | 34 current scenarios in debug and optimized modes pass; 98 reentry combinations, a 12000-transition mixed sequence and a separate 12000-event/300-history automatic-recovery sequence are included, not independent device trials. |
| Negative controls | Ten exact-build9 and two exact-first-repair scenarios per compiler mode fail the repaired properties as expected. These retained failures are not current-source failures. |
| Existing controller and transition tests | 1030 controller checks, 85 recovery assertions, 41 lifecycle assertions, 15 callback-lifetime assertions, 49 authorization assertions and worker-delegate checks pass. Async session 38/3000 transitions and preparation 22/3000 transitions pass in both modes. Historical authorization control retains 28 expected failures. |
| Foundation/Combine and worker helpers | 34 main/worker notification deliveries, cancellation, five real scheduling conditions and exact old blocking/implicit-preparation controls pass. Observed failed-activation times are 0.00116, 1.01696 and 2.04028 seconds; these are host-fixture observations, not device latency guarantees. |
| Shared validation guards | 46 common input/marker cases, 37 audit-entry cases, original marker controls, main ancestry, source pins, composition and clean worktree/index checks pass. |
| Apple SDK | Five production Swift files typecheck for ARM64/iOS17.2 with iPhoneOS27 and warnings-as-errors; diagnostic log is empty. Apple AVAudioFile decodes all 400 zero samples of the unchanged 50ms WAV. |
| Uninstrumented app execution | iPhone 16 Simulator, iOS27.0 build24A434: one original XCTest case passes, zero failures/skips, 116.249 seconds case time. Repeated On/Off, saved intent/relaunch, rapid changes and tab changes pass. Playing and Off screenshots were inspected. |
| Advisory and cleanup gates | Targeted main-thread audio advisory is absent in completed console and xcresult. runtimeWarnings and cleanup are empty. This is not a claim that every framework warning or every possible hang is absent. |
| Generic native archive/IPA job | Skipped by the explicit audio-checks-only scope, not represented as passed. No new IPA or release merge is produced by this branch-only repair. |
| Physical target environments | SideStore independent installation and LiveContainer guest execution, actual calls/Siri/Bluetooth/media-server reset, long locked-iPad operation, power, latency and throughput remain unperformed. |

The final run's SDK and Linux artifacts were produced on attempt 1; only the failed
Simulator job was rerun on attempt 2. They are not claimed to be three newly executed
attempt-2 jobs. Original ZIP digests and CRCs were verified. The SDK/Linux/UI source
archives have identical file bytes/modes and the expected commit comment. Independent
Git-tree reconstruction from all 72 paths reproduces the tested tree above. Local
Linux/Swift6.2.1 additionally reran the eight current fixture executables and all
34 policy scenarios plus 12 historical negative controls in both compiler modes.
Those offline fixture runs do not replace Apple SDK or actual Simulator execution.

Recorded Apple host: Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428. The CI Linux host uses Swift6.4.
The Simulator executable SHA-256 recorded by CI is
`f28d40a9655e11b982ec68c7a5a661100120497721578994ad4e4b64fa9969d2`.
Its executable is not separately distributed in the artifact for an independent
local rehash; the source and original artifact archives were independently rehashed.

| Original artifact | SHA-256 |
| --- | --- |
| Final SDK 10943683861 | 7a06f92ee982b5f2519c60ce8613c0b1f4fdc294258314ed70068dfa2e56ab5b |
| Final Linux 10944726138 | a648f4f06ad61356778d02be7f5f6758a90d4ee18fa99fe394534493cae5a556 |
| Final UI attempt2 10944594234 | cb74fea6ad67f71e509cc367ec886efbe602eb8d5ea5013328aa06ded5e0a438 |
| Retained UI attempt1 failure 10944573245 | e3000b21c09f92dc8eb7b4536e2d023d17cfc4030b1f370519ef456ba865560e |
| Diagnostic-only UI 10944137752 | 3542b9c8b782aa2ddeae57ba3aaf2a99c6ee9299d5ed0996ad3765f62c62ed2c |
| Cycled-ref removal 10940424430 | 91d3b6c13a207472a14bfc70844306594ad115b4e011ee7f1cd2ea8b60a4af48 |

### Retained failures and unresolved external timing

The first repair73e36a5b passed SDK/model checks in36348760076. Its Simulator
attempt1 failed readiness/cleanup before app execution; attempt2 failed the original
initial Playing deadline. A diagnostic commit message initially grouped both as
Playing failures; the original artifacts and this correction take precedence.
Tracing in f33cf831/run36351187140 passed only with test-copy instrumentation.
The later d3dde5c9 uninstrumented run36352163355 passed; d7876d04 then changed only
the explanatory Audio footer and received fresh tests rather than inheriting that
verdict without qualification. Earlier readiness and Playing-wait failures remain
failure evidence; successful retries do not erase them or establish their every cause.

Diagnostic caa0e3b0/run36356990709 isolated a slow boundary on saved-On relaunch:
prepareToPlay() on the utility worker ran from device uptime3689.6040882083335 to
3700.3924599166667, approximately10.78837 seconds, and returned true. Activation had
already succeeded. No overlapping operation or notification/retry loop occurs in
that recorded segment. This locates an observed delay inside the Apple call; it does
not identify its internal cause, prove that all prior failures shared it, or establish
a fixed worst-case startup time. Instrumented success is not final product evidence.

Final6f1ab4fc contains no trace helper or production telemetry and has exactly the
same tree as d7876d04. Run36357672450 attempt1 again stopped at Simulator readiness/
cleanup before application execution. Attempt2 reused the identical source and
passed all original UI deadlines, advisory and cleanup gates. No predicate, timeout,
warning scan, host, entitlement or runtime workaround was changed to manufacture a
pass. The completion above is code/policy and scoped-validation completion, not a
promise that audio always resumes within one second or that every possible OS-level
interruption has been physically reproduced. A never-returning external operation
and suspension still cannot be bypassed safely by overlapping another operation.

The rejected cyclic ref is absent; the repository again has the original eight
branches. Only feature/background advanced. Main, the other five feature branches,
release/integrated at8577bb1f and the previously supplied build9 IPA remain unchanged.
The repaired Background source is therefore not silently present in that old IPA.

Primary contracts:
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptionrecommendation
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptioncontext
- https://developer.apple.com/documentation/avfaudio/avaudiosession/mediaserviceswereresetnotification
- https://developer.apple.com/documentation/avfaudio/avaudiosession/activate(options:completionhandler:)
- https://developer.apple.com/forums/thread/685525
