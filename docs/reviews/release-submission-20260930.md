# Release submission recheck — completed 2026-09-30

## Executed source and disposition

Starting final release: `7eb2c7ec1427291a0f2ed1e6a79219dc7c4de240`.
Executed checkpoint: `e47f7ec80aaa464a0eec9f56b9f62f41a51d150f`, tree
`609da546e481ba34c56947ce5fde24a317af5be6`, 242 tracked paths.
Combined run36714842285 attempt1 completed successfully on Linux and Xcode27;
terminal metadata is2026-09-30T12:59:46Z. This is the fresh run started before the
interrupted response, not a rerun invented during resumption or an earlier badge.
Both original artifacts and their source/product/execution records were inspected.

No additional reproducible production defect was found in this review. No production,
test, build, workflow, project, resource, dependency, default, permission, signing,
assertion or timeout change was needed. The checkpoint only added this review file;
all prior241 paths remained exact. Closure updates README, its identical integrated
specification and this report; the other239 tested paths remain byte/mode-identical.
The docs-only closing commit is a direct child of the tested checkpoint, not another
runtime execution. Previous final review and failure history remain at7eb2c7ec.

The user explicitly retained fixed UDP port/multiple unknown-peer behavior. Default
UDP1080 and all existing policies are unchanged; no dynamic-port fallback, client
change or experimental patch is applied. Main and all six feature refs remain intact.
Physical iOS27 SideStore standalone and LiveContainer guest are the intended, distinct
deployments; minimum17.2, host/SDK/Simulator and actual physical execution are not
interchangeable evidence. No new physical execution is claimed.

## Source review matrix

| Area | Reviewed implementation and verified boundary |
| --- | --- |
| Composition/root | One SettingsStore, ServerController and BackgroundKeepAlive; four tabs; JSON sole durable owner; no duplicate AppStorage path. Seven-parent integration, all six actual tips/main and177 original path/hash/mode mappings remain. |
| Server | Settings validation and byte-sensitive equality, YAML escaping, current/desired/attempted intent, idle prepare, serialized native work and Stop/reconfiguration examined. Running remains invocation rather than readiness; tests use sockets separately. |
| Persistence | Atomic whole-file writes, bounded read, migration only on missing file, no-op save suppression, explicit retry, live Stop on failed write, stale import revision/cancellation and provider/security-scope boundaries examined. Existing durable/live failure distinction remains. |
| UDP | Eight ordered patches, 1500/500/300s/60s buffer ownership, demand buckets, sizing/truncation, allocation errors, peer/header filtering, partial frames, maintenance versus idle timeout and final cleanup examined. Existing fixed-unknown observation is not a corrected profile. |
| Accounting/UI | Positive destination I/O counted once before later failures; peeks/headers excluded; control-peer reference and process-lived registry; independent atomics and visible/active sampling examined. Total/IP/Unattributed, non-reset on Stop/Start and pre-rounding sums remain. |
| Background | Actual628-line owner reviewed: independent coarse location, no coordinates retained, one0.5s deadline, serialized activation/preparation/release, weak stale callbacks, Off priority, unowned release guard and consumed resume intent. No second state machine or scheduling workaround added. |
| Icon/product | Approved image/WAV/catalog and project membership preserved. Generated framework/source identity, full ZIP bytes/types/modes/directories/CRC, ARM64/platform/minimum and matching dSYM inspected. Test code stays outside the app. |

Every tracked path was inventoried by content and Git mode and classified:12 production
Swift files,8 native patches,16 baseline-framework entries,119 test/driver paths,
18 build/validation paths,56 documentation/metadata paths and13 project/resource/
license paths. This classification is not an assertion that all historical documents
or every possible input history were executed. All83 Python/Bash/JSON/plist inputs
parsed successfully, including71 Python/Bash inputs. CI supplies actual C/Swift
compilation and execution separately from local syntax/inventory checks.

## Completed combined execution

The original current-run logs retain full test output and deliberate old-code failures.
Linux uses buffered and splice; Apple uses buffered and actual SDK/archive/Simulator.
Apple-only skipped Linux steps are not counted as execution.

| Suite | Current result |
| --- | --- |
| Source/package gates | Baseline46, input37,177 ownership mappings, source/pin/worktree/index, formatter18, exact eight-patch reversal,62 package metadata and12 original payload-boundary checks pass. |
| TCP | 15,552 conditions times three callback modes under sanitizer/O3 pass for Linux buffered/splice and Apple buffered; actual collector, successful I/O and NULL/legacy behavior checked. |
| UDP/statistics | Per mode111 complete-payload network cases,24 accounting boundaries,18 associations/126 full echoes,426 large/mixed records and145,459 stream cases pass. Registry/concurrency and Apple TSan retain their scoped success. |
| Sampler | Exact source passes98,516 checks per compiler mode and retains the old implementation's expected failure. |
| Server/settings | Native18 final-server,12 active-client and16 real file/store/controller/Hev records per mode pass with existing cancel/auth/restart tests. Models retain1,250 schedules/25,544 assertions,512 YAML parity and889 settings assertions. |
| Background | Original35 policy scenarios,1,352 pairs,69,984 triples,65,536-event histories/1,024 liveness checkpoints,135 ownership assertions and12,096 reentry histories pass at the exact owner in both compiler modes. Byte mappings and direct integrated controller/async/host/UI checks connect that scope to release. |
| Apple host/SDK | Real Combine34 deliveries/cancellation and RunLoop checks pass; audio/location doubles are not real OS interruptions. AVAudioFile reads400 zero samples. Actual12-file iPhoneOS27/ARM64/min17.2 typecheck succeeds with empty diagnostics. |
| Simulator/UI | Ten original/remapped preseeded cases pass. Actual iPhone16/iOS27.0 build24A434 runs3 UI cases: passed3/failed0/skipped0/expected-failure0, runtimeWarnings=[], both cleanup arrays empty. |

Current UI durations: audio118.567s, integration130.361s, statistics96.169s; session
window412.410s. Original predicates and900s test command limit are unchanged. Thirteen
UI attachments and five seeded screenshots were inspected. Portrait Total In/Out/Sum
is100.226/100.226/200.452KB, each IP50.113/50.113/100.226KB; Stop/Start landscape
values double. Scroll/hittability evidence does not mean every overview/footer is
unobscured by the floating tab bar. Final JSON has serverRunning=false and both
Background choices false; the configured UDP default is still1080.

Real retention received48001 then30001 bytes and no later packet. Linux demand gap
120.049781s, reclamation30500 at300.211670s and1500 at420.325799s. Apple gap
119.971519s, reclamation300.020803s/420.042072s. Total and registered-IP In remain
78002 and Out0. Actual UDP/clock/allocator/Hev timer are used with a fixture-only600s
timeout; app default60s and suspension/scheduler limitations remain unchanged.

Supplemental resumption replays completed17 commands, all exit0: Git fsck, baseline,
composition, integration ownership, baseline/input/package controls, sampler,
server/settings/Background/async suites, exact-owner policy/all-owner checks, and
final tracked worktree/index comparisons. They are full-history Linux replays, not
another whole native pipeline, new Apple run or physical test. Syntax/inventory and
independent product checks supplement, not replace, the fresh combined CI.

## Product and evidence correspondence

New unsigned1.1.0/build10 IPA, bundle`hev.Socks5`,285407 bytes:
`97d35e44c1d397ff957597f8d5390b4d24fddac18807ad8f33308acb2e4c58ce`.
All seven regular payload files and Unix modes equal the preceding valid reviewed
build10, including executable0755/resources0644. ZIP metadata/hash differ; earlier
IPAs remain unchanged. Independent parsing confirms ARM64/iPhoneOS27/minimum17.2,
no signature/encryption, and actual app/dSYM UUID
`78205DB1-9792-3928-98C1-B40B14ACF29D`. The matching DWARF defines aggregate/client
statistics and prepare; a stripped app's absent symbols are not mistaken for missing
functionality. Actual archive/CAR/ImageIO checks and original WAV remain successful.

| Original artifact | SHA-256 |
| --- | --- |
| Linux11096281579 | 6f2effd6ff67efb9ce489521fdadd4c9b72bb8b1a6fe2737f94643f374018dd0 |
| Apple11097441060 | 8732b0ebcfa46f8137ad66e772eecab45818117db9c6c0b073e8478de16019dc |

Original ZIP hashes/CRCs and four242-path source archives (Linux, Apple, packaged
source and UI source) agree with the exact tested commit/tree, bytes and Git modes.
Full manifests agree; genuine history verifies ancestry. Generated framework/product
attestations name the tested source, not the later document child or unchanged
committed baseline. Offline evidence verification does not execute a new build.

A first connector job query timed out, then the direct jobs GET confirmed both
completed successes. A local PTY launch was unsupported and the subsequent existence
check found no script; no test had started in those calls. The later recorded runner
completed all17 commands. These tool/setup outcomes are not reclassified as CI test
successes or production defects. Original intentional negative-case failures,
ASan alternate-stack limitations, libtool/AppIntents notices and tool diagnostics
remain. No warning threshold, host, cache, runtime or timer workaround was used.

## Resource judgment and final scope

No production instruction, allocation policy, packet copy, timer, worker, lock,
registry or observer is added. Healthy reuse and visible-only sampling remain; the
original sizing syscalls, buffer/history memory, process-lived IP entries, atomics,
snapshot/sort work and audio/location scheduling still have costs. No universal
CPU/RAM minimum, physical energy gain or maximum throughput result is asserted.

No new reproducible defect or failed required current check remains within the
reviewed/executed scope. The documented fixed-port UDP restriction is deliberately
retained. Physical SideStore signing/install/run, LiveContainer/shared-host audio,
real permissions/calls/Siri/Bluetooth/providers, long lock/background survival,
power-loss durability and device resource measurements remain unperformed. Neither
this review nor its finite tests constitute an unconditional zero-defect guarantee
for all possible deployment, input, resource and scheduler histories.
