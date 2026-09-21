# Background keep-alive experiments

This module is separate from the original server UI and the unmodified Hev core.
The app entry point changes only from ContentView() to BackgroundKeepAliveRoot().
All switches default to off on each launch. Server Start/Stop and these switches
are independent. Turn the switches off when the experiment is finished.

## Location modes

Only one location mode can be enabled at a time, so comparisons are not masked
by a second live location session. All location work runs on the main run loop.
Coordinates are discarded; only a read count and receipt time are displayed.

1. Continuous: keep a CLLocationManager session open and consume each callback.
2. Held: keep that session open, consume an update, wait at least five seconds,
   then accept the next delivered update. This does not set the GPS sampling rate.
3. Cycled: start a session, consume one update, stop/release that manager, wait
   five seconds, and create a new session. Timers cannot wake a suspended app;
   this mode can stop progressing in the background without another activity.

These are native equivalents, not shell commands or a real /dev/location device.
Requested accuracy is Best, with no distance filter. Automatic location pauses
are disabled; mode 3 still explicitly stops its session. iOS controls actual
location delivery and hardware use. A delivered update can be cached by iOS.
Select a mode while the app is in the foreground and grant location access.
Always authorization is requested; iOS may initially grant only When In Use.
For restart experiments, enable Always in Settings when it is offered.
Neither authorization nor these modes prevents a system resource termination.

## Silent audio

Silence.wav is 50 ms of mono 8 kHz, signed 16-bit PCM with every sample equal to
zero (844 bytes including the WAV header). AVAudioPlayer loops it with -1 loops.
The playback session mixes with other audio; no microphone access is requested.
There is no per-loop timer, busy loop, remote-control registration, or PiP.
Interruptions pause playback. Resume is attempted only when iOS supplies
shouldResume, or on foreground return after a recoverable audio-service reset.
Errors are displayed rather than retried in an unbounded background loop.

## Build and scope

Use .github/workflows/build-keepalive-ipa.yml. The core is pinned to the same
upstream commit as the previously tested native IPA. The workflow verifies the
unchanged original ContentView, the added permission keys, ARM64, and WAV silence.
The resulting IPA is unsigned and must be signed by SideStore for installation.
This is a private experimental build, not an App Store compliance claim or a
guarantee of indefinite execution. Test location and audio on an actual device.
