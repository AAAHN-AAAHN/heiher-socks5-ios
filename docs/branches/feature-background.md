# Independent continuous audio and location services

## Purpose and scope

This feature supplies independent controls for continuous silent audio and coarse location updates. It preserves explicit user intent and makes serialized recovery attempts while the operating system permits execution. Background services are independent of Server Start/Stop, tab visibility and screen locking. Saved On is not a promise of permission, physical rendering, unlimited background execution or server availability.

The standalone root owns one `BackgroundKeepAlive` facade and persists `background.continuousLocation` and `background.silentAudio` through AppStorage, both initially false. Its Server/Background tab choice is not persisted by this feature. Release supplies the choices from its single Settings owner and is responsible for readiness, revision and disk completion ordering. The facade neither reads storage nor calls the Hev server. Original WAV bytes, minimum iOS 17.2, upstream pins, the common XCFramework and native code are unchanged.

## Functional behavior

### Continuous location

One CLLocationManager uses three-kilometer desired accuracy, no distance filter, background updates, a visible indicator and automatic pausing disabled. It is configured before delegate assignment because authorization may be reported immediately. Permission requests are deduplicated and issued only while active. A new When-In-Use session starts in the foreground; an existing session is not repeatedly restarted on lifecycle advice. Always authorization retains its supported startup path.

Undetermined, denied, restricted and unavailable authorization stop obsolete updates or wait without changing saved On. A nonempty update from the current active manager increments Reads and records the callback observation time. Coordinates and location history are discarded. Reads counts callbacks, not individual CLLocation values. Temporary errors remain visible without clearing intent. Off stops updates, detaches the delegate and releases the manager. Stale callbacks cannot restart or update another manager. Count/time remain in memory across Off/On, are not saved, and reset with a new facade.

### Continuous silent audio

One AVAudioPlayer loops the original 844-byte WAV: mono, 8 kHz, signed 16-bit PCM, 400 zero-valued frames and 50 ms duration. The exact canonical header and all-zero PCM are checked before caching immutable Data. `numberOfLoops = -1` remains the playback backend; there is no spare player or added waveform signal. Direct session management uses `.playback`, `.default` and `[.mixWithOthers]`. The two system-alert/route-disconnect preferences are best effort; their rejection alone does not abort playback. No microphone, ducking or forced output route is added.

One control-queue DispatchSourceTimer schedules the earliest health, retry or bounded progress-probe deadline. The ordinary health/retry interval is 0.5 seconds. A healthy player is inspected and reused without repeating category setup or activation. Completed failures retain On and the same finite failure episode; retry count is not capped. Availability advice may expedite once per episode, while an explicit repeated On remains distinct from an automatic hint. Repeated hints do not start overlapping attempts or postpone an existing deadline.

Playing is published after preparation, play success, `isPlaying`, matching session configuration and current cancellation/resource identity agree. A following observation closes the failure episode. Playback position can corroborate reported state, but does not prove physical rendering.

### Recovery and user intent

| Event or condition | Behavior |
| --- | --- |
| Healthy route, rendering, mute or lifecycle advice | Coalesced inspection; reuse a healthy player |
| Interruption, decoder failure, media loss/reset | Sticky resource invalidation; discard stale results and recover serially |
| Positive/unknown resumption or foreground availability | Preserve On; bounded opportunity to retry before a pending deadline |
| Negative resumption advice | Preserve intent and healthy playback without bypassing retry pacing |
| A valid stopped player | Reuse and prepare/play the existing player when configuration remains valid |
| Invalid player/configuration | Stop/release the old player, retain cached WAV, then recreate/reconfigure |
| Missing or invalid WAV | Visible error, no automatic disk-read loop; explicit intent/availability can retry |
| Explicit Off | Immediately accept cancellation, cancel automatic timers, show stopping while an entered operation remains unfinished |
| Off-On during activation, preparation or release | Retain the actual outstanding operation and mandatory release barrier; activate only after the old release returns |
| Failed owned release while Off | Show the returned error; no automatic Off retry loop; explicit repeated Off can retry |
| An unreturned platform operation | Retain one operation/player and bounded state; keep control/UI responsive; never invent completion |

`setAudio` accepts explicit service intent before publishing the facade value. `syncAudio` ignores identical storage echoes and applies changed nonexplicit values. Both audio state fields are assigned coherently before observable delivery, with no later write after a synchronous observer can submit a newer Off. The standalone toggle forwards the runtime intent before writing AppStorage. Release must preserve the same ordering when storage blocks, fails or reenters; settings schema/readiness are owned by Settings and Release.

## Implementation and ownership

`BackgroundKeepAlive` is the MainActor facade for location and displayed audio state. Each facade registers an audio owner token and asynchronously unregisters on destruction. The process audio service owns cleanup; an orphan view/controller closure never directly deactivates a shared session. Another enabled owner can retain an in-flight activation. The normal root creates one facade and does not tie its lifetime to the removable tab view.

`LoopAudioService` has a short control queue and one exclusive I/O queue. The control queue owns the state machine, operation gate, failure episode, timer, monitor and diagnostic ring. The I/O queue alone creates and calls the endpoint. A short lock protects the latest aggregate intent, monotonic owner/revision/stop/resource identifiers, a fixed-bit inbox and publication/timing values. No AV operation, file access, platform wait, observer callback or dispatch sync executes inside that lock. Every control adoption preserves a pending Off-On stop barrier, including timer and admission paths.

`AudioEndpoint` alone owns AVAudioSession/AVAudioPlayer use. All category/preference/session calls, player allocation, prepare/play/stop and property reads occur on its I/O lane. Fresh intent is checked between potentially blocking calls; when an entered call returns after Off, cleanup proceeds at the next safe point. On iOS 27, activate/deactivate completion APIs keep the gate occupied until actual receipt and consumption. Earlier supported systems use the synchronous API on the same I/O lane. Callback receipts are coalesced before queueing. Player delegates use weak source identity plus a monotonic generation and a bounded inbox; an old player's callback cannot invalidate its replacement.

The service registers the explicit 17-name iOS 27 audio/lifecycle notification set once from the root, using NotificationCenter delivery on the posting thread. Repeated view restoration does not register again. Only normalized enum events cross into the mailbox. `BackgroundKeepAliveEvents` retains the separate main-run-loop application-active restoration needed by location. Audio delivery does not depend on a removable view or an unbounded main-queue Combine backlog.

### Finite execution claims

The application root explicitly supplies a UIApplication capability; no bundle name or identifier is used to guess execution mode. A recovery episode requests one named finite claim on the I/O lane before preparation. Healthy playback, Off, invalid assets, expiration and supersession finish it exactly once. A token received after finish is also ended once. Failed retries do not renew the episode's claim. Grant/no-grant and expiration are recorded separately from audio success.

Provider end executes on a separate utility serial queue. At most one platform token/end job is retained; if that end does not return, later episodes get no grant instead of accumulating more tokens or cleanup jobs. Provider bookkeeping never blocks control. Explicit Off does not introduce a fresh cleanup claim acquisition before stop: a second blocked acquisition would delay the first safe cleanup point. Finishing an existing claim does not cancel AV work or release its operation gate.

The optional extension adapter uses a separate monotonic identity and semaphore for each request. Acquisition and expiration may arrive in either order. Old expiration/end callbacks cannot signal a later holder. End, expiration or its finite 25-second holder deadline releases only that holder; it never cancels audio. The current application root does not select or advertise extension capability. A real extension deployment requires platform comparison and an actual root capability before enabling it; unsupported contexts use no grant.

### Concurrency audit boundary

| Declaration | Mutable state and access rule | External exposure |
| --- | --- | --- |
| `LoopAudioService: @unchecked Sendable` | Control-only policy state; I/O-only endpoint; lock-only ingress/publication/timing; notification tokens configured once on MainActor and removed at final destruction | Immutable command/reply/diagnostic values and short methods; no AV object returned |
| Private `AudioEndpoint: @unchecked Sendable` | Player/session/data/generation accessed on its I/O queue; callback identity/receipt metadata under the delegate lock | Protocol operations on the supplied I/O queue; normalized events and value replies |
| Private `LeaseStorage<Value: Sendable>: @unchecked Sendable` | Value-only lease metadata under one short NSLock; no platform function or wait inside its accessor | Used only within the lease file; checked Sendable lease, provider, end gate and holder surfaces |

The first two declarations reflect distinct existing queue/lock confinement domains; they are not broad permission to send AV objects to views or arbitrary closures. The lease refactor confines its unchecked synchronization to one private wrapper instead of adding unchecked annotations to each gate/holder. Strict-concurrency compilation and actual adapter queue assertions verify these boundaries. No diagnostic warning is hidden by disabling concurrency checks.

## Design rationale and resource cost

One outstanding operation and one owned player prevent a stuck platform call from spawning replacement workers or racing a second activation. Dispatch queues are scheduling lanes, not promises of dedicated permanent threads. The I/O lane uses userInitiated QoS; claim end uses utility. No real-time or userInteractive escalation is used.

The service holds one active timer, at most one finite claim/end job, a 64-entry diagnostic ring, one latest inbox and a bounded progress sample window. The endpoint caches only the original 844-byte resource. Failed attempts do not append a history proportional to elapsed uptime. UI state is delivered only when its values change; repeated healthy hints do not allocate players, reread the asset or continually rewrite session settings. Actual scheduling, API work, audio and location still consume energy. Object bounds do not establish minimum CPU, RAM or battery use on a device.

The progress monitor validates finite values, player generation/resource epoch, monotonic host/device times, read brackets, duration/rate and device/host elapsed agreement. Position movement must agree with the device clock within buffer/read uncertainty. A 50-ms loop can alias under 500-ms sampling. Bounded nonharmonic probes at 0/17/48/91 ms can supply extra evidence, with at most three added samples per window and separated windows. Quantization or uncertainty that covers the observation makes it inconclusive. Two informative suspect windows, a 30-second cooldown and a per-stall budget are required before a certified speculative rebuild. The default certificate is false: suspect/inconclusive evidence is diagnostic until physical false-positive acceptance exists. Identical reported clocks/positions cannot distinguish healthy rendering from an opaque renderer stall.

Delayed-stage observations use 2 seconds for warning and 10 seconds for an unresponsive-operation label. Those values describe an outstanding call; they are not cancellation deadlines, the UI test timeout or authority to release the gate. UInt64 operation, timer, owner, intent and resource identifiers never wrap and reuse identity; saturation refuses further work and exposes a diagnostic rather than launching an ambiguous operation.

## Verification contract

`Tests/Background/run_checks.py` runs the exact historical controller fixtures in a disposable local Git worktree at `618b3d2b413937aaad7373ee2af9e693ec81b84a`, followed by `check_loop_audio.py` against current sources. Historical passes and exact older negative controls are labeled historical and do not certify the new service. The old fixture bodies, assertions and timeouts remain available unchanged in that commit. Adapted async/policy/subscription/scheduling and ownership entry points preserve their historical controls and invoke the relevant current suite. Scope and audit-marker checks remain short, separate entry points.

The current driver compiles the actual service/monitor/lease bodies with strict concurrency and warnings as errors in debug and optimized modes. The actual AudioEndpoint body is compiled with controlled AV doubles for both availability branches; only conditional module/availability selection and same-file test access are translated. It exercises every setup/player/property boundary, blocked APIs, partial failures, duplicate/stale callbacks, owner handoff, Off-On release ordering, finite failures including 1/100/1000 rejections, resource caps and exact token ends. The original WAV is the valid input; an invalid resource is created only in a temporary test directory.

Separate current traces cover harmonic alias, jitter, quantization, delayed/invalid/stale samples, clock discontinuities, bounded speculative recovery, token end blocking, no-grant, stale extension identity and acquisition/expiration ordering. The actual facade tests synchronous observer reentry, coherent publication, storage echoes, independent location, owner cleanup, the full posting-thread notification registry and the real control timer while its main executor is occupied. Combine publication is used where available; Linux uses an explicit synchronous publisher double. Named mutants remove stop admission, cancellation, clock/sample validity, token end, holder/delegate identity, claim isolation and facade ordering. Each must first compile and then fail at its intended runtime invariant; compile failure, unrelated signal and timeout never count as successful negative detection.

`check_audio_sdk.sh` typechecks all eight standalone app Swift inputs against the actual iOS 27 SDK with `-strict-concurrency=complete -warnings-as-errors`, minimum target iOS 17.2, and unchanged platform branch bodies. It also decodes the original WAV through AVAudioFile and runs host fixtures. The Xcode application target includes all three new module files. The Simulator harness retains its exact Playing/Off predicates, the 10-second Playing wait after element lookup, and 5-second Off checks. It covers repeated toggles, saved intent across relaunch and tab navigation, retains failing commands, and attempts bounded diagnostic/attachment export without replacing the original failure. The UI harness does not certify physical SideStore/LiveContainer execution.

Source SHA256, compiler commands, each runtime result and failure inputs are retained in artifacts. Success markers are invalidated at entry, and previous diagnostics are preserved. Host doubles prove the stated event and ownership boundaries, not Apple playback or physical output. Documentation inheritance and frozen source/validation blob identities are separate from functional tests; release verifies the exact owning branch sources and its own integration.

## Operation and limitations

On and Off remain independent for audio, location and server. Permission loss, protected data and recovery failures remain visible without silently erasing On. When a system operation is still pending, Off is displayed as stopping/waiting rather than falsely reporting completed release. A returned owned-session release error is shown explicitly.

The primary physical targets are iOS 27 via standalone SideStore installation and separate LiveContainer guest execution modes. A guest may share process/session resources with a host. Direct management cannot prove exclusive host session ownership; no empty host coordinator or bundle heuristic pretends otherwise. Actual host cooperation would require a verified handshake and separate comparison before that capability is advertised.

Suspension and termination prevent timers/callbacks from progressing. No queue or execution claim promises recovery while the process cannot execute or an entered API never returns. Calls, Siri, routes, media-service changes, first unlock, device permissions, long locked-device sessions, real host contention and energy measurements require physical evidence. Simulator IDs, host fixtures and an SDK compile are not substitutes for that evidence.

## Related documents

The [shared baseline](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/main-baseline.md) defines unchanged inputs. The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) separates source, controlled events, actual scheduling, Simulator and physical deployment. Current parent documents and the frozen functional boundary are recorded in `docs/documentation.json`; this README is mirrored exactly in `docs/features/background.md`.
