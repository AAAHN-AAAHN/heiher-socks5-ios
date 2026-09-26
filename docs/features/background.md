# Continuous location and asynchronous silent audio — current main

## Completed alignment — 2026-09-26

This independent feature inherits main75335d201cb1e541bb153e9899badbc11ccf1973
as an actual ancestor and exact base_commit. Run36225709587 attempt1 executed
27117ab11438c13fed7badbe76b645708e9b8629, tree
664a03aca5d2d63bab5306a8306cb7e50fea3106, with70 tracked files. Both SDK/controller
and actual Simulator UI jobs passed in their first execution. The ordinary iPhone
archive/IPA job was skipped. The completion changes only this README and its identical
docs/features/background.md; all68 other files match the executed bytes/modes.

The complete preceding specification and all its qualified results remain at
https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/fc79cf015a3ac01d592de4094abe2af2ba694d87/README.md
and the companion before-source archive. Both existing background-before-async and
background-before-final-audit history files remain byte-identical. New success does
not erase old failures. The four original principles are in docs/top-level-principles.md.

## Real target and separate ownership

The intended environment is physical iOS27 on an iPhone, installed independently
through SideStore or running as a LiveContainer guest. Signing, permissions,
containers and shared host audio/process state differ. Neither native doubles,
SDK compilation nor Simulator success certifies either physical path. Minimum
configured iOS17.2 is not proof of execution on every supported version.

One root-owned MainActor BackgroundKeepAlive owns one location manager, one player
and one health/retry timer. The standalone root has the two existing AppStorage
keys background.continuousLocation and background.silentAudio. An integrated root
may instead supply JSON-backed bindings; two parallel persistence systems are not
introduced. Background never controls Hev, reads JSON or depends on UDP/statistics/
server/persistence/icon features. Audio and location On/Off are mutually independent
and separate from server Start/Stop. Audio stays above Location. AppRoot/event
subscriptions remain independent of tab visibility.

All application Swift, project/plist, baseline framework, original server sources,
app identity hev.Socks5, source/submodule pins, settings keys and WAV are unchanged
from the preceding completed owner. No BGTask, NetworkExtension, remote commands,
Now Playing ownership, microphone permission, host patch or new OS workaround exists.

## Preserved location behavior

One CLLocationManager is configured before delegate assignment: three-kilometer
accuracy, no distance filter, background updates/indicator enabled, automatic pause
disabled. It is continuous standard updating, not a periodic restart/read loop.
The OS determines delivery and sensor use; coarse accuracy is not a GPS-off command.
Permission requests are active-only and deduplicated. A genuinely new When-In-Use
session waits for foreground; an already-started one is not restarted on background
entry. Always retains its existing start behavior. Denied/restricted stops updates
without clearing user On. On authorization reset to notDetermined, clear the obsolete
updating flag before stopping; reauthorization can restart and stale updates cannot
be counted. Initial requests do not stop an unused manager. Off discards the manager;
old manager delegates are rejected. Temporary errors retain intent. Only callback
count/time are retained; coordinates are neither stored nor sent.

## Serialized audio and bounded recovery

A single AVAudioPlayer loops the original silent WAV with playback/default/
mixWithOthers and a best-effort system-alert preference. Healthy monitoring does
not recreate or reactivate playback. One common-mode one-shot Timer checks/retries
after one second. A new independent stop/invalidation attempts immediate recovery;
repeated failures in one episode preserve the pending retry deadline instead of
spinning or postponing it. No backoff, attempt limit or automatic Off is added.

The optional transition serializes activating, preparing and deactivating, including
results queued for MainActor. iOS27 uses the native session completion APIs. Earlier
supported systems execute synchronous setActive on a shared utility worker. Player
prepareToPlay also runs on a utility worker with exclusive temporary ownership:
controller reference and delegate are detached until completion. Only successful,
noninvalidated preparation with latest On intent may play. Category/preference,
player construction and final play remain MainActor operations. There is no claim
that all possible blocking system calls or startup latency were eliminated.

Off stops local playback/monitoring immediately; an uncancelable pending system
operation completes before release. Off-On drains the earlier release before new
activation. Activation/preparation errors retain On and the one-second retry. A
release failure while Off is visible without an automatic retry loop; repeated
explicit Off may retry. Initial/already-completed Off does not deactivate a host
session never used here. Weak completions, best-effort orphan cleanup, stale player/
timer identity, re-entry and invalidation checks preserve ordering. Only one root
owner is supported; unrelated LiveContainer host session operations are not serialized.

The fixed registry retains13 audio-session notifications and four lifecycle checks,
with26/27 availability guards, plus the root app-active restoration event. Legacy
interruption metadata or shouldResume advice does not erase saved On. A healthy
checkpoint preserves playback; category drift repairs the configured options.
The controller does not override user volume, system audio priority or scheduling.

WAV:844 bytes, mono8kHz signed16-bit,400 zero samples/50ms; SHA-256
26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e.
Its nonzero header is distinguished from silent PCM. Existing worker/completion
cost occurs per actual start/recovery, not every healthy tick. No new timer/thread/
observer/log or per-packet workload is added; energy/throughput/latency improvements
are not measured.

## Audit changes and preserved failure evidence

The shared main update verifies all native tracked inputs, including Makefiles and
index, before applying patches and after reversal. Its generic packaging uses a
separate exact-HEAD product copy, never overwriting the committed framework. The
Background-specific source/notification/AST checks remain, now comparing current
main. The dedicated SDK entry adds the identical46-case common regression suite.
All original controller, async, permission, callback, marker, SDK and UI tests remain.

Existing guards require clean worktree/index at entry and final boundaries, reject
Python optimization before assertion-based drivers, invalidate obsolete verdicts,
and retain diagnostic logs. Swift debug and optimized configurations both remain.
Input checks are bounded checkpoints, not an atomic hostile-input snapshot.
No warning gate or deadline is changed. Extra cost is only audit-time work.

The preceding fc79cf01 review recorded run36206790399's first actual UI failure:
first On did not satisfy Playing within ten seconds. Its test failed in39.816seconds;
raw accessibility showed Activating and movie frames later showed Playing. The state
covers both activation/preparation; movie timestamps do not isolate callback latency.
Its internal cause remains unestablished. The identical-source retry passed, but
neither that result nor this new run certifies universal bounded startup or turns
the failed attempt into success. No speculative forced restart or host change was
introduced. The earlier location reset repair is preserved, not a new fix here.

## Inspected new results

SDK/controller passed1193 retained assertions and49 current authorization assertions;
the exact old controller retains28 expected permission failures. Swift debug and
optimized modes each pass38 session assertions/3000 transitions and22 preparation
assertions/3000 transitions, exact-old blocking/implicit-preparation controls and
real worker helpers. All46 common cases,37 Background audit-entry cases and three
original marker controls pass. Foundation/Combine delivers34 notifications and
checks cancellation; five real Timer/RunLoop conditions and400 zero WAV samples pass.
All five production Swift files typecheck at ARM64/iOS17.2 against iPhoneOS27 with
warnings-as-errors and a zero-byte diagnostic log. Source/pin/composition/scope and
worktree/index checks pass. Platform doubles are not actual phone or location events.

Actual iPhone16 Simulator iOS27.0 24A434 passed one XCTest with0failures/0skips in
126.089seconds (case time, not workflow duration). Identified Playing/Off, the generic
Off-selector counterexample, repeated/rapid choices, tabs and saved On/Off relaunch
passed. Both original full-screen attachments were inspected. Cleanup and runtimeWarnings
are []; the targeted main-thread advisory is absent in completed console and xcresult.
Two AppIntents warnings and debugger diagnostics remain. No universally warning-free
or hang-free claim is made. The run records Xcode27.0 27A266a, iPhoneOS27.0,
Swift6.4 swiftlang-6.4.0.34.1 and macOS27.0 26A428.

| Original artifact | SHA-256 |
| --- | --- |
| SDK10900946166 | 8a60994094733f9a4e15988cb670a37f4821e95e78b0e2bb92289c430788c9e5 |
| UI10901081762 | e9067b8753a4a4e79a322470faa36614fc26d43727050b725f5615d2b63bedac |

Both original ZIP digests/CRCs, source comments, all70 paths/bytes/modes/manifests and
Git trees were independently checked. The Simulator executable hash is recorded by
CI; its binary is not separately shipped for a local rehash. Prior local84/578 and
later84/423 supplemental matrices are different fixtures, as qualified by their
respective reports; they are not newly executed by this CI or physical state-space proof.

## Reproduction and explicit unperformed boundaries

Use a clean complete Git checkout. Run python3 Tests/Background/run_checks.py,
check_async_session.py and check_audit_integrity.py; on Xcode27 run
bash Tests/Background/check_audio_sdk.sh and python3 Tests/Background/check_async_ui.py.
Historical controls and ancestry require real Git objects. A source archive or offline
evidence verifier does not execute new SDK/device tests. Release must inherit this
completed owner and validate the combined product separately.

Physical SideStore install/signing, LiveContainer guest/host arbitration, real
phone/Siri/Bluetooth/privacy resets/file protection, VPN/hotspot, lock/suspension/
termination, long-duration survival and power are unperformed for this revision.
Saved On is intent; execution cannot continue when iOS does not schedule the process.
The app does not auto-relaunch or override OS audio priority. This feature run creates
no iPhone archive or IPA and does not by itself refresh the integrated release.
