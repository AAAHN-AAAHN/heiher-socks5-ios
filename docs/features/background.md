# Independent continuous audio and location services

## Purpose and scope

This feature supplies explicit, independent controls for continuous silent audio and coarse location updates. The root-owned controller preserves user intent and performs best-effort recovery while the operating system allows the process to execute. It does not grant unlimited background time, prevent termination or automatically relaunch a terminated application.

Background services are independent of Server Start/Stop and tab visibility. The standalone root persists its two choices through AppStorage; the integrated root supplies the same choices from its single JSON settings owner. `BackgroundKeepAlive` itself does not read storage or invoke the Hev server.

In the standalone branch, the AppStorage keys are `background.continuousLocation` and `background.silentAudio`, both initially false; its Server/Background tab selection is not saved by this feature. In release, both choices are fields in the shared AppSettings snapshot and the root applies them only when the corresponding controller value differs. Neither route adds a second writer inside BackgroundKeepAlive.

## Functional behavior

### Continuous location

One CLLocationManager is configured with three-kilometer desired accuracy, no distance filter, allowed background updates, a visible background indicator and automatic pausing disabled. The configuration is established before assigning the delegate because authorization callbacks can arrive immediately.

Permission requests are deduplicated and issued only while the app is active. A new When-In-Use background session must start in the foreground; an already-started session is not repeatedly restarted merely because the app changes lifecycle state. Always authorization retains its supported startup path. Undetermined, denied, restricted and unavailable authorization stop obsolete updates or wait as appropriate without erasing the saved On preference.

A valid nonempty update from the current active manager increments the diagnostic callback count and records a read time. Coordinates and a location history are not stored or transmitted. Temporary location errors remain visible while retaining intent. Off stops updates, detaches the delegate, releases the manager and rejects stale callbacks from a different manager. The diagnostic count is not a promise of a fixed sensor cadence.

Reads counts accepted callbacks, not the number of CLLocation samples inside the delivered array. Last read is the callback observation time rather than a stored coordinate timestamp. These diagnostics remain in the controller across a location Off/On cycle and are not written to persistent settings; creating a new controller starts a new count.

### Continuous silent audio

One AVAudioPlayer loops the original 50-millisecond, mono, 8-kHz silent WAV indefinitely. The audio session uses playback, default mode and mix-with-others. The best-effort preference concerning system alerts does not override operating-system interruption policy.

Session category setup is required and its error enters the existing recovery path. The request to prefer no interruptions from system alerts is best-effort: rejection of that preference alone does not prevent an activation attempt. Playback reports Playing only after preparation, `play()` success, `isPlaying`, current player identity and the non-invalidated enabled state all agree.

A single nonrepeating common-mode timer uses the same 0.5-second interval for healthy playback inspection, retry pacing and unavailable-service probes. Healthy inspection keeps the existing player and session rather than reconfiguring or restarting them. Off invalidates the timer and stops local playback immediately.

The first unexpected player stop, decoder error or actual interruption can initiate immediate recovery. Repeated failure before a healthy sample shares one failure episode and one existing retry deadline. Notification storms do not continuously postpone that deadline or permit unlimited immediate retries. Explicit user requests remain distinct from automatic advice.

### Recovery and user intent

| Event or condition | Required behavior |
| --- | --- |
| Healthy route, rendering, mute or lifecycle advice | Inspect current playing/configuration state without recreating a healthy player |
| Interruption start or invalidated work | Mark the in-flight result stale and prevent false playback success |
| Interruption end or positive/unknown resumption advice | Treat it as an availability opportunity rather than automatic resource invalidation |
| Negative resumption advice | Preserve explicit On and healthy playback, without bypassing an existing retry wait |
| Media services lost | Stop local output, preserve On and the current retry episode, and probe on the common interval when scheduled |
| Media services reset | Drain invalidated work and use a bounded fresh recovery opportunity |
| Missing end/reset notification | Permit serialized service-availability probes; do not wait forever for one particular notification |
| Off during activation or preparation | Stop locally, retain the operation's completion ownership and compensate before any later activation |
| Failed owned deactivation while Off | Show the release failure without an automatic Off retry loop; a repeated explicit Off may retry |

## Implementation and ownership

`BackgroundKeepAlive` is MainActor-owned. It owns location state, player state, one timer, failure-episode flags and an activation/preparation/deactivation gate. The root owns exactly one controller. `BackgroundKeepAliveView` binds the two independent choices. The root-attached `BackgroundKeepAliveEvents` modifier, not the removable tab view, merges the controller's explicit notification registry onto RunLoop.main and separately calls `restore()` when the application becomes active. Subscription therefore remains attached when another tab is selected.

On iOS 27, session activation and deactivation use completion APIs. The supported-system compatibility path runs synchronous session work on its utility adapter rather than waiting on MainActor. Player preparation also uses the existing worker adapter. While preparation owns a player, that player is detached from controller/delegate access until completion. This prevents Off, timers and callbacks from concurrently touching the object being prepared.

The gate remains occupied through the completion's hop back to MainActor. An Off-On sequence must drain the old operation and any required release before a new activation; an old release must not complete after the new activation and disable it. Stale player callbacks use weak object identity, not a raw address that could be reused for another player.

`ownsAudioSession` records whether this controller requested activation. A category/preference failure before activation must not cause Off to deactivate an unrelated shared session. When no owned release is needed, the already-consumed deferred-resume request is cleared before serving a latest On. A failed fresh attempt then waits for its one retry deadline instead of consuming the same request twice.

The flag is not an operating-system lease or a lock against another LiveContainer host operation. Weak orphan completions perform best-effort cleanup if the controller disappears while work is pending. An operation that never returns cannot safely be considered cancelled merely to allow overlapping work.

## Design rationale and resource cost

A single controller, player, location manager and deadline keep lifecycle ownership explicit and prevent duplicate work from view recreation. Coarse location accuracy is sufficient because coordinates are discarded; navigation-grade accuracy would not serve this feature's purpose. Location callbacks are system-driven and no location polling timer is added.

The timer intentionally balances recovery opportunities against wakeup cost. Healthy checks reuse objects and do not periodically activate the audio session again. The timer still creates its next scheduled deadline, and the operating system still incurs audio and location costs. Notification recovery, worker completions and location delivery are not free. No minimum physical CPU/RAM or battery use is established by object-count tests.

Playback health uses `isPlaying` and session configuration. It is not a physical-output monitor. Sampling the playback position of a short repeating waveform could alias, so the implementation does not add a misleading stall detector, spare player or forced periodic recreation. Persistent On describes intent, not permission, audible output or guaranteed server availability.

## Verification contract

The controller, async-session and preparation fixtures use the actual implementation with controlled platform outcomes. They verify reentry, delayed completions, Off priority, weak/stale callbacks, owner lifetime, failure pacing, lost-service probes and recovery after failure ends. The location fixtures verify authorization transitions, active-start conditions, current-manager identity and independent audio/location behavior.

Policy histories include ordered notification pairs and triples, long event sequences and automatic-liveness checkpoints. Reentry tests inject successive actions while platform calls are still active, compare a separately tracked last user intent, and require recovery through already-scheduled callbacks or timers rather than a fabricated new On request. Ownership tests cover setup failures before activation, post-request failures, explicit failed-release retry and healthy object reuse.

Actual Apple Foundation/Combine/RunLoop checks verify notification delivery, cancellation and scheduling separately from platform response doubles. AVAudioFile decodes every sample of the original WAV. SDK checks compile the actual supported API paths. The Simulator UI test verifies repeated On/Off, identified Playing/Off state, saved intent across relaunch and tab navigation while retaining the original predicates and time bounds.

Standalone source predicates run at their appropriate feature scope. The integrated release uses exact owner equality and separate direct controller, host and combined UI checks. A source-specific predicate is not falsely described as inspecting unrelated modules in the combined app. Documentation inheritance is checked independently of the frozen functional code.

## Operation and limitations

The two choices can be controlled independently. Denied permissions, unavailable services and recovery failures are shown without silently erasing saved intent. An explicit Off is the authority to stop local work. Changing tabs or stopping the server does not implicitly own those service choices.

The configured minimum is iOS 17.2; the primary target is physical iOS 27 through SideStore standalone installation or LiveContainer guest execution. The latter can share process/session resources with its host. A remapped Simulator identifier is not a substitute for testing that host boundary.

System scheduling can delay a 0.5-second deadline. Suspension and termination prevent timers and callbacks from progressing. Calls, Siri, Bluetooth routes, media-service resets, first-unlock/permission states, long locked-device operation and device resource use require physical evidence. The persistent-On recovery policy is a project behavior, not a claim that every media-player application should automatically resume after every platform event.

## Related documents

The [shared baseline](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/main-baseline.md) defines common inputs. The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) separates controlled events, actual scheduling, Simulator and physical deployment. The current parent documents and frozen-code boundary are recorded in `docs/documentation.json`.
