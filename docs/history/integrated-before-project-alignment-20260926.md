# Integrated SOCKS5 for iOS — six finalized feature owners

## Current integration review — 2026-09-26

This revision integrates the six completed owners below into `release/integrated`,
starting from `b1ce46553424099937d8001b5badb4eeceab1cce`. The actual combined native,
SDK, archive/package and Simulator checks completed in run36214354604 as detailed
below. Individual feature successes were not substituted for the combined build.
The new package identifier is **1.1.0 (build 8)**;
the previous build 7 IPA and its historical results are not relabeled or overwritten.

The intended environment is a physical **iOS 27 iPhone**, either **SideStore standalone**
or a **LiveContainer guest**. Those have different signing, container, permissions,
registration and shared-process/audio-session boundaries. Configured minimum iOS
remains **17.2**. Native host tests, SDK typechecking, archive/IPA creation, Simulator,
SideStore installation, guest execution and physical background survival are separate
proof levels. No physical installer/host version or device behavior is certified here.
The exact four owner instructions remain in `docs/top-level-principles.md`.

This README and `docs/features/integrated.md` are identical. The complete preceding
release README is retained without byte changes in
`docs/history/integrated-before-20260926.md`. Earlier owner/release histories preserve
failed attempts, intermediate corrections and qualified results for their own source
revisions. They do not describe the outcome of this new source.

## Immutable owners and one-way composition

| Branch | Exact completed owner | Responsibility |
| --- | --- | --- |
| feature/udp-compat | 7f603a7e063422df460fb171d3b95b36cc6230af | Port-zero, sockaddr normalization, peer filtering and queue continuation. |
| feature/traffic-statistics | 3c24614497d0962bc80b888e81a76809afffa37c | External socket I/O counters and visible/active sampling; inherits the exact UDP owner. |
| feature/server-control | 52251e1229cd7b91d15320f93e57fde7ce1142da | Options, validation, YAML, serialized Start/Stop and native cancellation. |
| feature/settings-persistence | 4b57a3b855ec2d914a91ee5357ac67f1d925718d | JSON storage, restoration, migration and import/export; inherits the exact server owner. |
| feature/background | fc79cf015a3ac01d592de4094abe2af2ba694d87 | Continuous coarse location, serialized async audio/preparation, independent On/Off and recovery. |
| feature/app-icon | d08fdfb2b3187ec2e3aae3ffe1552e7c0a5e3af6 | Preserved approved icon and standard asset-catalog integration. |

The shared main remains `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`. This integration
retains the prior release and all six owners as actual Git ancestors, not only labels.
`docs/feature-membership.json` maps 120 owner paths to exact original commit/path,
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

The only production-file changes from build 7 are the two exact Background owner
files: BackgroundKeepAlive.swift and BackgroundKeepAliveView.swift. They contain
native asynchronous iOS27 session activation/deactivation, legacy utility-worker
session calls, exclusive utility-worker player preparation, the previously audited
location-authorization reset repair and the specific audio-state accessibility ID.
The integration adds no second audio state machine or new runtime workaround.

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

## Release-specific validation repairs

### Clean source and generated-framework handoff

The earlier release replaced the tracked framework during packaging. That blurred
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

The former integration UI checked audio toggle intent, not identified playback state,
and retained the earlier synchronous-session advisory. The new temporary XCTest
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
ownership gate covers the actual combined source and all120 mappings. The old
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

Build8 uses the unchanged `hev.Socks5`, schema1 and
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

## Completed integrated release verification — 2026-09-26

The executed source is **b559b19bab86a9d4125a2db90813812f7a4360fc**, tree
**bfbda5342efa71164d186fe56da334f274ef53a4**, with 181 tracked files. This is a
real merge of the preceding release and all six owner commits above. Run
**36214354604** completed successfully after retrying only the failed Linux job.
The macOS native/SDK/archive/package/Simulator/UI job succeeded in attempt 1.
Linux succeeded in attempt 2 on identical source. The macOS result shown with
attempt 2 is carried forward, not a second independent Apple execution. No source,
assertion, timeout, worker profile or warning criterion changed between attempts.
The final documentation commit changes only this README/specification pair; all
179 remaining files match the actually tested source, including executable modes.

### First Linux failure and unchanged-source retry

Attempt 1 stopped in the required buffered mixed-workers4 UDP profile: the
three-association/independent-close case returned ConnectionRefusedError, errno111.
The other ten cases in that profile passed. This was NOT the accepted fixed-port
observation-only failure, not a Simulator boot failure, and not a corrected
production defect. Its original artifact and failed status remain preserved.
Native SUCCESS and downstream Apple/package/UI results were not produced by this
Linux attempt. The later retry passed the entire buffered and splice suite.

Supplementary local replay used the actual stats-linked Hev host executable from
that failed artifact with its command stdin held open. Five full unbound/workers4
profile replays and 200 targeted independent-close repetitions passed. The original
protocol/context helpers were retained with extra traceback/endpoint recording.
This host embeds the same tested library but is not the original CLI executable or
a new native rebuild. Neither the replays nor the retry establish the first
failure's internal cause or a zero failure probability. No speculative engine,
host, dispatcher or retry-policy change was made to conceal that uncertainty.

### Native and model results

The successful Linux buffered/splice and macOS buffered combinations each passed
all58 required UDP profile-case executions,8 current peer/queue cases,20 statistics
network executions,8 writers/800000 counter updates, actual TCP/UDP boundary probes,
ASan/UBSan and optimized sockaddr checks. Actual object symbols identified the
I/O mode. macOS additionally passed the real counter's TSan check. The fixed-unknown
UDP observations remain separate: Linux buffered workers1 was9/9; its workers4,
both Linux splice workers and both macOS workers were8/9 on independent closure.
These outcomes retain, rather than solve, the documented fixed-port restriction.

Each mode also passed the inherited real server/controller suite:14 result records
including40 active Stop/restarts,12 active-client cases,16 old/current delayed
completion records,40 pre-start and100 legacy/prepared cancellations, worker controls
and configuration/parser checks. JSON/store/controller/Hev integration produced16
passing records and4 expected old/current delayed records per mode. This includes
byte-distinct and255-byte credentials, real process relaunch, failed saves still
stopping the engine, explicit pending-save retry and persisted Stop. Old negative
controls remain expected failures, not failed conditions in the current code.

Both hosts passed7 server scenarios,84 current assertions,512 parity cases and the
22 expected original-model failures;209 settings assertions and original import/
store/access controls;1193 retained Background assertions plus49 authorization-reset
assertions and28 expected old-controller failures. Session38/3000 and preparation
22/3000 suites passed in both Swift debug and optimized builds with the original
blocking/implicit-preparation controls and real worker helpers. The10000-sample
statistics model,6 pipe cases and3 original statistics-driver cases passed.
Apple Foundation/Combine delivered34 notifications and verified cancellation;
all5 real Timer/RunLoop conditions and400 zero WAV samples passed. Audio/location
objects in these host suites are doubles; counts include repeated controlled events,
not independent physical-device trials or whole-program sanitizer coverage.

All six exact detached-owner source/driver groups passed and were cleaned up.
They retain the current UDP/statistics/server/persistence/Background/icon controls,
including the icon's13 methods/30728 one-bit mutations and38 boundary cases,
Background's37 entry cases and the existing marker controls. The separate release
37 input/header/generated-source cases and12 exact-old/current payload cases passed
on both hosts. Main/owner ancestry, all120 file hashes/modes, composition, formatter,
patch application and exact reverse checks passed. Input/final worktree/index logs
are empty. The same-revision native headers matched both saved digests before SDK use.

### Actual Apple product and UI

Xcode27.0 **27A266a**, iPhoneOS SDK27.0, Swift6.4 **swiftlang-6.4.0.34.1** and
macOS27.0 **26A428** are recorded by this run. All12 production Swift files passed
ARM64/iOS17.2 typechecking with warnings-as-errors and a zero-byte diagnostic log.
The actual seven-patch engine/framework and iPhone app archive compiled and linked.
The delivered executable is ARM64, iOS platform2, minimum17.2 and SDK27.0, with no
code-signature load command. Defined stats/prepare symbols and app/dSYM UUID pairing
passed. Full IPA payload inventory and bytes matched the verified archive.

Archived CAR inspection found exact opaque1024-square phone/pad AppIcon images.
Apple ImageIO decoded the approved source and120/152-square compiler fallbacks
completely; fallback bytes in the delivered IPA match the recorded decoder hashes.
The source artwork and WAV are unchanged. These are archive-resource checks, not a
new physical home-screen, manual tinted/clear or LiveContainer icon-cache test.

The real iPhone16 Simulator ran iOS27.0 **24A434**. All10 preseeded original/remapped
cases passed: saved tabs, Start/relaunch with actual TCP echo and saved Stop. Both
actual XCTests then passed,0 failures and0 skips: the unchanged owner audio test
108.069seconds and integrated server/settings/audio test108.447seconds, total
216.516seconds of test-case execution. The reported result-bundle span is distinct
from those times and from full workflow duration. Eight UI attachments and five
seeded screen captures were inspected; they are original Simulator evidence, not
rendered mockups. Scrolling/portrait/landscape native greetings, stored intent,
specific Playing/Off state and server Start/Stop while audio remained On passed.

Final JSON has serverRunning=false and both Background switches=false; test settings
are not bundled into the IPA. Both Simulator cleanup reports and runtimeWarnings
are empty arrays. The targeted main-thread audio advisory is absent from completed
console and xcresult. Native libtool empty-symbol warnings for platform-specific
objects, AppIntents extraction warnings and debugger/destination diagnostics remain
in raw logs. This is not a universally warning-free or bounded-latency guarantee.
The earlier Background owner's first-On timing failure remains historical and
unresolved as documented by that owner, not erased by this integrated success.

### Delivery identity and independent artifact inspection

**Unsigned IPA: Socks5-1.1.0-build8-unsigned.ipa**

- Source: b559b19bab86a9d4125a2db90813812f7a4360fc; version1.1.0/build8; hev.Socks5.
- Bytes:261577; SHA-256: **3babd7a9eef22c30d490cbf441f54d9ffc7e0bad397f4bdebbdb93674c700ead**.
- App/dSYM UUID: **03F5D92F-C31B-3702-B635-AEC509102466**.

The three downloaded original artifacts passed SHA-256/CRC, genuine source-comment,
all181 file bytes/modes, complete manifests and reconstructed Git-tree checks.
The actual delivered IPA's Mach-O commands and dSYM bytes were independently parsed;
the original CI IPA is copied unchanged. The generated framework attestation is
inspected as CI evidence; its rebuilt libraries are not separately shipped in these
artifacts for an independent local rehash. The committed baseline libraries are
fully present and verified in source. A Simulator binary/hash is not the iPhone IPA.

| Original artifact | Attempt and result | SHA-256 |
| --- | --- | --- |
| Linux10896468726 | 1, required UDP failure | d3ae0feae3d790543396594ee8f56ad07854b7f2604786385c12e1ca3e284993 |
| macOS10896714499 | 1, full Apple success | ac044ed7922cfb6884732d618bf5c20f074c4293f04c43ad2ac221599930a20e |
| Linux10897311199 | 2, full native success | 7139cbca740370c6672f3880431d0d686ac7b2dd929c5e4c7eb084e95d1dd624 |

The companion offline verifier checks source trees, exact owner files and genuine
reachable merge ancestry, original artifacts, recorded package/UI results and patch
forward/reverse reconstruction. It does not run a fresh Apple or device test. The
source delta has66 changed paths:44 existing paths and22 additions, no deletions;
115 preceding files remain identical. The only product-source changes remain the
two exact Background files. No main/feature branch or prior build7 IPA was changed.

Local preparation initially lacked full historical objects because direct GitHub
DNS cloning was unavailable. The first CI artifact then supplied a genuine145-commit
reachable bundle. Baseline/composition, server, settings, Background and full async
local reruns passed with actual history. Earlier missing-object errors and externally
limited batches are retained separately; an interrupted owner batch is not counted
as complete. CI's full owner groups passed. Only the owned temporary worktree from
that interrupted local batch was removed. No test deadline/assertion was weakened.

For source rebuilds use the documented build entry in a clean checkout. It no longer
modifies the tracked root framework. Directly building the root project with its
unpatched committed framework is not the supported integrated build path; the
script archives `.build/integrated-product-source/Socks5.xcodeproj` with the freshly
rebuilt patched framework. Final documentation-only HEAD and tested binary source
remain explicitly distinct. Physical installation/execution and the unestablished
first Linux failure cause remain outside the successful final verdicts above.
