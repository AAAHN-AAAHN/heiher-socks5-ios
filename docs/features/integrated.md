# Integrated SOCKS5 for iOS — six finalized feature owners

## Current integration review — 2026-09-26

This revision aligns the complete project on main `75335d201cb1e541bb153e9899badbc11ccf1973`
and integrates the six completed current-main owners below, retaining previous
release `2bc8e5a8bfbe6a7d2de74644bec9955513f8f8df` as a real ancestor. Combined native,
SDK, archive/package and actual Simulator checks for this source passed in
run36229814360, attempt1, as recorded below. Individual feature successes were not
substituted for the combined run. The new package is **1.1.0 (build 9)**; prior
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

## Completed project-wide verification — 2026-09-26

The actual tested release is **87ecb2d8f716ed47f5eb06f63df1765e85a304c0**,
tree **88f2ccb354c8f50fd0781d2224f611dfbe919e35**, with188 tracked files.
Run **36229814360**, attempt1, passed both Linux and Xcode27 jobs without retries.
The Apple job passed native/models,12-file SDK, actual ARM64 archive/IPA,ten seeded
Simulator cases and both real UI tests before artifact upload. A final documentation
commit changes only this README and its identical integration specification; all
186 remaining files are the executed bytes/modes. No production patch is added
or test threshold weakened after verification.

### Complete current dependency graph

Main75335d20 is a real ancestor of all six features and release. UDP9909aa5f is the
actual parent owner for statisticsbb07d179; serverbe4bdd14 is the actual parent
owner for persistence472ef5a3. Release contains all six completed feature heads and
its previous release. All15 required ancestry relationships have zero missing parent
commits. This count includes transitive requirements, not15 direct Git parents.
Composition base_commit, separate membership and every owner baseline agree.
The127 source mappings,26 server-to-persistence and17 UDP-to-statistics inputs match
original owner paths, bytes, modes and hashes. All README/specification mirrors and
six retained feature README copies match their actual current owners.

| Branch | Actual tested source | Run | Final scope |
| --- | --- | --- | --- |
| main | 3e7047cfa52f446e5c5d2f6c15e49e8bbfd7cd8b | 36218740219 | Linux native and actual unpatched Apple baseline archive. |
| UDP | 3b78847619c5123a1c13a2413faa4ee2525eef77 | 36219497734 | Linux/macOS native and SDK. |
| Statistics | b4b840d8e8594f9cbc1a08bb69f1c8c5c01210a6 | 36226383235 | Exact UDP prerequisites, native/SDK and actual UI. |
| Server | 3ba1eb40efd25a0a833b7b3b3ed6c393ddcd8e2e | 36225969482 | Metadata-correct native/controller and five-file SDK. |
| Persistence | ffbeed20b18cb5f9b04c34ac1d10b534bcd06d40 | 36226873958 | Latest server composition, native persistence and eight-file SDK. |
| Background | 27117ab11438c13fed7badbe76b645708e9b8629 | 36225709587 | SDK/controller and actual audio UI. |
| Icon | 39dea8c1f852bb0d927b01fa258adb4507a44e99 | 36225581121 | Actual assets/ImageIO and Simulator registration/launch. |
| Release | 87ecb2d8f716ed47f5eb06f63df1765e85a304c0 | 36229814360 | Combined native/SDK/ARM64 IPA and Simulator/UI. |

The final eight source runs passed17 required jobs on their first attempts. Server's
intermediate b8ab6c1e/run36225295956 also passed, but its separate old-main membership
references were corrected and completely retested in the final source above; its
two jobs are not added to the17 final jobs. Expected skips of ordinary packaging in
feature-only workflows or Apple-only steps on Linux are not claimed as execution.

The whole project review checked655 branch-file entries and136 branch-local Python/
Bash syntax inputs. Repeated files across branches count as separate entries, not655
unique files. All branch product-source paths remain identical to their project-
audit starting snapshots. Main's original app/project/LICENSE and the16-file committed
baseline framework remain unchanged. The two upstream main refs were re-read and
still matched180012e8 andb3585289. This is a dated observation, not automatic future
upstream tracking or independent updates to the server's locked submodules.

### Actual combined native and model results

Linux buffered/splice and macOS buffered each passed58 mandatory UDP profile-case
executions,8 current peer/queue cases,20 statistics network executions,8 writers/
800000 counter updates,actual TCP/UDP boundary probes and ASan/UBSan tests. Object
symbols verified the actual mode; macOS also passed the real counter's TSan check.
Formatter18,optimized strict-aliasing sockaddr probes,exact patch application and
reverse restoration passed. There is no new native policy or runtime correction.

Each mode retained14 server/controller records including40 active Stop/restarts,
12 active-client cases,16 old/current delayed completion records,40 pre-start and
100 legacy/prepared cancellation cases and worker/configuration controls. The
JSON/store/controller/Hev integration produced16 passing records and4 old/current
delayed records. These verify byte-distinct/255-byte credentials,process relaunch,
failed saves still stopping Hev,explicit pending-save retries and saved Stop.

Both hosts passed7 server scenarios,84 current assertions,512 parity cases and22
expected old-model failures;209 current settings assertions and original import/
store/access controls;1193 retained Background assertions plus49 authorization-reset
assertions with28 expected old-controller failures. Session38/3000 and preparation
22/3000 suites passed in Swift debug and optimized modes with their blocking/
implicit-preparation controls and actual worker helpers. The10000-sample statistics
model,six pipe andthree original driver cases passed. Apple Foundation/Combine
verified34 deliveries and cancellation; five real Timer/RunLoop checks and400 zero
WAV samples passed. Platform doubles are not physical audio/location event tests.

All six detached-owner source/driver groups passed and were removed. The common46,
release37 generated-input/header and12 complete-payload cases passed on both hosts,
without deleting original assertions or deadlines. Entry/final worktree/index logs
are empty; SDK header commit and digests match the actual native source. Counts
include controlled repetitions and expected historical failures, not independent
device trials or whole-program sanitizer certification.

### Actual Apple product and UI

This run records Xcode27.0 **27A266a**, iPhoneOS SDK27.0, Apple Swift6.4
**swiftlang-6.4.0.34.1**, clang2100.3.34.1 and macOS27.0 **26A428**. All12
production Swift files passed ARM64/iOS17.2 warnings-as-errors typechecking with
an empty diagnostic log. The seven-patch engine/framework and actual iPhone archive
compiled and linked. ARM64 platform2/minimum17.2/SDK27.0,unsigned load commands,
required native definitions,full payload and app/dSYM UUID checks passed.

The actual iPhone16 Simulator ran iOS27.0 **24A434**. All10 seeded original/remapped
cases passed: stored tabs,Start/relaunch with TCP echo and saved Stop. Both actual
XCTests passed with0failures/0skips: owner audio **160.646seconds** and combined
Server/Statistics/Settings/Background **150.296seconds**; total **310.942seconds**
of case execution. Result-bundle span and total workflow duration are different.
The original13 captures (eight UI attachments andfive seeded screenshots) were
inspected,including portrait/landscape controls and specific Playing/Off states.
Real native greetings,stored intent and server Start/Stop while audio remained On
passed. Test code and preseeded JSON are not bundled into the IPA.

Both Simulator cleanup reports and runtimeWarnings are empty arrays. The targeted
main-thread audio advisory is absent from completed console and xcresult. Existing
platform-specific libtool empty-symbol,AppIntents,destination/debugger diagnostics
remain in raw logs. This is not a universal warning-free or bounded-startup claim.
Archived CAR and ImageIO checks retain exact opaque1024-square phone/pad icons,
complete source/fallback decoding and original WAV/artwork. No new physical icon
cache,manual icon-mode or LiveContainer guest-list check is inferred.

### Original artifacts and exact delivery identity

| Original current release artifact | SHA-256 |
| --- | --- |
| Linux10901662620 | 875c2b2d5cfbdf646be06c6e6cfb26dc47af65a6467d76587ca9543de1afb5e0 |
| macOS10902259359 | 0d525b425cad3028f488f88c6d161d33e44cbd570fc34a2809f80ee1f402bbeb |

Both ZIP digests/CRCs,genuine source comments,all188 path/byte/mode identities,
complete source manifests and Git tree were independently checked. The actual CI
history bundle contains162 reachable commits at the tested source. Final docs-only
commit identity and source are separately supplied; no invented history is needed.

**Socks5-1.1.0-build9-unsigned.ipa** is **261577bytes**, version1.1.0/build9,
hev.Socks5, SHA-256 **9ccd35c53d2f03cc8cf71dc74ca28314f85dc54b5af860bcd76c18b21e4c116f**.
Its app/dSYM UUID is **03F5D92F-C31B-3702-B635-AEC509102466**. The original CI IPA
was copied without modification; Mach-O,UUIDs and native definitions were independently
parsed. Against the preserved build8 IPA,the executable and resource members are
byte-identical; only Info.plist differs (build9). Equal executable/UUID is consistent
with unchanged production source,not proof of a different binary implementation.
The new source checkout,build logs,version and package digest distinguish this fresh
build from an old IPA renamed by the reviewer. Re-signing changes delivery bytes.

Generated framework hashes and phase/source attestation were inspected as CI evidence;
those rebuilt library files are not independently shipped for a local rehash. The
committed unpatched baseline libraries are fully present and verified in source.
A Simulator binary hash is not an iPhone IPA hash. The companion verifier checks
original artifacts,source trees,real ancestry,mappings,all eight patch round trips
and recorded product/UI identities; it does not run a new native or device test.

### Retained limitations and resumed-work boundary

Fixed-unknown UDP observations were8/9 for both workers on Linux buffered/splice
and macOS buffered. Failure was independent closure: Linux buffered workers4 got
errno111; the others timed out. These are the accepted observation-only fixed-port
restrictions,not failures in this run's mandatory58 cases. Defaults are preserved;
UDP Listen Port0 remains the recommendation for multiple unknown-client sessions.

The prior build8 run36214354604 first mandatory mixed-workers4 errno111 remains
unexplained; it is not the observation-only case above. Its later retry and local
host replays did not establish cause. The older Background first-On timing failure
also remains unestablished. Original failed artifacts10896468726 and10894776054 are
preserved separately in the evidence package. Current first-attempt success does
not reclassify either historical failure or imply a zero future failure probability.

Resumption completed eleven local source/ownership/model groups at the actual tested
release,including all detached owners,server,settings,Background and full async.
The completed release37/12 boundary runs are also retained. A preceding batch hit an
external45-second tool limit and is not counted as complete; no internal deadline
was weakened. Direct GitHub cloning failed container DNS. Authorized source archives
and exact-hash Git objects were used,then the genuine CI bundle supplied full current
history. These local checks are not a fresh local native/Apple rebuild.

Across release alignment only36 paths differ from build8:29 modified and7 added,
no deletions;152 old files remain identical. Across all branches no application,
native patch,resource,platform/default/schema or committed framework bytes change.
The final source graph,mirrored specifications and traceable build9 are complete
within the executed scopes. Physical SideStore/LiveContainer and other unperformed
boundaries above remain unperformed; no blanket defect-free certification is made.
