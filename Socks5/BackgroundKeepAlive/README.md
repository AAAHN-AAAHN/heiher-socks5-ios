# Background services

The Background tab has two independent saved switches: Continuous location and
Loop silent WAV. Server controls, statistics and all five Hev patches are unchanged.

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

If activation or playback fails, the preference remains On and a single timer
retries after 1, 2, 4 and then at most one attempt every 8 seconds. A fresh system
event or foreground entry tries immediately. After success, a five-second health
check observes isPlaying and recovers an unnotified stop. It does not reactivate a
healthy session. Timer tolerance permits coalescing; the callback captures the
controller weakly, and Off cancels it before releasing the player. These checks
are distinct from the deleted five-second location modes.

## Persistence and limits

UserDefaults stores two booleans, written only when a user changes a switch.
On launch and foreground entry, the controller restores enabled services without
creating duplicates. Initial installation defaults to Off. The older app did not
persist choices, so enable the desired switches once after this upgrade.
Settings survive normal app restarts/updates, not app deletion. Diagnostic count
and time are not stored. This does not automatically start the SOCKS5 server.

No app code can run after process termination or while iOS has suspended it.
Audio activation can be refused, including under background/priority policies.
Retries run only while the process is scheduled; saved choices are restored on
the next app launch. No self-relaunch, uninterrupted-call guarantee, private API,
extra background-task loop or force-quit bypass is implemented or claimed.

## Verification

Tests/Background compiles the production controller body with scripted platform
doubles, checking permission handling, persistence, interruptions, retry limits,
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
