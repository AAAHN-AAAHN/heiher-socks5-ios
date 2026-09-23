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
is used. System-alert interruption avoidance is requested as a best effort.

The On choice is user intent, distinct from actual playback success. A single
one-shot Timer on the main run loop in common modes performs a healthy `isPlaying`
check after one second. If playback is stopped it attempts recovery. Failures retry
after one second, without backoff or an attempt limit; success retains one-second
checks. There is no second polling timer during recovery and no timer for each WAV
loop. Normal healthy checks do not reconstruct the player or reactivate the session.

Interruption notifications (including missing/unknown metadata) recreate the player
and attempt immediate recovery even if `isPlaying` was stale. Media service loss and
reset do the same. Route changes check and repair playback; the application's own
normal category-change notification does not recursively rebuild a healthy player.
A root-level ViewModifier owns the event subscriptions so leaving the Background
tab does not detach them. Returning to the foreground reconciles enabled services.

Unexpected completion retries immediately. Decoder failure is paced at one second
to avoid a synchronous error spin. Delegate callbacks arriving off-main are routed
to MainActor. Object identity rejects callbacks from replaced players. Timer identity
rejects delayed callbacks from cancelled timers. Explicit Off invalidates the timer,
clears player/delegate state, and deactivates audio. Neither an error nor an old
callback silently re-enables or permanently disables a user's choice.

## Persistence and integration

The isolated branch uses the two existing AppStorage preference keys, which makes
its switches complete and persistent without depending on the JSON feature.
The final release uses the exact same controller and screen but injects JSON-backed
bindings from SettingsStore. On first migration it consumes the two old keys and
removes them only after a successful JSON save. It does not run both persistence
systems in parallel. The controller itself contains no settings-file I/O.

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

## Current scoped change and environment

The 2026-09-23 update only moves Audio above Location and changes healthy playback
checks from two seconds to one. Immediate event recovery and one-second failure
retries remain unchanged. Healthy timer requests are twice as frequent; there is
still only one timer, and no measured battery/CPU impact is claimed. This branch
update is not merged into `release/integrated`.

Target use remains iOS 27.0 on a physical iPhone with SideStore standalone
installation or LiveContainer guest execution. The configured minimum iOS remains
17.2. This patch was checked using Swift 6.2.1 on Linux, controller/delegate platform
doubles, raw WAV validation and source-diff checks. No iOS SDK compile, IPA build,
SideStore installation, LiveContainer run or physical-device timing test was
performed for this patch. These limits are separate from historical checks below.

## Validation

`Tests/Background` compiles the controller body against platform doubles to exercise
permissions, identity guards, healthy checks, missing-resource errors, notification
metadata, one-second repeated failures, Off, and off-main delegates. The repeated
1000-failure check is one scenario with 1000 assertions, not 1000 independent device
tests. The Apple audio decoder uses the real asset on macOS. iOS compilation checks
the actual framework APIs. Phone calls, Bluetooth routes, lock-screen scheduling,
and energy consumption still require device tests.

References:
- https://developer.apple.com/documentation/corelocation/cllocationmanager/pauseslocationupdatesautomatically
- https://developer.apple.com/documentation/avfaudio/avaudiosession/interruptionnotification
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/numberofloops
