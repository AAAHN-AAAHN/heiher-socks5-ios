# Integrated SOCKS5 for iOS — six finalized feature owners

## Current integration review — 2026-09-26

This revision aligns the complete project on main `75335d201cb1e541bb153e9899badbc11ccf1973`
and integrates the six completed current-main owners below, retaining previous
release `2bc8e5a8bfbe6a7d2de74644bec9955513f8f8df` as a real ancestor. Combined native,
SDK, archive/package and Simulator results for THIS source are pending until the
new execution record below is completed. Individual feature success is not a
successful new integrated build. The new package is **1.1.0 (build 9)**; prior
build7/build8 IPAs and their failed/successful attempts remain unchanged.

The intended environment is a physical **iOS 27 iPhone**, either **SideStore standalone**
or a **LiveContainer guest**. Those have different signing, container, permissions,
registration and shared-process/audio-session boundaries. Configured minimum iOS
remains **17.2**. Native host tests, SDK typechecking, archive/IPA creation, Simulator,
SideStore installation, guest execution and physical background survival are separate
proof levels. No physical installer/host version or device behavior is certified here.
The exact four owner instructions remain in `docs/top-level-principles.md`.

This README and `docs/features/integrated.md` are identical. The complete preceding
release README is retained without byte changes in
`docs/history/integrated-before-project-alignment-20260926.md`. Earlier owner/release histories preserve
failed attempts, intermediate corrections and qualified results for their own source
revisions. They do not describe the outcome of this new source.

## Immutable owners and one-way composition

| Branch | Exact completed owner | Responsibility |
| --- | --- | --- |
| feature/udp-compat | 9909aa5f5f41ec87bb3edd976923b2d668e00f08 | Port-zero, sockaddr normalization, peer filtering and queue continuation. |
| feature/traffic-statistics | bb07d1795f010d624b1924cc06203af9aeb3c6a2 | External socket I/O counters and visible/active sampling; inherits the exact UDP owner. |
| feature/server-control | be4bdd14d46b6bcd35dfad0c4923edda771c6ac6 | Options, validation, YAML, serialized Start/Stop and native cancellation. |
| feature/settings-persistence | 472ef5a3ec5626539e4649341d9b7d1bc4a57a9f | JSON storage, restoration, migration and import/export; inherits the exact server owner. |
| feature/background | bfc4656ad197aa8b8f0266d032ec72e964c25ba9 | Continuous coarse location, serialized async audio/preparation, independent On/Off and recovery. |
| feature/app-icon | 639de66aa2265f3beffc1d0b433981d2e8073cb2 | Preserved approved icon and standard asset-catalog integration. |

The shared main remains `75335d201cb1e541bb153e9899badbc11ccf1973`. This integration
retains the prior release and all six owners as actual Git ancestors, not only labels.
`docs/feature-membership.json` maps 127 source paths to exact original commit/path,
SHA-256 and executable-mode checks. Owner tests, patches, source and documentation
are inherited without rewriting them to accept a different feature declaration.
Feature READMEs are retained in `docs/branches/`, and current complete specifications
in `docs/features/`. All dated owner histories/reviews remain included.

The original integrated AppRoot remains byte-identical. It owns one SettingsStore,
one ServerController and one BackgroundKeepAlive, binds the existing four tabs in
Statistics/Server/Background/Settings order, and persists intent through JSON only.
There is no parallel Background AppStorage owner in the integrated app. Server does
not depend on storage; Background does not call Hev or read/write JSON. Statistics
and icon do not introduce reverse dependencies. Tab visibility does not create new
server or Background controllers. Location and audio are independent of each other
and of server execution.

## Implementation changes and preservation

There are no production-file changes from build8. All current owners retain the
same audited runtime, including Background's iOS27 async transitions, legacy worker
adapter, exclusive player preparation, authorization-reset repair and identified
audio state. This project alignment changes common validation, inherited metadata,
source provenance and build identification, not service behavior or default values.
It adds no second audio state machine, new native policy or host workaround.

Exactly seven existing native patches are applied once: three UDP, three statistics,
then the server startup/Stop patch. They are byte-identical to the finalized owners
and unchanged from the preceding release. The main source pins and its 16-file
unpatched baseline XCFramework remain committed unchanged. A product build rebuilds
all seven patches and links that generated framework, not the unpatched baseline.
The baseline's historical compiler provenance is distinct from this product's actual
Xcode27 compilation. Sharing main does not mean all feature-specific build/check
scripts are still identical to main's original maintenance scripts.

AppRoot, app entry, ContentView, server/store/statistics implementations, original
WAV/artwork/catalog, project, plist, Bundle ID, schema and defaults are preserved.
The test Swift sources remain outside the production target. No extra production
timer, thread, queue, observer, diagnostic log, permission, BGTask, NetworkExtension,
host patch or alternate icon is introduced by integration. Background's existing
per-recovery worker/completion costs remain documented by its owner; no measured
energy, throughput or startup-latency improvement is asserted here.

## Preserved release validation and new common checks

All branches now use the same completed main source pins and baseline. Shared
native patch application/reversal rejects differences in every tracked file and
index, including Makefiles/scripts, not only C/H files. The common46-case
exact-old/current input fixture is included alongside every retained owner and
release check. Membership and each owner's base_commit must agree with main; both
UDP-to-statistics and server-to-persistence must be actual ancestor relationships.
Those checks supplement, rather than replace, all exact mapped file/hash/mode checks.

### Clean source and generated-framework handoff

Before build8, the release replaced the tracked framework during packaging. That blurred
the boundary between the archived HEAD and the subsequent SDK/Simulator input and
prevented a strict clean-worktree check at every later phase. The native build now
keeps the checkout untouched and copies the exact HEAD into a disposable product
source directory. Only that copy receives the generated patched framework. Archive,
seeded Simulator and temporary UI builds use that same generated framework.

Native entry/final boundaries reject both worktree and index differences from HEAD,
including index-only edits. The exact server-owned SDK entry additionally requires
native SUCCESS, the same source commit and SHA-256 of both compiled headers before
Apple typechecking. Native and SDK pass markers still denote different phases.
The release-only generated-input guard checks source commit/tree, the full framework
inventory/hashes/modes, completed phases and every other copied source file before
package/Simulator work. A later documentation-only HEAD is not silently accepted as
identical input to an older binary. These are local provenance checkpoints, not an
adversarial trust boundary or an atomic snapshot of concurrent external toolchains.

### Full IPA payload, not only executable/plist

The previous package verifier compared the executable and plist but did not compare
the entire IPA payload to the verified archive. Exact-old fixture execution accepted
a missing/modified WAV and an unexpected extra payload file while those two entries
stayed unchanged. The new check requires matching full file inventories and bytes,
valid ZIP CRCs and no duplicate entries. The six old/current scenarios give twelve
explicit checks. Synthetic fixture bytes are not presented as an actual built IPA.

Real archive checks also reuse the icon owner's exact compiled filename/CAR checks
and independent Apple ImageIO decoder on the archived output. Phone/pad icon images,
metadata, source artwork hash, WAV, permissions, actual ARM64 platform/SDK/minimum,
unsigned input, stats/prepare symbol definitions and app/dSYM UUID pairing remain
required. Compiler-produced PNG hashes need not equal the source artwork hash.

### Actual audio state and independent combined behavior

Before build8, the integration UI checked audio toggle intent rather than identified
playback state and retained the earlier synchronous-session advisory. The new temporary XCTest
project runs the exact finalized owner's AsyncAudioUITests unchanged alongside the
retained integrated Server/Statistics/Settings test. The integrated test now checks
the identified Playing/Off state, including server Start/Stop while audio remains On,
and saved audio state after process relaunch. The original wait limits are retained.

A strict gate rejects the original main-thread audio advisory in both the completed
console and exported xcresult. This does not declare all diagnostic messages absent
or guarantee bounded system activation latency. In the owner's preceding run, one
first-On predicate wait failed before the same-source retry passed; its internal
cause remains unestablished and its evidence is preserved in the owner specification.
A new integration success cannot retrospectively turn that failure into a pass.

## Verification structure and commands

Use a full Git checkout. Exact historical controls and owner ancestry cannot be
reconstructed from a source ZIP alone. Run in clean isolated workspaces, not over
leftover build products; rejected attempts invalidate their applicable verdicts and
retain prior diagnostics.

```sh
bash Build/build.sh
# macOS/Xcode27, after the native pass at the same HEAD:
bash Build/check_swift_sdk.sh
python3 Build/verify_release.py
python3 Build/simulator_review.py
python3 Build/ui_review.py
python3 Build/record_evidence.py
```

The existing read-only release workflow runs Linux and Xcode27 without modifying
refs, feature branches or repository history. Linux builds identified buffered and
splice modes; Darwin builds buffered. Combined native checks reuse the unchanged
owners' actual UDP, statistics, server and JSON/store/controller/Hev tests against
the seven-patch engine, not separate historical badges. All retained model tests,
Background 1193 plus49 assertions, full async/preparation debug/optimized suites,
actual Apple Combine/Timer and WAV decoding remain enabled. Full native assertions,
formatter/sanitizer profiles and patch reverse checks are unchanged.

Feature-only audit-input/source checks run in genuine detached temporary worktrees
at each pinned owner and are cleaned up. They verify their exact standalone entry
contracts, not pretend that release is an icon-only/UDP-only tree. Separate release
fixtures execute the previous/current native/SDK entries and generated input checks:
37 source/header/product cases plus12 old/current payload cases. The integrated
ownership gate covers the actual combined source and all127 mappings. The old
success-marker controls remain. Python optimization is rejected; Swift debug and
optimized execution are both retained.

Apple-only work includes twelve production Swift files' typecheck, actual iPhoneOS
archive/IPA inspection, ten seeded original/remapped Simulator cases and two actual
XCTests. Seeded cases cover tabs, saved Start/relaunch with real TCP echo, saved Stop
and test-bundle identity remapping. The UI cases cover real portrait/landscape
controls/greetings, persisted intent, audio Playing/Off, rapid choices and tabs.
Only the temporary test project receives test code. The existing 900-second command
limit and optional bulk-diagnostic exclusion remain; assertions, screenshots,
xcresult, warning-gate, exit and cleanup checks are not disabled. UI cleanup errors
remain failures. Test counts contain repetitions/controlled events, not device trials.

Source recording always preserves Git source archive/comment, complete SHA-256
manifest and a genuine reachable-history bundle, even if an earlier phase fails.
These artifacts are inspected before completion. A native or package marker alone
is not complete workflow success. No claim is made that this covers every OS event,
UI element, file provider, accessibility setting or network topology.

## Operating, signing and unperformed boundaries

Build9 uses the unchanged `hev.Socks5`, schema1 and
`Application Support/Socks5/settings.json`. Version/build identifiers are supplied
to build commands; project deployment and signing settings are not rewritten.
An unsigned IPA is input to the existing signing/import workflow, not an app iOS
will execute unsigned. Subsequent signing changes bytes; the published digest
identifies the unsigned CI input and exact source, not the user's signed copy.
SideStore standalone and LiveContainer guest installation must be recorded separately.
Keep identity/container continuity when replacing a previous installation; export
JSON first when data preservation is uncertain. Exports contain plaintext credentials.
No speculative host identity override, cache deletion or entitlement is introduced.

UDP Listen Port0 remains the recommendation for multiple unknown-client associations;
fixed-port independent-closure restrictions are retained as observation-only limits.
Defaults stay unchanged. Peer filtering is not cryptographic authentication. Counters
measure successful external socket I/O, not radio usage, headers or remote ACKs;
system resolver internals are excluded. Running is native invocation, not readiness.
Failed persistence still applies live Stop/Off but may leave older saved Start/On
until an explicit successful retry. A blocked OS file provider cannot be forcibly
canceled by dropping its late result.

Saved Background On is intent. Recovery executes only when iOS schedules this process
and permits audio/location work. The serialized pending operation cannot safely be
canceled by overlapping another system operation or inventing a timeout. Suspension,
termination, host interference and OS audio priority are not overridden. No automatic
relaunch is promised. Light/dark-system-UI icon observations are not manually tested
Dark/Tinted/clear modes or LiveContainer guest-list/web-clip behavior.

Physical SideStore/LiveContainer signing/install/execution, real call/Siri/Bluetooth,
permission/reset/file-protection timing, Files/iCloud UI, VPN/hotspot changes, lock
screen, long-duration survival, power-loss durability and energy are unperformed
for this revision. Simulator is not a substitute. Exact source/run/toolchain,
failures, pass/not-run boundaries and artifact digests are recorded only after
inspection in the completion section below.

