# Background services

The Background tab has two independently controlled switches: Continuous location and
Loop silent WAV. SettingsStore persists their values. Statistics and all five Hev patches are unchanged.

## Location

One CLLocationManager runs the standard continuous location service. There is
no polling timer, periodic reopening, requestLocation loop or location history.
The callback retains only a count and receipt time, then discards coordinates.

- desiredAccuracy: kCLLocationAccuracyThreeKilometers, not navigation accuracy.
- distanceFilter: kCLDistanceFilterNone; update timing is decided by iOS.
- allowsBackgroundLocationUpdates and showsBackgroundLocationIndicator: true.
- pausesLocationUpdatesAutomatically: false, preserving the continuous session.
- Request authorization in the foreground; accept When In Use or Always.
- A denial or temporary error does not switch off the saved preference.
  Authorization changes and foreground entry re-evaluate the existing manager.

Approximate accuracy reduces the requested precision. It does not guarantee a
particular sensor, interval, energy saving or uninterrupted app execution.
Apple documents coarse accuracy with auto-pause disabled as an option for
continuing background updates. This app does not need or store precise positions.

## Silent audio

The same bundled Silence.wav is retained: PCM, mono, 8 kHz, signed 16-bit,
400 frames (50 ms), 844 bytes including its header. All 800 PCM data bytes are
zero. The valid WAV header is not all zero. numberOfLoops = -1 performs native
looping; there is no timer per WAV repetition and no microphone permission.

The playback audio session mixes with other apps; it does not duck them or
force an output route. The alert-interruption preference is requested on a
best-effort basis. It does not suppress accepted calls or all system interruptions.

Interruption begin/end, route changes and media-service lost/reset notifications
immediately attempt recovery while the saved switch is On. The switch is the
user's persistent intent, not a mirror of isPlaying or shouldResume. Orphaned
players are replaced. Unexpected completion is restarted; decoder errors are
paced rather than recursively restarted. Own category-change notifications are
ignored to avoid feedback loops.

If activation or playback fails, the On intent remains and a single timer retries
every one second without backoff or an attempt limit. After success, a two-second
check observes isPlaying and recovers an unnotified stop. Retry checks also inspect
isPlaying, so a second timer is unnecessary. A healthy player is not reactivated.
Every interruption notification triggers recovery regardless of its metadata or
shouldResume flag; resetting the player also handles a stale true isPlaying value.
System events can prompt an earlier attempt. Own category-change notifications
cannot create reconfiguration loops; they preserve a scheduled check instead.

The timer runs in common main-run-loop modes. No intentional tolerance is added.
Only one timer exists; a stale timer callback cannot replace a newer timer. Off
cancels it, detaches the delegate and releases the player. Timers still depend on
iOS scheduling; one or two seconds is a requested cadence, not a real-time guarantee.

The controller and all player state belong to MainActor. Core Location delivers
callbacks on the main run loop where its manager was created; its legacy delegate
conformance uses @preconcurrency to express that documented runtime contract.
Audio delegates bridge to MainActor when needed, passing only player identity and
error information; stale callbacks cannot revive a stopped or replaced player.

## Persistence and limits

SettingsStore owns the single application JSON, including both background switches,
server settings and desired Start/Stop, and the last tab. This controller has no
separate preference store. Root-level observers stay active on every tab, and root
reconciliation applies saved choices at launch and after an import. Diagnostic
count/time are not persisted. See ../Settings/README.md for migration and export.

No app code can run after process termination or while iOS has suspended it.
Audio activation can be refused, including under background/priority policies.
Retries run only while the process is scheduled; saved choices are restored on
the next app launch. No self-relaunch, uninterrupted-call guarantee, private API,
extra background-task loop or force-quit bypass is implemented or claimed.

## Verification

Tests/Background compiles the production controller body with scripted platform
doubles, checking permission handling, interruptions, fixed retry cadence,
route/reset events, failure paths, stale callbacks and timer ownership. Only its
framework imports are substituted; tests do not enter the IPA. This is not an
actual phone-call or suspension test. The app itself is built with the iOS SDK.
The WAV is also decoded with Apple AVAudioFile and its sample bits checked.
Existing native TCP/UDP and statistics regression tests run unchanged.

## Apple references

- https://developer.apple.com/documentation/corelocation/cllocationmanager/pauseslocationupdatesautomatically
- https://developer.apple.com/documentation/avfaudio/avaudiosession/setactive(_:options:)
- https://developer.apple.com/documentation/avfaudio/handling-audio-interruptions
- https://developer.apple.com/documentation/avfaudio/avaudiosession/setprefersnointerruptionsfromsystemalerts(_:)
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/numberofloops
