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
on that run loop. It requests `kCLLocationAccuracyThreeKilometers`, has no distance
filter, permits background updates, shows the location indicator, and disables
automatic pausing. It calls `startUpdatingLocation()` only when needed, not on a
polling timer. iOS determines actual callback cadence and sensor use; coarse accuracy
is not a command to turn the physical GPS off or sample at an exact interval.

Permission requests are made only while the application is active, with a flag to
avoid duplicate requests. Both authorized-when-in-use and authorized-always states
can start the configured session. Permission denial stops updates but preserves
user intent. Authorization changes can resume the existing manager. Off stops it,
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

Delegate callbacks off-main are routed to MainActor. Player identity rejects stale
callbacks; timer identity rejects cancelled callbacks. Off cancels the timer,
clears recovery pacing/player/delegate state, and deactivates audio. Recovery may
fail during a call or while iOS denies activation; it does not defeat that policy.

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
  permissions, audio options, location behavior and WAV are unchanged.
- **Scope:** add the public playback signals above and fix stopped-category and
  first-decoder recovery. Audio remains above Location. No BGTask, host patch,
  ID rewrite, extra timer, persistent diagnostic log or relay change is introduced.
- **No IPA requested:** a commit marked `[audio-checks-only]` runs only the isolated
  validation job. The production archive job is skipped, not called and discarded.
  The validation script type-checks sources but creates no app archive or IPA.
- **Actual checks:** the current local run uses Swift 6.2.1 Linux platform doubles,
  1030 existing controller assertions, four worker-delegate checks and 103 recovery
  assertions (including repeated 1000 decoder and 100 completion callbacks).
  Counts include loop repetitions and are not independent physical-device tests.
  The same tests also passed in the test-only Xcode 27 run recorded below.
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

## Completed no-IPA verification (2026-09-23)

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
- https://developer.apple.com/documentation/avfaudio/avaudiosession/interruptionnotification
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/numberofloops
