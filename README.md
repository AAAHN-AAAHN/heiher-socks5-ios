# SOCKS5 for iOS: background

This is the focused `feature/background` branch.
For the complete app use `release/integrated`; the shared app + engine baseline remains on `main`.

Build and verification: [instructions](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/background/docs/build-and-validation.md).
The following specification is also preserved verbatim at `docs/features/background.md`.

# Background services: continuous coarse location and silent audio recovery

## Purpose and scope

`feature/background` adds an opt-in Background screen and native services without
changing Hev's relay engine. Both switches are independent of server Start/Stop.
The aim is to keep the process eligible to execute while its SOCKS5 server is in use,
with concise native APIs rather than iSH emulation, Python polling, or Picture in
Picture. This is a sideload-oriented utility, not an App Store approval claim.

Only continuous location and silent WAV remain. Earlier held-open/five-second-read
and close/wait/reopen experiments were removed. The location state, callback count,
and last callback time remain visible. Coordinates are neither retained nor sent.

## Location implementation

One CLLocationManager exists while enabled. It is created on MainActor and delegates
on that run loop. Coarse/background options are configured before assigning its
delegate, so an initial authorization callback cannot start an unconfigured manager.
It requests `kCLLocationAccuracyThreeKilometers`, has no distance filter, permits background updates, shows the location indicator, and disables
automatic pausing. It calls `startUpdatingLocation()` only when needed, not on a
polling timer. iOS determines actual callback cadence and sensor use; coarse accuracy
is not a command to turn the physical GPS off or sample at an exact interval.

Permission requests are made only while the application is active, with a flag to
avoid duplicate requests. Both authorized-when-in-use and authorized-always states
can use the configured session. A new When-In-Use session waits until the app is
active; the root activation callback then starts it. A session already started in
foreground continues in background without a restart. Always authorization retains
its existing background-start behavior; actual OS delivery is not guaranteed.
Permission denial stops updates but preserves user intent. Authorization changes can resume the existing manager. Off stops it,
clears its delegate, and rejects stale callbacks by manager identity. Temporary
errors report status rather than disabling the saved preference.

Apple documents low accuracy with automatic pausing disabled as a way to retain
standard location updates more economically. This does not make the service free:
no iPhone battery benchmark has established a precise percentage saving.

## Audio state and events

A single AVAudioPlayer loops `Silence.wav` with `numberOfLoops = -1`. The session uses
`.playback`, `.default`, and `.mixWithOthers`. No microphone permission or recording
is used. System-alert interruption avoidance remains a best-effort preference.

Saved On is user intent, not a claim of successful playback. One common-mode,
one-shot main-run-loop Timer checks `isPlaying` every second. An observed stop
attempts recovery in that callback, without another initial one-second wait.
A new interruption or invalidation likewise attempts recovery immediately in its
MainActor handler, even if the old player still claims to be playing. Failed
activation, construction or play schedules the next attempt after one second,
without backoff, attempt limit or automatic Off. Healthy samples do not reactivate
or recreate the player. This is not a real-time timer or suspension bypass.

### Public signal coverage

The subscriber and handler share `BackgroundKeepAlive.audioNotifications`, avoiding
separate lists that can drift. On iOS 27 the registry contains all 13 playback-
relevant AVAudioSession notification names below, plus four lifecycle checkpoints.
The legacy interruption notification is deliberately retained alongside its new
replacements, including missing/unknown userInfo. Typed NotificationCenter messages
are alternative representations of these events, not extra signals to duplicate.

| Signal | Handling while Audio is On |
| --- | --- |
| `interruptionNotification` (legacy) | Recreate and attempt recovery, for began/ended and unknown or missing metadata. |
| `didBecomeInactiveNotification` (iOS 27) | Recreate and attempt recovery regardless of deactivation reason/context. |
| `resumptionRecommendationNotification` (iOS 27) | Recreate and attempt recovery; missing/negative advice does not erase saved On. System priority can still deny activation. |
| `mediaServicesWereLostNotification`, `mediaServicesWereResetNotification` | Discard stale audio objects, restore the session and attempt recovery. |
| `routeChangeNotification` | All route reasons reach playback reconciliation. Repair changed category/mode/options. A stopped existing player is retried even on a normal category-change event. |
| `didBecomeActiveNotification` (iOS 27) | Reconcile playback without rebuilding a healthy player. Suppress our own activation echo when a missing player already has a recovery attempt/retry. |
| `silenceSecondaryAudioHintNotification` | Reconcile playback; this foreground-only hint is not a guaranteed background end notification. The WAV is already silent. |
| `spatialPlaybackCapabilitiesChangedNotification`, `renderingModeChangeNotification`, `renderingCapabilitiesChangeNotification` | Reconcile playback, without reconstructing a healthy player solely for a rendering change. |
| `outputMuteStateChangeNotification`, `userIntentToUnmuteOutputNotification` (iOS 26+) | Reconcile playback without overriding mute/volume or declaring silence a playback failure. |

App will-resign-active, did-enter-background, will-enter-foreground and protected-
data-available notifications provide additional audio-only checkpoints. The existing
root did-become-active callback continues reconciling both enabled services. The
root owns subscriptions, not the Background tab. This is observation, not a request
for new background execution, and neither changes the saved switches nor the server.

Microphone-injection/input-mute notifications concern unused recording facilities;
AVAudioEngine/AVPlayer events do not describe this AVAudioPlayer. They are not added
as fake interruption coverage. Remote media commands are not audio-session
interruption broadcasts: no Now Playing/remote-command ownership is introduced,
which could interfere with the LiveContainer host or other media. Undelivered OS
notifications, process termination and events outside this session cannot be
observed by subscribing to more names. Polling and foreground reconciliation remain
the fallback when no stop notification arrives.

### Immediate recovery without recursive failure loops

The first unexpected completion or decoder failure after healthy playback now
recreates and retries immediately. A failed replacement that errors again before
one healthy timer sample belongs to the same recovery episode: preserve the pending
one-second retry rather than spin or push its deadline further into the future.
A healthy sample resets this pacing so the next independent failure is immediate.
There is no global throttle on genuinely new interruption notifications.

If setCategory, setActive, stop or play synchronously delivers another event or
player failure, an in-progress guard prevents recursive activation/play. An
invalidating event marks that attempt unsuccessful, and its retry remains one
second. A delayed own-category/active echo with no player does not bypass an already
scheduled failure retry. These are re-entry/echo protections, not ignored external
stopped-player events. Explicit Off wins even if it occurs during activation.

Delegate callbacks off-main are routed to MainActor. Weak player identity rejects
stale callbacks even after deallocation and address reuse; timer identity rejects cancelled callbacks. Off cancels the timer,
clears recovery pacing/player/delegate state, and deactivates audio. Initial/repeated
Off is a no-op when this controller is already disabled: applying saved Off must not
deactivate an existing LiveContainer host session. Off during category/preference
configuration, player disposal or activation also wins; a successful activation
that returns after Off is deactivated again before returning. The old player is
detached before stop can call back. Recovery may fail during a call or while iOS
denies activation; it does not defeat that policy.

## Persistence and integration

The isolated branch uses the two existing AppStorage preference keys, which makes
its switches complete and persistent without depending on the JSON feature.
The integration contract uses the same controller/screen interfaces with JSON-backed
bindings from SettingsStore. The existing release migration consumes the two old
keys and removes them only after a successful JSON save; it does not run both
persistence systems in parallel. This branch update has not been merged into that
release. The controller itself contains no settings-file I/O.

The Background screen places Audio above Location and Location state.
`BackgroundKeepAliveView` receives the controller and two bindings. It does not own
the server, statistics, JSON store, or whole tab hierarchy. `AppRoot` assembles the
active features. This separation removes the former all-features root from the
background module without redesigning its runtime recovery.

## Asset and limits

The preserved WAV is 844 bytes: 44-byte WAV header plus 800 zero PCM bytes, mono
8 kHz, signed 16-bit, 400 frames (50 ms). Every sample is exactly zero. The header
is necessarily nonzero to remain a valid WAV. Both raw-byte and AVAudioFile decoder
checks verify silence; the SHA-256 is
`26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e`.

Timers are scheduling requests, not real-time guarantees. If iOS suspends or kills
the process, callbacks and retries cannot execute. Interruption delivery itself may
be delayed until the app is scheduled. Saved On is reapplied on the next launch;
the app does not relaunch itself. A call may or may not allow reactivation. The code
continues retrying when it can execute, but cannot override iOS audio priorities.

## Supported versions, installation environments and current scope

- **Target use:** iOS 27.0 physical iPhone, SideStore standalone installation or
  LiveContainer guest execution. These are different runtime environments.
- **Minimum deployment target:** unchanged at iOS 17.2; this is not certification
  that every OS release has been tested. New 26/27 notifications are runtime-gated.
- **Build requirement for these symbols:** Xcode 27 / iPhoneOS 27 SDK. The branch's
  macOS CI runner now selects that toolchain. The app identity, entitlements,
  permissions, audio options, coarse-location parameters and WAV are unchanged.
- **Scope:** all Background-owned additions relative to main, including the public
  signals, audio/location lifecycle, root bindings, project/plist, asset, tests and
  README. The current audit also repairs initial Off/shared-session interference,
  Off during recovery and new When-In-Use foreground startup. Audio remains above
  Location. No BGTask, host patch, ID rewrite, extra timer, persistent diagnostic
  log or relay change is introduced.
- **No IPA requested:** a commit marked `[audio-checks-only]` runs only the isolated
  validation job. The production archive job is skipped, not called and discarded.
  The validation script type-checks sources but creates no app archive or IPA.
- **Actual checks:** the current local run uses Swift 6.2.1 Linux platform doubles,
  1030 existing controller assertions, four worker-delegate checks, 103 recovery
  assertions, 41 branch-wide lifecycle assertions and 15 callback-lifetime assertions
  (including scripted repeated
  decoder/completion callbacks and 2000 deterministic mixed state transitions).
  Counts include loop repetitions and are not independent physical-device tests.
  Historical and current SDK/CI results are recorded separately below.
- **Not performed:** physical iOS 27 SideStore/LiveContainer installation or
  interruption delivery, phone/Siri/Bluetooth/lock-screen tests, energy benchmarks,
  and release/integrated merging. No claim that every OS signal is always delivered
  or every attempted activation succeeds is made.

The added signal observers are a fixed-size list (13 session + four lifecycle
checkpoints on iOS 27), not new polling. Extra state is three Booleans for in-flight
invalidation and repeated-player-error pacing. Memory does not grow per event.
Frequent external notifications can cause more than one immediate attempt per
second; one second is the scheduled retry interval, not a global event-rate limit.
No battery or CPU saving is asserted without measurement.

The previous `f2b0ad7` update only reordered Audio and changed health checks to one
second. Its old common composition checker still required the obsolete two-second
literal and notification names physically in the view. That validator now checks
the shared registry and one-second policy; it does not reintroduce obsolete code to
satisfy string checks. Feature-specific validation is allowed to evolve, while
engine pins, the committed framework and production build script remain locked.

**README maintenance rule:** record minimum/target/tested OS separately, including
OS build, SDK/Xcode, installer/host version when actually known, tested source
commit/CI run, passed/failed/not-run scopes, costs and limitations. SDK type checking,
scripted tests and Simulator evidence never substitute for physical SideStore or
LiveContainer tests. Keep this README and its feature specification byte-identical;
preserve historical results with their own source/version rather than relabeling
old evidence as a new run.

## Historical no-IPA verification: c334ed0 (2026-09-23)

Tested commit: `c334ed060ac8d27081c74196dae544df5bff3a80`.
Tested tree: `8995bd73aea2ce4df10ae9bd8641262262a56696`.
GitHub Actions run: `35824844915`; test-only `audio-checks` job succeeded.
The normal `verify` archive/IPA job was intentionally skipped by the commit marker.
This completion text is a later documentation-only change, not another test run.

The actual toolchain was Xcode 27.0 build 27A266a, iPhoneOS SDK 27.0. All five
production Swift files passed `swiftc -typecheck -warnings-as-errors` for ARM64 with
the unchanged iOS 17.2 deployment target. This validates API names, availability,
types and SwiftUI wiring, but does not link an application or run it on an iPhone.
The tests ran on the macOS runner; no Simulator or physical iOS runtime was used.

The 1030 controller assertions, four off-main delegate checks and 103 recovery
assertions passed. Recovery tests exercise each registered notification, unknown
metadata, all known/unknown route reasons, immediate first decoder failure, repeated
failure pacing, stale callbacks, synchronous re-entry, Off during activation, and
single-timer ownership. The 1000 decoder/100 completion loops are scripted repeats,
not that many independent interruption scenarios or OS-generated events.

The actual production Combine publisher expression was also tested with real
Foundation/Combine and scripted audio/device boundaries. All 17 names delivered
once from main and once from a worker reached the handler on main: 34 deliveries.
Subscription cancellation detached it. This checks forwarding, not OS delivery
conditions or the lifetime of a hosted SwiftUI screen. Apple's AVAudioFile decoded
the original WAV into 400 zero samples. Baseline pin/framework preservation,
composition/style checks and whitespace checks passed.

Artifact `10734727873` was downloaded and inspected. Its SHA-256 is
`131d85c248b0fca074df347130eda5b7cfbe0a20cfe3a90703fb391fc20f05b5`.
All 53 recorded source-file hashes match the reviewed source tree. The artifact
contains logs and a source hash manifest, no IPA or app archive. Compared with
`f2b0ad7`, 40 of 50 existing tracked files remain byte-identical; ten files changed
and three test-only files were added. The location methods are byte-identical.
Only controller and view are changed production Swift files; the Xcode project,
Info.plist, AppRoot, server, WAV, source pins and build pipeline script are unchanged.
`Build/check.py` itself is no longer byte-locked to the baseline because its
feature checks were updated; the runtime/source/framework locks remain enforced.

No physical-device phone/Siri/Bluetooth interruption, iOS delivery timing, SideStore
signature/install, LiveContainer guest loading or actual audio priority arbitration
was tested. No installer or host version is claimed tested. Successful scripted
recovery is not proof that iOS will permit every activation or deliver every event.

## Complete Background-only audit (2026-09-23)

The input feature commit is `4b6f637eefb8a07547d63a17d5407cb4b9cd9f19`.
The excluded main baseline is `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
This audit reviews the Background delta, not the inherited SOCKS5 engine or unrelated
UDP/statistics/settings/icon features. It does not merge into `release/integrated`.
The seven existing branches remain the only branches; no audit branch is added.

### Reproduced defects and narrowly scoped corrections

| Finding | Correction and reason |
| --- | --- |
| Initial saved Audio Off called setActive(false), even when the controller had never used audio; repeated Off did so again. | Disabled-to-disabled updates now do nothing. Explicit On-to-Off still stops and deactivates. This avoids an unnecessary shared-session side effect in LiveContainer without changing the host or adding ownership hooks. |
| Off raised during category/preference setup, orphan disposal or a successful activation could be followed by another activation. Off during retry disposal could be overwritten with Waiting state and a timer. | Recheck intent at those boundaries, detach the old player before stop, and compensate an activation that completes after Off. No new persistent state or retry timer is required. |
| Delegate assignment preceded location configuration. An immediate authorization callback could start with defaults. | Apply the existing accuracy/background/pause options before attaching the delegate. No settings values are changed. |
| A new When-In-Use session could be started while backgrounded. | Defer that start to the existing foreground restore event. Do not stop an already running session or impose this restriction on Always authorization. |

These were reproduced with the actual old controller and strengthened scripted
boundaries: nine failing lifecycle assertions. This is code-path evidence, not a
claim that all nine failures were observed on the user's iPhone. The strengthened
session double tracks final active state, not just call counts; earlier tests had
missed active-after-Off even when the controller's switch and timer looked stopped.
The initial-delegate case intentionally exercises synchronous delivery as a boundary
condition, not a claim about every Core Location implementation's scheduling.

`LifecycleTests.swift` now covers the corrections, permission transitions, temporary
errors, stale delegates, repeated On/Off, configuration/activation/init/play failures,
independent audio/location switches and 2000 deterministic mixed transitions.
Existing 13 session/four lifecycle notifications, immediate new-event recovery,
one-second health/retry cadence, failure pacing and original WAV remain intact.
No diagnostic UI, disk logging, extra timer, thread, socket or global host patch is
added. Extra runtime work is a few intent checks at transition boundaries and, only
if activation succeeds after Off, one compensating deactivation. Energy is unmeasured.

`check_scope.py` verifies every unmodified main file byte-for-byte, the sole app
entry-point substitution, native source pins and unchanged native checker helpers,
project identity/deployment settings, two AppStorage bindings, one root subscriber,
plist modes/permissions/single-scene configuration, Audio-first order and README
mirror. This is source configuration verification, not proof of granted device
permissions. Commit-wide whitespace is checked against main, not just a clean
working tree. Test subprocesses have finite deadlines.

Only the Background controller changes in production. AppRoot, view, Info.plist,
Xcode project, WAV, server and all inherited runtime files are retained. Tests and
README/specification are updated; the existing checks-only CI path is reused.
No archive, IPA, physical iOS runtime or installer/host test is implied by type checks.

### Completed audit evidence

Tested commit: `247e91aacbe588cb1f39fdb5087d9608e91ade05`.
Tested tree: `421794e2d397f55e081990502c458f9dbdf57bb4`.
Run `35829002622`: `audio-checks` succeeded on the first run; the normal archive/IPA
job was deliberately skipped. Xcode 27.0 (27A266a), iPhoneOS SDK 27.0 type-checked
all five production Swift files for ARM64 at the unchanged iOS 17.2 minimum, with
warnings treated as errors and an empty type-check diagnostic log.

The runner passed 1030 controller, 103 recovery and 41 lifecycle assertions plus
four worker-delegate checks. Real Foundation/Combine delivered all 17 registered
names from main and worker threads (34 deliveries) and detached on cancellation.
Apple AVAudioFile decoded the original 400 zero samples. Source boundary, project,
permissions declarations, settings bindings, source locks and whitespace checks
passed. Exactly 33 inherited main files were byte-identical; the six intentional
main-file integration/configuration deltas were checked separately. The existing
80-assertion final audio-contract test also passed locally against this controller;
it was a local regression, not an additional CI or iPhone run.

Downloaded artifact `10736291871` SHA-256:
`4978c84d8f5a17d16728a8c68d91a52af296582722cc7326b8ae6e0b481dcbfd`.
All 55 source hashes match the reviewed tested tree. The artifact contains checks
and logs only, not an app archive or IPA. This completion text is a later
README/specification-only commit; production and test code are the tested bytes.
Relative to input `4b6f637e`, six existing files changed and two test files were
added; the other 47 original files remain byte-identical. No additional known
code-path defect was found within the reviewed scope. Physical interruption delivery,
SideStore signing/install, LiveContainer loading/host arbitration, background timing
and energy use remain untested; source verification is not device certification.

## Final revalidation: queued callback identity (2026-09-23)

Input: `fde5746be7d29113c8581d90385b252391f002c1`. The scope remains the Background
implementation relative to main, not the relay, other features or integrated release.

A further lifetime defect was reproduced: a worker delegate stored only the old
player's `ObjectIdentifier` while waiting for MainActor. After that object was
released, the allocator could reuse its address for a new player. The queued old
callback then passed the address comparison and unnecessarily restarted the healthy
replacement. Swift guarantees ObjectIdentifier comparisons only during the object's
lifetime. This is a code-path reproduction, not an observed user-device failure.
The previous mocks retained every player in an instances array, masking this case.

Only the completion and decoder delegate bodies change in production. Each captures
the callback player weakly and, on MainActor, checks the surviving actual object
against the current player with `===`. A deallocated player yields nil; a different
living player fails identity comparison. Current-player callbacks retain the same
immediate recovery, Off checks and repeated-failure pacing. No unsafe pointer, new
identity counter, unchecked Sendable wrapper, actor bypass, timer or persistent state
is added. Weak capture has normal ARC bookkeeping until callback disposal; discarded
players are not kept alive. No energy or CPU improvement is claimed measured.

`CallbackLifetimeTests.swift` adds 15 assertions with real worker/actor scheduling
and scripted audio objects. It explicitly releases the old test player, checks
current/living-stale/released-stale/Off paths and preserves the existing timer.
Allocator reuse is measured rather than required on every platform. Locally, reuse
occurred and the old controller failed the completion regression; a separate old
controller decoder probe also restarted the replacement. Both corrected paths
passed. Optimized local builds also passed the lifetime and 80-assertion audio
contract tests. These tests do not inject telephone or Bluetooth events on an iPhone.

Tested commit: `758a550aab7b8c6fb18d5a2b4c00f5cb936cde7e`.
Tested tree: `b5671a81f5eff4299bed3dfa411d4e034616f0e2`.
Run `35832101248`: `audio-checks` succeeded; archive/IPA `verify` was intentionally
skipped. Xcode 27.0 (27A266a), iPhoneOS SDK 27.0 type-checked all five production
Swift files at the unchanged ARM64 iOS 17.2 deployment target with warnings-as-errors.
The type-check and commit-whitespace logs are empty. The unchanged main-boundary,
source-pin, project/plist/root/settings checks passed, including 33 byte-preserved
main files. No app link, archive or IPA was performed.

The runner passed 1030 controller, four worker-delegate, 103 recovery, 41 lifecycle
and 15 new lifetime assertions: 1193 total, including scripted repetition. The 2000
mixed transitions and existing decoder/completion repetition remain part of those
scenarios, not independent device trials. Actual Foundation/Combine again delivered
34 registered events and detached on cancellation; AVAudioFile decoded 400 zero
samples. In the runner lifetime test, decoder address reuse occurred after one
allocation; completion address reuse was not observed within 20,000 allocations.
Both postconditions passed. This explicitly distinguishes observed reuse from the
non-reuse case rather than counting both as reproduced collisions.

Earlier run `35831753584` failed while compiling the new test's never-mutated local
weak variable under Xcode 27 warnings-as-errors. An immutable weak-capture probe
replaced that variable without dropping the deallocation assertion or suppressing
warnings. Production code did not change between that failed run and the successful
run. Its failure artifact is retained as failure evidence, not an SDK success.

Successful artifact `10737043024` SHA-256:
`5c136da52c4f217178462ad280acf97d70548b5358b0b7115bc5f2065415b665`.
All 56 recorded source hashes match the reviewed tested tree. This record is added
in a later README/specification-only commit; those two documents remain byte-identical.
The 13 session notifications, four lifecycle checkpoints, one-second polling/retry,
location policy, WAV, UI, AppRoot, plist, project, build pipeline and main engine
remain unchanged by the lifetime fix. Only this existing feature branch is updated;
no new branch, host change, BGTask experiment or integrated merge is introduced.

No other reproducible defect was found in the exercised revalidation paths. Actual
iOS 27 SideStore signing/install, LiveContainer guest execution and host arbitration,
OS-originated interruptions, lock-screen timing and power use remain untested. No
installer/host version or physical-device pass is claimed. Source and SDK checks
cannot establish that the system always delivers an event or permits playback.

## Validation

`Tests/Background` compiles the controller body against platform doubles to exercise
permissions, identity guards, healthy checks, missing-resource errors, notification
metadata, one-second repeated failures, Off, and off-main delegates. The repeated
1000-failure check is one scenario with 1000 assertions, not 1000 independent device
tests. The Apple audio decoder uses the real asset on macOS. iOS compilation checks
the actual framework APIs. Phone calls, Bluetooth routes, lock-screen scheduling,
and energy consumption still require device tests.

References (public API contracts, not device-test results):
- https://developer.apple.com/documentation/avfaudio/avaudiosession/didbecomeinactivenotification
- https://developer.apple.com/documentation/avfaudio/avaudiosession/resumptionrecommendationnotification
- https://developer.apple.com/documentation/avfaudio/avaudiosession/didbecomeactivenotification
- https://developer.apple.com/library/archive/qa/qa1882/_index.html
- https://developer.apple.com/documentation/foundation/timer
- https://developer.apple.com/documentation/corelocation/cllocationmanager/pauseslocationupdatesautomatically
- https://developer.apple.com/documentation/corelocation/cllocationmanager/allowsbackgroundlocationupdates
- https://developer.apple.com/documentation/corelocation/cllocationmanagerdelegate/locationmanagerdidchangeauthorization(_:)
- https://developer.apple.com/documentation/avfaudio/avaudiosession/interruptionnotification
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/numberofloops
- https://developer.apple.com/documentation/swift/objectidentifier


## Six-feature closure recheck (2026-09-24)

Input product/test snapshot: `9227a03461e5f1a72a2ffbed75cdd7724c2175fc`.
Fresh verification commit `22e284d4e86309be06b258a9f60f44bef8fc6351` has the
same tree `1d389daa6d94475dab7efe3ee89f69d05ebed0e1`. Run `35928260734`
passed on its first attempt; only the existing audio-checks job ran and the
archive/IPA job was skipped. The downloaded artifact `10780062749` SHA-256 is
`6709aacb2795fb7b4fc69b38169cc88c410213fd383eb62166dd2ae6aa9b2461`.
All 56 source hashes match the unchanged input. No runtime or test edit was needed.

The full 1193 assertions passed again: controller 1030, worker delegate 4,
recovery 103, lifecycle 41 and callback lifetime 15. Real Foundation/Combine
delivered all 34 main/worker notifications and detached on cancellation; Apple's
decoder confirmed the existing 400 silent samples. Xcode 27.0 `27A266a` with
iPhoneOS SDK 27.0 typechecked five production Swift files, with an empty diagnostic
log. Exact main boundary, plist/root bindings, Audio-first order and resource
identity checks passed. Repetitions are not independent physical-device trials.

The controller remains responsible only for the independent location/audio
services. The standalone root's two existing AppStorage keys supply user intent;
the integrated root can instead supply persistence-owned bindings. Neither
SettingsStore nor server-control is a dependency of this standalone feature.
The 13 session notifications, four lifecycle checkpoints, immediate detected-stop
recovery, one-second single-timer policy and bounded re-entry protections are
unchanged. No host patch, extra scheduler, new observer or polling path is added.

The repository-wide closure retains eight branches and leaves main/release
unchanged; earlier seven-branch statements above describe their historical runs.
Actual iOS 27 SideStore installation, LiveContainer host arbitration, telephone/
Bluetooth notifications, process suspension and energy use remain untested.
This result verifies the implemented paths and current SDK contracts, not
guaranteed delivery/activation while iOS refuses or suspends execution.

## Retained independent real-scheduling verification (2026-09-24)

The subsequently observed scheduling harness and its test-only compiler corrections
are retained, not reverted. Their purpose is distinct from scripted timer firing:
use actual Foundation Timer/RunLoop and Combine scheduling around the unchanged
production controller body and actual publisher expression. Audio and location
remain explicit doubles. No production observer, timer, thread, setting or recovery
state was added, and this test does not claim background execution permission.

Tested commit: `da9a8b615be0132097103118f65020ba76bf9a7e`.
Tested tree: `04140706a9350a38b033984f8901a0f0aed06859`.
Run `35941608803` succeeded; the normal app archive/IPA job was skipped. The five
new scheduling postconditions passed: failed activation retries with a real timer;
new queued resumption before the pending retry; no reactivation from healthy samples
or 100 restores; Off wins before worker-notification delivery; independent location,
canceled observers and controller release stay inactive. Recorded initial attempts
were approximately 0.0012, 1.0379 and 2.0458 seconds. These are host observations,
not a one-second real-time guarantee on a suspended iPhone.

The existing 1193 assertions, 34 real Combine deliveries/cancellation, 400 zero
WAV samples, source boundaries and actual Xcode 27.0 `27A266a` / iPhoneOS SDK 27.0
five-file ARM64 typecheck also passed. The first harness compilation had diagnosed
a test weak local and an actor-isolated notification referenced from a worker;
those test declarations were corrected without suppressing warnings, removing
assertions or editing production logic. The earlier failure is not an executed
successful scheduling test.

Downloaded artifact `10784863270` SHA-256:
`33500b40a820499c590134d33146d20ffead120aea9158408864a52f98ab3922`.
The recorded 57 source hashes identify the exact tested files. This completion
updates only README and its identical specification; the successful test/production
bytes are retained. Session attribution cannot be established from commit authorship,
so the retention decision follows source scope and executable evidence instead.

The original immediate detected-stop recovery, one-second health/retry schedule,
weak callback identity, Off priority and coarse-location startup policy remain.
No extra runtime cost is introduced by retaining test-only code; energy is still
unmeasured. Physical iOS27 SideStore/LiveContainer installation, real phone/Siri/
Bluetooth interruptions, lock-screen scheduling, host arbitration and OS refusal
remain outside these checks. No main/release change, new branch, app archive or
IPA is part of this closure, and the repository still has eight branches.

## Final audit-driver and evidence closure (2026-09-25)

A failed checks-only retry could retain a prior SUCCESS.txt. The actual old shell
was executed with a deterministic first-toolchain failure and reproduced that
stale marker. The entry now removes only its old success marker before validation.
Three isolated old/current-retry/current-first-failure cases check the nonzero exit,
marker state and preservation of prior diagnostic logs. No controller or resource
change is needed. The artifact now also contains source.zip, a Git source archive
rather than an application archive, so its full source manifest is reconstructable.

Tested commit: `3307a5fc1008c6f9aa7042a4abe854d705d9e154`.
Tested tree: `9cb37faa36840b1676c33e60c6ae072d356d0af5`.
Run `36055863671` passed audio-checks on its first attempt; the ordinary archive/IPA
job was intentionally skipped. All 1193 retained controller/recovery/lifecycle/
callback assertions, 34 real Combine deliveries and cancellation, five real
Timer/RunLoop scheduling postconditions and the three new driver cases passed.
The Apple decoder again confirmed 400 zero samples. Both released-player address-
reuse observations occurred in this run; these are scripted object-lifetime cases,
not phone interruptions. Five production Swift files passed Xcode 27.0 `27A266a`
and iPhoneOS SDK27.0 ARM64/iOS17.2 type checking with an empty diagnostic log.

Artifact `10832780858` SHA-256:
`ffbe79d98295eb19396df631b7a04ad90031be97370f76321ec3192689e93e4b`.
The downloaded ZIP passed integrity checks; all 58 source-manifest hashes matched,
and its source archive reconstructed the exact tested Git tree, including modes.
The runtime files and original WAV are byte-identical to the preceding owner.
Only test-driver/evidence handling changed before this successful run; this final
README and its identical feature copy add documentation after that run.

The target physical iOS27 SideStore and LiveContainer paths remain distinct from
native host/SDK tests. Installer/host versions, actual phone/Siri/Bluetooth events,
permissions, lock-screen survival and energy remain untested. The unchanged iOS17.2
minimum is not an all-version execution claim. No new polling, observer, production
state, host patch, main/release update, branch, app archive or IPA was introduced.
