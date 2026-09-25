# Background services: continuous location and asynchronous silent audio

## Current status and scope — 2026-09-26

This final audit is complete within the source, regression, SDK and Simulator
boundaries below. The corrected source is
`ac1af90e67f3bb760729ea95370536bb95fa8151`, tree
`d7c8567532e21d4f726abdde8918d9dfd3fdba48`, on `feature/background`.
New run **36153834876** passed: SDK/controller in attempt 1 and the same-source
Simulator UI retry in attempt 2. The earlier run 36138588562 was not reused as
validation of these changes. Physical installation and execution remain unperformed.
No release integration or new IPA is part of this audit. This final documentation
update changes only the identical README/specification pair; the other 65 files
remain byte-for-byte and mode-for-mode identical to the tested 67-file source.

The complete preceding README is preserved byte-for-byte in
`docs/history/background-before-final-audit-20260926.md`.
That file retains the earlier publication failures, exact artifacts and successful
preparation-worker verification. The original synchronous specification remains in
`docs/history/background-before-async-20260925.md`. Historical status statements
apply to their own revisions, not this source. This README and
`docs/features/background.md` are identical.

## Target, ownership and preserved baseline

The intended environment is a physical **iOS 27 iPhone**, installed independently
through **SideStore** or run as a **LiveContainer guest**. These are distinct signing,
container, permission and shared-audio-session boundaries. A Simulator or Xcode SDK
check is not evidence of either physical installation method. The configured minimum
remains **iOS 17.2**; it does not certify execution on every intervening OS version.
Exact build and execution environments must be recorded with each test result.

The common main baseline is `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
This independent feature adds no native patches and has no dependency on UDP,
statistics, server-control, persistence or icon features. Upstream pins, the committed
unpatched XCFramework, original ContentView/server implementation, app project,
plist, Bundle ID `hev.Socks5` and WAV remain unchanged in this audit. Main, release,
other feature refs and the eight-branch structure are not changed.

One root-owned MainActor controller owns location, audio state and their bounded
recovery machinery. The standalone root persists only the two existing AppStorage
keys `background.continuousLocation` and `background.silentAudio`. The integrated
root can supply JSON-backed bindings to the same controller/view instead; two
parallel persistence systems are not introduced. Background never controls Hev or
reads/writes JSON. Audio and location switches are independent of each other and
of Server Start/Stop. Audio remains above Location in the view.

The original four project principles remain the governing contract: understand and
preserve established behavior before minimal, simple, efficient changes; target the
actual SideStore/LiveContainer environments; maintain complete version/environment/
implementation documentation; and distinguish source checks, mocks, SDK, CI,
packages, installation and physical execution as separate evidence levels.

## Final-audit findings and minimal corrections

### 1. Location authorization reset left an obsolete running flag

When an already-started manager returned to `notDetermined`, the old controller
kept `updating = true`. A late location batch could still increment its diagnostics,
and reauthorization was blocked by the existing already-updating guard. The exact
old controller blob `63e9e895ed6141e2b021ba80742cbddb13d04052` fails 28 of the 49
new authorization assertions; the corrected controller passes all 49 locally
and in the new Apple host run.
These callbacks are platform doubles, not a claim that a physical permission reset
was executed. Apple's authorization callback contract includes user privacy resets
and expiry of temporary authorization.

The correction adds one conditional stop/reset to the existing `notDetermined`
branch. The flag is cleared before stopping the obsolete request. Initial permission
requests remain active-only and deduplicated; an unused manager is not stopped.
When-In-Use still requires foreground for a new session, Always keeps its existing
start behavior, and repeated callbacks do not add starts/stops. User On is retained.
No location polling, timer, new state field, coordinate storage or permission is added.

### 2. A generic UI Off selector could match the location state

The former UI test searched any `Off` text. Location can display Off while audio
is Playing, so that query alone did not identify audio state. The view now supplies
the stable `background.audioState` accessibility identifier on its existing text.
There is no label/layout/control change. The test waits for that element's exact
Playing/Off label after normal toggles, rapid changes and relaunch. A negative-selector
control also confirms that generic Off exists while the identified audio is Playing.
The new Simulator run passed this strengthened test and its negative-selector
control. The original screenshots show audio Playing with Location Off, followed
by the final identified audio Off state; they are not physical-device captures.

### 3. Working source and archived HEAD were not required to match

Both audit entry points previously allowed staged or unstaged changes to reach the
Apple boundary. The UI app was built from `git archive HEAD` while its manifest and
copied test could come from the working tree; SDK checks also read working files.
Both now reject tracked differences from HEAD before Apple tools. The SDK driver
checks again before its final manifest; the UI driver retains its full before/after
hash check. UI Git queries use the repository root even when invoked elsewhere.
This binds the tested tracked input to its archived revision; it is not protection
against an adversary concurrently modifying and restoring files during a run.

### 4. Failed UI retries retained old advisory/product markers

The UI entry point now invalidates `SUCCESS.txt`, `advisory-check.txt` and
`app-sha256.txt` before workspace/optimization/SDK validation. Old diagnostic logs
are retained. Success is still written only after XCTest, warning checks, source
preservation and cleanup succeed. Partial current-phase artifacts are not overall
success. Existing original SUCCESS-marker shell controls remain unchanged.

`check_audit_integrity.py` runs the actual old/current shell and UI entry points in
isolated Git fixtures: clean, staged, unstaged, existing-workspace and Python -O
boundaries. Sixteen cases retain exact-old negative controls, confirm no SDK entry
for dirty current input, and preserve prior diagnostics. Fake failing SDK commands
are only a driver test; they are never substituted in real Apple verification.

## Continuous location contract

One CLLocationManager is configured before delegate assignment: three-kilometer
accuracy, no distance filter, background updates and visible indicator enabled,
automatic pausing disabled. Standard updates remain continuous rather than periodic
open/read/reopen. The OS determines timing and sensor use; approximate accuracy is
not a command to switch GPS hardware off.

Permission requests occur only while the app is active. Already-started When-In-Use
sessions are not restarted merely on background entry. A genuinely new When-In-Use
session waits for foreground. Denial/restriction stops updates without clearing On;
reauthorization can restart. Authorization reset now invalidates the obsolete local
running flag too. Off discards the manager; stale manager delegates are ignored.
Temporary errors preserve intent. Only callback count/time are kept, not coordinates.

## Serialized audio, recovery and cost

One AVAudioPlayer loops the unchanged WAV with playback/default/mixWithOthers and
the best-effort system-alert preference. One common-mode one-shot Timer supplies
one-second health checks or retries while On. Healthy checks do not recreate or
reactivate playback. New independent interruptions/stops attempt immediate recovery;
repeated player failures in the same episode retain the existing retry deadline,
without backoff, attempt caps, busy loops or automatic Off.

The optional transition enum serializes activating, preparing and deactivating,
including queued MainActor completions. iOS 27 uses native session completion APIs.
Earlier supported systems run synchronous setActive on a shared utility worker.
No semaphore, synchronous MainActor wait or timeout pretends to cancel an OS request.
Player preparation also runs on a utility worker: controller ownership and delegate
are detached until completion, preventing concurrent player use. Only accepted,
noninvalidated completion with current On intent can play. Category/preference setup,
player construction and final play remain on MainActor; no universal latency claim
is made. The present audit does not change this audio implementation.

Off stops local playback/monitoring immediately and waits for outstanding work before
release. Off-On drains the older release before a new activation. Activation or
preparation failure keeps On and schedules the existing retry. Release failure while
Off is displayed without an Off retry loop; explicit repeated Off can retry. Initial
or completed repeated Off does not deactivate an unused host session. Weak completion
ownership and best-effort orphan cleanup are retained. One root owner is supported;
independent LiveContainer host session activity is not serialized by this controller.

The fixed registry still covers 13 session notifications on iOS 27 and four lifecycle
checkpoints, with 26/27 availability guards and the legacy interruption signal.
Root-level Combine subscriptions survive tab changes; the separate app-active event
restores both services. Weak player identity, stale timer identity, re-entry guards
and invalidation checks protect Off and recovery ordering. No new observer, remote
control, Now Playing, microphone, BGTask, NetworkExtension or host patch is added.

The WAV remains 844 bytes: mono 8 kHz signed 16-bit, 400 zero samples (50 ms), SHA-256
`26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e`.
Its required nonzero header is distinguished from silent decoded PCM. Runtime cost
added by this audit is only the conditional cleanup on authorization reset and static
accessibility metadata; tests add no production objects. Energy/throughput/latency
improvement has not been measured.

## Verification commands and boundaries

Use a full Git checkout, with Swift, Python and Git, because exact old-code controls
and ancestry checks require real Git objects. Generated source ZIPs are not full
repository history.

```sh
python3 Tests/Background/run_checks.py
python3 Tests/Background/check_async_session.py
python3 Tests/Background/check_audit_integrity.py
# macOS, actual iOS 27 SDK; checks only, no iPhone archive or IPA:
bash Tests/Background/check_audio_sdk.sh
python3 Tests/Background/check_async_ui.py
```

`run_checks.py` retains all 1193 earlier assertions and adds 49 authorization-reset
assertions plus an exact-old failing control. Async tests retain 38 session assertions
and 3000 mixed transitions, 22 preparation assertions and 3000 mixed transitions,
exact-old blocking/implicit-preparation controls and real worker helpers, in debug
and optimized modes. The Apple entry point also retains source/framework/scope
checks, three original shell controls, 34 actual Combine deliveries/cancellation,
five real Timer/RunLoop cases, Apple WAV decoding and five production Swift files'
ARM64/iOS17.2 typecheck with warnings-as-errors. Audio/location objects in host
suites are doubles; assertion counts are not independent physical-device trials.

The unchanged checks-only workflow skips ordinary iPhone archive/IPA production.
Its separate UI job builds a temporary Simulator project, drives actual On/Off,
playback state, stored intent/relaunch and tab navigation, exports xcresult and
screenshots, and rejects the original main-thread audio advisory in both console
and runtime results. Test deadlines, warning reporting and all existing postconditions
remain enabled. Optional bulk system diagnostics stay disabled as previously
recorded; that is not suppression of the targeted warning or XCTest results.

Local results include preserved 1193 regressions, complete async suites, 49 new
permission checks (also optimized), the exact-old 28-failure control and 16 audit-entry
cases. A supplemental optimized host test enumerated all 32768 length-five sequences
of eight selected events and checked 231780 invariant boundaries. It used the exact
tested controller and existing deferred platform doubles without OS rejection.
This finite model is not full state-space or physical-event coverage, and it was
not added to CI. Its source and reproducible runner are in the companion evidence.

## Inspected final execution evidence

Run `36153834876` executed the exact source/tree identified above. SDK/controller
attempt 1 passed all retained 1193 assertions, 49 new authorization assertions,
the exact-old 28-failure negative control, all session/preparation suites in debug
and optimized modes, the 16 audit-entry cases, the three original shell controls,
34 Combine deliveries/cancellation, five real Timer/RunLoop conditions and Apple
WAV decoding of 400 zero samples. Baseline/composition/scope checks passed.
The five production Swift files passed the actual ARM64/iOS17.2 typecheck with
warnings-as-errors and an empty diagnostic log. Tracked-source diff logs are empty.

UI attempt 1 failed before XCTest because Simulator bootstatus exceeded 120 seconds.
Shutdown and delete cleanup each exceeded 30 seconds. The failed original ZIP was
preserved; it contains no XCTest verdict, overall success, advisory or product marker.
The precise CoreSimulator stall cause is not established. Only that failed UI job
was rerun normally on identical source, with all deadlines and assertions unchanged.
The SDK success displayed in attempt 2 is carried forward from attempt 1, not a
second independent SDK execution.

UI attempt 2 passed one XCTest with zero failures or skips; the test case took
110.656 seconds, not the entire workflow. It checked the identified audio Playing/Off
state, the ambiguous old-selector counterexample, repeated/rapid intent changes,
tab navigation and stored On/Off after process relaunch. Both original full-screen
attachments were inspected. xcodebuild exited successfully, cleanup.json is [],
runtimeWarnings is [], and the original main-thread audio advisory is absent from
both the console and xcresult JSON. AppIntents/debugger diagnostics remain in the
logs; absence of the targeted advisory is not a universally warning-free or hang-free
execution. No synthetic audio/location callback is presented as a real OS interruption.

Actual SDK environment: Xcode 27.0 `27A266a`, iPhoneOS 27.0, Apple Swift 6.4
(`swiftlang-6.4.0.34.1`), macOS 27.0 `26A428`. Actual UI: iPhone 16 Simulator,
iOS 27.0 `24A434`. The ordinary archive/IPA workflow job was skipped.

| Original artifact | Attempt | SHA-256 |
| --- | --- | --- |
| SDK/controller 10873136052 | 1 | 30345383f7e84bcb31b9a36f9e4e50e582b339c9e51e29f111f66f6efd7e23a3 |
| UI boot failure 10872389189 | 1 | fc7f54125ff6a61f82dd95d89ea124d86c7b57d6b0668be4743a54823a6cb397 |
| UI success 10873467349 | 2 | 0f9557b0f216bd63cdb1f58f42cf5f831c50868aca768dfb4c3e8f2a5a5900a1 |

All three downloaded ZIPs passed digest/CRC checks. Each genuine Git source archive
has the correct commit comment, and all 67 paths, modes, bytes, source hashes and
the reconstructed Git tree match the tested source. Forward/reverse application of
the audit patch reconstructs the corrected 67-file and original 64-file trees.
Nine existing paths change and three are added; 55 existing files are unchanged.
The only production delta is five controller lines and one accessibility identifier;
all audio methods, the fixed registry, WAV, root, project, plist, native framework and
source pins are preserved. Main, release and the other five feature heads remain
unchanged. The companion offline verifier checks these source/artifact identities;
it is not a new Apple or physical-device execution.

## Explicitly unperformed and unchanged boundaries

Physical SideStore signing/install, LiveContainer guest loading and host arbitration,
real telephone/Siri/Bluetooth events, privacy prompts and resets, Files/container
behavior, lock screen, suspension/termination, VPN/hotspot changes, earlier-device
execution, long-duration survival and power measurements remain unperformed for this
revision. Saved On is intent; no callback/timer can run when the OS does not schedule
the process. No automatic relaunch or override of system audio priority is promised.

The existing release `b1ce46553424099937d8001b5badb4eeceab1cce` and build 7 remain
unchanged and do not contain the later Background owner. This feature audit must not
be presented as a refreshed integrated IPA. Accepted UDP/server/settings limitations
are not rewritten as part of a Background-only review.

Primary contracts used in this audit (documentation, not execution evidence):
- https://developer.apple.com/documentation/corelocation/cllocationmanagerdelegate/locationmanagerdidchangeauthorization(_:)
- https://developer.apple.com/documentation/corelocation/cllocationmanager/allowsbackgroundlocationupdates
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/preparetoplay()
- https://developer.apple.com/documentation/avfaudio/avaudioplayer/play()
