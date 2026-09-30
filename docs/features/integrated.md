# Integrated SOCKS5 for iOS — verified six-feature release

## Completed submission recheck — 2026-09-30

The repeated final review is complete for the executed scope. It starts at
`7eb2c7ec1427291a0f2ed1e6a79219dc7c4de240`; the documentation checkpoint
`e47f7ec80aaa464a0eec9f56b9f62f41a51d150f`, tree
`609da546e481ba34c56947ce5fde24a317af5be6` (242 paths), is the actual tested source.
Fresh combined run **36714842285**, attempt1, completed successfully on Linux and
Xcode27; terminal metadata was updated at **2026-09-30T12:59:46Z**. Both original
artifacts, four matching source archives, real IPA/dSYM and saved execution results
were inspected. Earlier results below retain their own source identities.

No additional production defect was reproduced in this review. All twelve app Swift
files, eight native patches, tests, build/workflow code, 177 owner mappings, resources,
defaults and limits are unchanged. Only the review checkpoint and closing documents
change. The fixed UDP port/multiple unknown-peer behavior and default1080 are
preserved by explicit user decision; no fallback or client/protocol change is applied.

The complete current outcomes and per-feature review matrix are in
`docs/reviews/release-submission-20260930.md`. The unchanged combined native/model,
source/input/metadata gates, actual twelve-file iPhoneOS27 SDK check, ARM64 archive,
ten seeded Simulator cases and three actual UI tests all passed. UI runtimeWarnings
and both cleanup arrays are empty. Case times were118.567/130.361/96.169s; the
recorded session window was412.410s. Original predicates and deadlines were retained.
Real timed reclamation retained Total/IP In78002/Out0: Linux30500 at300.211670s,
then1500 at420.325799s; Apple300.020803s/420.042072s. The fixture-only600s timeout
does not change the application's60s default or certify physical background behavior.

The new unsigned **1.1.0/build10** IPA is285407 bytes, SHA-256:

```text
97d35e44c1d397ff957597f8d5390b4d24fddac18807ad8f33308acb2e4c58ce
```

All seven decompressed payload files and Unix modes equal the preceding valid build10;
only ZIP container metadata changes. Actual ARM64/iPhoneOS27/minimum17.2 and the
app/dSYM UUID78205DB1-9792-3928-98C1-B40B14ACF29D match. The dSYM contains the actual
aggregate/client statistics and prepare definitions. Older IPAs are not overwritten.

| Original current artifact | SHA-256 |
| --- | --- |
| Linux11096281579 | 6f2effd6ff67efb9ce489521fdadd4c9b72bb8b1a6fe2737f94643f374018dd0 |
| Apple11097441060 | 8732b0ebcfa46f8137ad66e772eecab45818117db9c6c0b073e8478de16019dc |

Supplemental full-history replays completed17 commands successfully, and83 Python/
Bash/JSON/plist inputs parsed successfully (71 Python/Bash). All242 tracked paths were
inventoried by content/mode and classified; inventory is not behavioral coverage.
The closing commit changes only README, its identical integrated specification and
the submission review. The other239 paths retain the exact tested bytes/modes.
This documentation closure is not a second CI or device execution.

The environment, resource costs, reproduction commands and deployment limits below
remain in force. No physical SideStore/LiveContainer run, actual location/call/provider
sequence, long locked-device survival or device CPU/RAM/energy/throughput measurement
is newly claimed. Finite passing checks are not an unconditional zero-defect guarantee.

## Prior package-metadata review — 2026-09-30

The release final review starts at `eff5574a902a8c7efba9675fe49587fdec030e83`.
The complete preceding integration specification, build10 evidence and earlier
failure history remain at that immutable commit's README and the retained
`docs/history` and `docs/reviews` files. Those results are not reused as this run.

Fresh combined run **36705838060**, attempt1, passed Linux and Xcode27 at
`e119676b2c83236ed465b7b61611db577a9576b2`, tree
`42ee2d39996b7fc2faeb166821266d1308cce442` (241 tracked files).
Workflow completion metadata was updated at **2026-09-30T11:34:16Z**.
Native/model checks, the actual ARM64 archive/IPA, twelve-file SDK check, ten seeded
Simulator cases and three actual UI tests passed. Apple-only skips on Linux are not
execution. The closing documentation commit is separate from that executed source.
README and `docs/features/integrated.md` remain identical.

The newly reproduced defect was in the IPA verification helper, not in the delivered
app runtime: metadata-only damaged copies could pass the prior bytes-only comparison.
The repair and exact old/current negative controls are described below and in
`docs/reviews/release-final-20260930.md`. All production code is preserved.

**The user explicitly chose to retain the fixed UDP port/multiple unknown-peer
limitation.** No experimental dynamic-port fallback, UDP default change, client
change or protocol change is applied. Its existing observation remains separate
from required supported-profile tests; it is not relabeled as a corrected case.

## Target environment and immutable composition

The primary target is a physical iOS27 device using **SideStore standalone** or
**LiveContainer guest** execution. Signing, container, permissions and shared-process
session ownership differ. Configured minimum is iOS17.2, not proof of execution on
every later OS. Native tests, SDK compilation, archive/IPA, Simulator, actual signing,
physical installation and background survival are separate evidence layers.
All four instructions in `docs/top-level-principles.md` remain unchanged.

| Feature | Exact integrated owner |
| --- | --- |
| UDP compatibility | 84d47e88de993a8f4b4cc084f9240f29565c78ed |
| Traffic statistics | dc6feaadb9061eb320bbce5d66c56a7c814c93d3 |
| Server control | 368aa4cf89436651414a8885a2a171f5cff9abd5 |
| Settings persistence | a52f2599c4bdb895bc4e8d04ba84f03f45b2a5c7 |
| Background services | 5480cbf9859b8d58c20f9001b0c9fda8e23fd6df |
| Approved app icon | a17e33b283025377601aef1bcfd32dfa6b79a426 |

Main `75335d201cb1e541bb153e9899badbc11ccf1973`, previous release
`8577bb1f9b24593de011076aa3a6cafcebd50240` and all six tips remain real ancestors.
The seven-parent integration is `32675a598053a21547ace23780b572cb238c0dd4`.
The 177 original path/hash/mode mappings in `docs/feature-membership.json` are
unchanged. Original owner READMEs remain in `docs/branches`, complete feature
specifications in `docs/features`, and dated histories/reviews remain available.
Statistics retains its actual UDP6f9848e4 dependency; release additionally contains
the latest test/document-only UDP tip with identical runtime patches. Settings
inherits the listed server-control tip. No ancestry is manufactured from labels.

Native pins remain server `b3585289622561caf4b8789b436cc8820ecd6be0`,
core `162dd996299fc2d2bff2dd63728f8a2cd71ed31a`,
task `328f35d903221b51811b3d02b277d665dfbdc75f`, and
yaml `162227cd7d2b6108bc8bc133273e11413222ddf4`. App pin remains180012e8.
Apply eight exact patches once at their manifest roots: UDP port-zero, sockaddr,
peer-filter, dynamic-buffer; statistics task-I/O, core, server; server startup-stop.
The committed baseline XCFramework is unpatched input. Product creation rebuilds
the eight-patch framework in a disposable source copy and does not overwrite HEAD.

## Preserved behavior and responsibility

One root-owned SettingsStore, ServerController and BackgroundKeepAlive manage four
tabs in Statistics/Server/Background/Settings order. JSON is the sole persistent
intent owner; there is no parallel Background AppStorage writer. Server is independent
of storage; Background neither calls Hev nor reads JSON. Tab changes do not recreate
these owners. AppRoot, app entry, project/plist, Bundle ID, schema and defaults are
unchanged by this audit. Tests and build verification are outside the app target.

UDP preserves complete datagrams, RSV/FRAG rejection, address normalization, peer
filtering, queue continuation and partial-frame handling. The continuous buffer policy
is base1500, growth500, hold300s and independent safe cleanup60s. Only each actual
demand bucket is refreshed; small messages do not retain an unused large block.
There is no arbitrary65536 allocation ceiling, but wire lengths, arithmetic, memory
allocation and actual socket/path limits still apply. Active I/O buffers cannot be
moved. Cleanup does not reset communication timeout and can be delayed by scheduling.

Statistics counts successful destination reads as In and socket-accepted destination
writes as Out, exactly once, retaining completed prefixes across later failure.
Peeks, headers, unused capacity and client-side calls are excluded; failed client
forwarding does not erase successful In. IP rows use normalized TCP control-peer IP
or Unattributed, not physical-device identity. Independent atomic snapshots can differ
transiently; finite UInt64/Double/display rounding limits remain. Stop/Start preserves
process totals; process restart resets them. Distinct-IP entries live for the process.
One approximately1s sampling task runs only while the tab is visible and active.

Server controls retain validated options, byte-exact credentials, YAML escaping,
serialized Start/Stop/reconfiguration and latest-intent priority. Running denotes
an owned native invocation, not listener readiness; tests separately use real sockets.
Persistence keeps schema1 at `Application Support/Socks5/settings.json`, no-op write
avoidance, whole-file import validation and revision ordering. Failure preserves old
files and still applies live Stop/Off, so older durable On can remain after failed
saving until a successful retry. Exported JSON includes plaintext credentials.
A blocked file-provider operation cannot be forcibly canceled by ignoring its result.

Background keeps independent location/audio choices, one coarse location manager,
no coordinate history, the original infinite50ms silent WAV and one0.5s health/retry
deadline. Session activation/preparation/release remain serialized; stale callbacks
are rejected and Off stops local work promptly. The ownership flag prevents releasing
an unrequested session after failed setup, but is not an OS lease against a host.
On is intent, not permission, uninterrupted output or a relaunch entitlement.
Approved artwork/catalog, compiled icon validation and all resources are unchanged.

## Final verifier repair and resource cost

The exact prior `check_ipa_files` validated names, file bytes, CRCs and duplicates,
but ignored Unix type/permission metadata and directory entries. Copies of the actual
old valid IPA passed after removing executable permission, marking its WAV as a link,
or adding traversal/foreign directories. The delivered old IPA itself was not corrupt.

The revised helper requires a real nonempty source app with only regular files and
directories, Unix regular ZIP files with permissions matching the archive, and only
expected usable empty Unix directory entries. Directory entries remain optional and
entry order remains irrelevant. Source links/special files and unexpected directory
paths fail. This is the existing Unix-generated IPA pipeline contract, not a generic
ZIP extractor or an adversarial boundary when both archive and attestations can change.

The helper change is33 added/2 removed lines, plus one build invocation. The older
payload fixture now explicitly records source Unix metadata without changing its
six inputs/oracles. The new121-line fixture executes31 inputs against the exact old
and current function bodies:62 checks per host. Four valid forms remain valid; five
prior rejection cases stay rejected;22 formerly accepted malformed inputs now fail.
These are verification fixtures, not synthetic products represented as real IPAs.

There is **no production change**: all12 Swift files,8 patches,53 inspected runtime/
platform/pin/workflow paths and177 owner mappings are preserved. No new app allocation,
copy, syscall, timer, thread, lock, log or polling path is introduced. Added filesystem
metadata work is confined to validation and scales with archive entry count. Existing
UDP sizing/buffer costs, atomic counters, process-lived IP rows, snapshot/sort work,
audio deadlines and location-service costs remain; no device energy/global optimum
claim is made. Freeing memory does not guarantee immediate matching RSS reduction.

## Fresh combined results

| Layer | Result at e119676b, not a prior feature badge |
| --- | --- |
| Package boundaries | New62 exact-old/current metadata checks and all12 prior payload comparisons pass on both hosts. Full real archive-to-IPA comparison uses the stronger helper. |
| Source and input | Main/previous-release/six-owner ancestry,177 exact mappings, baseline46, input37, source/index/worktree, source pins, formatter18 and eight-patch reversal gates pass. |
| TCP accounting | 15,552 parameter cases x three callback modes pass under ASan/UBSan and O3 for Linux buffered/splice and Apple buffered, using the actual collector and successful-I/O oracle. |
| UDP and statistics | Per mode111 whole-payload network cases,24 accounting boundaries,18 associations/126 echoes,426 large/mixed records, and145,459 stream boundaries retain their required outcomes. |
| Registry/sampler | Concurrent writer/registration/snapshot/expanded-registry contracts, Apple TSan and exact sampler98,516 checks per compiler mode pass. |
| Server/settings | Per mode18 server records,12 active-client cases and16 file/store/controller/Hev records pass; retained1,250 schedules/25,544 assertions,512 YAML parity and889 persistence assertions pass. |
| Background | Unchanged full policy driver runs at its exact standalone owner:35 scenarios,1,352 pairs,69,984 triples,65,536 events/1,024 recovery checkpoints,135 ownership assertions and12,096 reentry histories. Byte mappings and separate release controller/async/host/UI checks connect it to release. |
| Apple host/SDK | Actual Combine34 deliveries/cancellation and RunLoop tests pass, with audio/location doubles explicitly separate. AVAudioFile reads400 zero samples. Twelve production Swift files pass iPhoneOS27/ARM64 minimum17.2 checking with an empty SDK diagnostic log. |
| Actual Simulator | iPhone16/iOS27.0 build24A434:10 seeded original/remapped cases and3 actual UI cases pass, no failures/skips; runtimeWarnings=[] and cleanup=[]. |

The UI cases are audio125.549s, integration122.142s and statistics125.198s; the recorded
session window is474.134s. All original predicates and the900s command limit remain.
Thirteen original UI attachments and five seeded captures were inspected. Portrait
Total In/Out/Sum is100.226/100.226/200.452KB, each IPv4/IPv6 row50.113/50.113/100.226KB.
After Stop/Start the landscape totals/rows double exactly. Scroll/hittability checks
establish access; overview captures are not proof that every row/footer is unobscured.

Real forwarder retention receives48001 and30001 bytes about120s apart, then no packet.
Linux observes30500 at300.147746s and1500 at420.256488s; Apple300.017604s/420.022286s.
Total and the registered IP preserve In78002/Out0. The fixture's600s timeout only
permits observing300s retention; the application's60s default is unchanged.

Supplemental local checks completed17 full-history/source/model/driver commands,
8464 finite metadata combinations and three deliberately omitted checker guards.
All final local commands pass and the three mutants fail explicit assertions. A
first outer20s container limit interrupted a local wrapper before its result; it is
retained, not counted as a test failure or pass. Unchanged checks then completed.
An initial directory-mutant probe raised KeyError rather than the intended assertion;
the corrected disposable mutant confirms assertion detection. No mutation is published.

Duplicate-name fixture warnings, ASan alternate-stack limitations, upstream libtool,
AppIntents and runner notices remain in logs. The targeted synchronous main-thread
audio advisory is absent in the completed console/result. Empty SDK/runtime-warning
fields do not mean all tools emitted no notice or every library path was instrumented.
Finite fixtures/host scheduling are not physical interruption or installer trials.

## Actual unsigned product and provenance

The newly built **1.1.0/build10**, `hev.Socks5`, IPA is285407 bytes, SHA-256:

```text
2ca709d22a9e8f0f0bf1772f45b166aa3072b0d1f20048d5514848265f90ada5
```

It is ARM64/iPhoneOS27/minimum17.2, unsigned and unencrypted, with seven regular
payload files. Independent parsing confirms executable0755/resources0644, proper
Unix directory types, original WAV/icon bytes and matching app/dSYM UUID
`78205DB1-9792-3928-98C1-B40B14ACF29D`. The matching DWARF defines aggregate/client
statistics and server_prepare; undefined references are not counted as definitions.
Actual archive/CAR/ImageIO tests also pass. All seven decompressed payload files and
their Unix modes match the earlier build10 exactly; ZIP timestamps/extra fields and
its archive SHA differ. Earlier delivered bytes/products are not overwritten.

| Original current-run artifact | SHA-256 |
| --- | --- |
| Linux11091983182 | 723ad4aad55efdd023737e89dd8cea7f924729598bd2fb380cf0f082d6baac4a |
| Apple11093346414 | e62dd93617a0d52973fd859dcd407536e164950432ba1cbd8be80510ea4a6d44 |

Original ZIP digests/CRCs, four241-file source archives, Git modes/full manifests and
the tested tree were independently checked. Product/framework attestations identify
e119676b, not the later documentation commit. Genuine history preserves all owners.
The final publication changes only README, its identical integration specification
and the final review report; the other238 paths retain exact tested bytes/modes.
No new runtime or CI is claimed for that documentation-only closure.

## Reproduction and deployment limits

Use a clean full-history checkout; source ZIPs cannot replace historical controls:

```sh
bash Build/build.sh
# Actual Apple host, after native completion at the same HEAD:
bash Build/check_swift_sdk.sh
python3 Build/verify_release.py
python3 Build/simulator_review.py
python3 Build/ui_review.py
python3 Build/record_evidence.py
```

The unsigned IPA is input to signing/import, not directly executable unsigned iOS
software. Subsequent signing changes bytes/hashes. SideStore standalone and
LiveContainer guest installation/execution must be recorded separately. Preserve
identity/container continuity and exported JSON when replacing an installation.
Physical permissions/file protection, external provider transfer, call/Siri/Bluetooth,
VPN/hotspot, shared-host audio, lock/suspension/long background survival and device
CPU/RAM/energy/maximum throughput remain unperformed. Simulator does not certify them.

The fixed-port multiple unknown-peer independent-close limit and valid same-IP first-
sender race remain unchanged by explicit user decision. No default is silently
changed. Current required tests pass and the reproduced verifier gaps are repaired;
this is not an unconditional guarantee for every possible input/OS/scheduler/host.
