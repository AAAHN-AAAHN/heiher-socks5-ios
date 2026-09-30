# Traffic statistics — successful payload totals and control-peer IP rows

## Contract, environment and preserved inputs

The primary targets are physical iOS27 installed independently with SideStore and
execution as a LiveContainer guest. These are different signing, container and
shared-process environments. Configured minimum remains iOS17.2; native Linux/macOS,
iPhoneOS27 compilation and Simulator tests do not certify either physical target or
all versions above that minimum. `docs/top-level-principles.md` applies unchanged.
No release merge, device archive, IPA, permission or host configuration is changed.

This owner contains only statistics and its exact UDP dependency. Main
`75335d201cb1e541bb153e9899badbc11ccf1973` is the actual baseline ancestor, and
UDP `6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5` remains an actual merge ancestor.
The manifest and seven-patch order are unchanged: UDP port-zero, sockaddr, peer-filter,
dynamic-buffer; then statistics task-I/O, core and server. Repository roots and full
upstream revisions remain in `Build/features.json`. Server b3585289, core162dd996,
task328f35d9 and yaml162227cd remain pinned. The committed baseline XCFramework is
unpatched input, not a newly compiled product containing this review.

The complete preceding specification and verification/failure history remain at
immutable commit `0c1000424c7774d503f8c66426c46cdca1fc4553`, its README, and
`docs/reviews/statistics-dynamic-udp-20260929.md`. Earlier reports describe their own
revisions. `docs/branches/feature-udp-compat.md` and the mapped UDP files still contain
the exact dependency owner's bytes. The current README and feature specification
remain identical. No other feature owner or release branch is updated.

### What is counted

In is successful destination-side payload reads; Out is successful destination-side
payload writes accepted by the socket. Positive completed I/O is reported once even
when later work fails, is canceled, or cannot deliver the received data to the client.
TCP buffered and Linux splice use the same accounting boundary. UDP counts the final
successful send prefix and actual receive returns before descriptor filtering; an
Apple retry does not duplicate earlier successes. A truncated destination read counts
only bytes actually returned, not the original advertised datagram length. Invalid
client RSV/FRAG input contributes no destination Out, and empty payload adds zero.
Peeks, SOCKS/wire headers, unused capacity and client-side read/write calls are
excluded. Kernel retransmissions do not add separate application I/O counts.
This is not a remote-delivery acknowledgement,
DNS-resolver accounting, or whole-interface/billed traffic meter.

Each row is keyed by the SOCKS TCP control-peer IP, not destination or UDP port.
IPv4-mapped peers normalize to IPv4, IPv6 scope participates, and same-IP connections
share an entry. IP is not a physical device identity. Failed identity/allocation uses
Unattributed without losing aggregate bytes. Stable process-lived references survive
UDP buffer growth/reclamation and server Stop/Start; process restart resets counters.
No persistent traffic history or payload log is added. The 256 registry buckets are
not a client cap; distinct-IP memory grows over the process lifetime. Callback updates
use relaxed atomics without the registry mutex or a new per-packet lookup/allocation.

Total and individual fields/rows are independent atomic reads, not a global snapshot
transaction. During traffic they may temporarily differ; quiescent sums agree modulo
the finite UInt64 representation. Counter wrapping and Double/display precision are
explicit limits. Rounded displayed cells need not algebraically sum to the rounded
Total. Raw counter verification is independent of formatting.

### Presentation, sampling and resource costs

The existing table shows Total first, then registered IPs; Unattributed is shown when
needed. In/Out/Sum columns and Spd./Vol. rows retain three decimals and decimal units
KB through PB and Kbps through Pbps. Sum uses unrounded values. One approximately
one-second task samples only while this tab is visible and active. Cancellation and
return-to-tab rebaselining preserve cumulative volume. The actual sampler builds one
client snapshot before publishing it; this is not a promise of one SwiftUI render or
one total state write. Arrays/dictionary copying and row sorting scale with IP count.

The inherited UDP policy remains base1500, growth500, hold300s, cleanup60s, with no
arbitrary65536 allocation ceiling; wire lengths, integer bounds and allocation failures
still apply. Only the actual demand bucket is refreshed, and safe owner-task sweeps
are independent of communication timeout. Existing next-datagram queries, Linux
receive-batching tradeoff, base-plus-replacement memory and shrink costs remain.
The private statistics pointer is per association, not per packet/bucket. No new
production state, allocation, payload copy, I/O, timer, polling or thread is introduced
by the tests below. Normal I/O and OS/allocator costs are not zero. User-space free
does not promise immediate byte-exact RSS reduction. Do not infer physical power or
maximum-throughput improvements from source preservation or host-only tests.

## Reproduction

Use a clean full-history checkout, not just a source ZIP:

```sh
python3 Tests/Statistics/audit.py
# Actual Apple host with iOS27 SDK/Simulator:
python3 Tests/Statistics/ui_audit.py
```

The unchanged workflow first verifies the independent pinned UDP owner on Linux and
Apple, then statistics on both hosts and the original Simulator UI suite on Apple.
The documented source/ancestry/ownership/formatter18 gates, historical negative
controls, compiler diagnostics, assertions and timeouts remain. Native typechecking,
model/fixture execution, network tests and Simulator results are separate evidence.

## Final statistics submission audit — 2026-09-30

This review starts at published `0c1000424c7774d503f8c66426c46cdca1fc4553`.
No new production defect was reproduced. All seven patches, five production Swift
files, collector/API, table/sampler, project/plist/defaults/resources/framework,
source pins and workflows are unchanged. Preserve the already validated behavior
rather than add a new runtime, retry policy, renderer or diagnostic to manufacture
a code change. Earlier integration records retain their original sources and
execution dates; they are not reused as this new run's evidence.

The two pre-validation changes are the 344-line
`Tests/Statistics/tcp_accounting_matrix.c` and ten driver lines in
`Tests/Statistics/audit.py`. Existing tests, warning gates and timeouts are retained.
The new fixture is not an application target and adds no runtime allocation, copy,
I/O, atomic update, lock, timer or thread. Existing collector, UI sampling and UDP
costs remain; this is not a measurement of globally minimal CPU/RAM or device energy.

### Successful-I/O accounting and cancellation matrix

The fixture includes the actual task-I/O implementation. Only read/write/splice/shutdown and
yield-cancellation outcomes are scripted; its callback routes to the real native collector
and public Total/IP snapshot API. Actual loopback TCP peers register IPv4 and IPv6
identities once; the third identity is Unattributed. It is not a simulated alternate
implementation of the counter or an independent physical network trial.

Each executable runs 15,552 parameter cases: six outcomes for each of four directional
read/write positions, four cancellation points and three attribution targets. Each
case is repeated with the measured callback, a NULL callback and the legacy API
(46,656 relay executions). Initial successful partial I/O precedes the selected
error/short/EOF/EAGAIN outcomes. Some cancellation points stop before later configured
outcomes; parameter selection does not imply every syscall is invoked in every case.
Actual Hev task lifetime, circular buffers and the Linux pipe/reactor context remain.

The oracle observes actual positive destination-I/O returns independently from
callback delivery. It requires exact raw In/Out deltas before cancellation and final
exit, preservation of completed I/O across later failures, correct IP/Unattributed
increments, unchanged unrelated rows, and quiescent sum-of-rows equality with Total.
The full syscall/yield event arrays must also match NULL-callback and legacy runs;
those unmeasured runs must not change counters. Payload bytes in buffered reads and
writes are checked. These checks cover bounded cases, not every arbitrary scheduler,
wire delivery, request or operating-system failure history.

Local deliberate mutations that omit destination reads, overcount destination writes
or lose the attribution token fail explicit assertions in both buffered and splice
paths. They are disposable test copies, not production modifications. The existing
UDP composed accounting, registry/concurrency, complete payload and UI checks remain
separate and mandatory.

### New execution evidence

Tested source: `951889519524951c7949cfc9bc3cb748899f161c`, tree
`21f99d7b526223bb1872cf59bfa02932efe4141e`, 111 tracked files.
Run `36668781490` concludes success on attempt 2, metadata updated at
2026-09-30T05:13:00Z. Both pinned UDP prerequisite jobs and statistics Linux passed
on attempt 1; only the statistics Apple job was rerun after a Simulator setup failure.
Its native/SDK and unchanged actual UI suite then passed on the same source and
original limits. This is not four newly executed jobs on attempt 2, nor a first-try
success. No IPA or release-composition product was generated.

| Layer | Actual inspected result |
| --- | --- |
| New TCP matrix | 15,552 parameter cases x three callback modes pass in ASan/UBSan and O3/strict-aliasing for Linux buffered/splice and macOS buffered. Actual formatter18 output matches the new C file. |
| Full payload and UDP | Each native mode passes 111 full-payload network cases, 24 controlled UDP accounting boundaries, 18 mixed/concurrent/restart associations with 126 complete echoes, and existing UDP/peer/header checks. Failed receive-to-client delivery does not erase successful In; unsuccessful send suffixes do not inflate Out. |
| Registry and counters | Eight writers/800,000 updates, concurrent registration/snapshot, normalized IP and allocation-failure cases pass. An additional 2,048 entries, ten caller capacities/canaries, growth races and finite-width wrap conservation pass. Apple counter/client/expanded-registry TSan passes within fixture scope. |
| Model and sampler | Existing numeric/format tests pass. The unchanged exact sampler body passes 98,516 checks per debug/optimized mode with 512 clients/64 intervals and snapshot growth. Old per-row publication is rejected. This verifies one client-state publication per snapshot, not one UI render. |
| Real elapsed retention | Linux input spacing 120.060168s, shrink30500 at300.196727s and1500 at420.231722s; final Apple spacing120.007955s, corresponding300.024350s and420.035636s. Total and the registered IP retain In78002/Out0 after replacement storage and history are reclaimed. |
| Source and SDK | Full ancestry/pin/29 UDP ownership mappings, baseline46, driver10, source/index/worktree/formatter18/reversal gates pass. Patched native C/header interfaces and all five production Swift files pass iPhoneOS27/ARM64 minimum17.2 checking with empty required C/Swift diagnostic logs. |
| Actual Simulator | iPhone16/iOS27.0 build24A434, one case passed, zero failures/skips, case182.299s; runtimeWarnings=[] and cleanup=[]. Original server/tabs/handshake/Stop/portrait/landscape predicates and deadlines remain. Five original screenshots inspected. |

In each orientation the real UI test transfers 64+2048+48001=50113 bytes per IPv4
and IPv6 client. Portrait Total In/Out/Sum is100.226/100.226/200.452KB; each IP is
50.113/50.113/100.226KB. After Stop/Start and the next orientation, Total is
200.452/200.452/400.904KB, each IP100.226/100.226/200.452KB. Landscape rows remain
scrollable; the overview is not a claim that every row is simultaneously unobscured.
Screenshots, accessibility values and exact network replies provide separate checks.

Retention uses the real composed forwarder, UDP, clock, allocator and Hev timer in
a native fixture, not a physical-device or full-server memory benchmark. Its test
communication timeout is600s to observe the300s hold; the app's default60s is unchanged.
No packets follow the second demand. Supplemental local replay observed shrink at
300.148731s and420.229109s with the same78002-byte counters. Scheduling/suspension
can delay reclamation; successful free does not prove byte-exact physical RSS change.

The independent prerequisite still checks UDP owner `6f9848e4` and its exact 29
mapped paths. Newer UDP owner `84d47e88` has the identical four runtime patches;
its changes are tests/documentation. This audit neither silently merges that new
history nor changes the dependency pin. A supplemental local run also passes its
145,459-case stream fixture against this statistics-linked core in ASan/UBSan and
optimized modes. That is not a new combined full-history prerequisite execution.

### Simulator setup failure and unchanged retry

Attempt1 Apple completed its native/SDK checks, then `simctl bootstatus` exceeded
the existing120-second limit before app/XCTest execution. Shutdown and delete also
exceeded their30-second cleanup limits. No XCTest result or app screenshot exists
for that failed setup; it is not a failed payload assertion or a successful UI run.
The original artifact11077981699 and exact diagnostic are preserved. Its internal
boot/cleanup cause is not established.

Only that Apple job was rerun at the identical commit. No timeout, test predicate,
warning rule, product code, cache, provider or host setting was changed. Attempt2
passes native, SDK, actual UI and cleanup. This resolves the required current run,
not the historical failure or a universal guarantee about Simulator startup latency.

### Development failures and verification boundaries

The first local fixture invoked the splice path outside a Hev task and then, in an
intermediate repair, released the test task before running it. These were test-harness
setup errors, not changes to or defects established in production. The published
fixture runs in one real task, keeps it alive through task-system execution and
asserts that every planned case completed. The retained first diagnostic and recorded
development history distinguish these failed harness attempts from the published
passing fixture. No source gate, timeout or warning rule was weakened to pass.

ASan on local coroutine runs warns about ignoring __asan_handle_no_return on an
alternate stack. Preserve that instrumentation limitation rather than suppress it
or certify all coroutine/library memory paths. The final current checks have no
reported failing assertion or sanitizer memory error within their executed scope.
Process-lived registry allocations intentionally use the existing detect_leaks=0
policy. Apple C/Swift SDK logs are empty, but the
raw UI build retains AppIntents extraction notices and matrix ASan logs retain the
alternate-stack warning. Do not call the entire toolchain diagnostic-free.

Supplemental Linux snapshot replay completed 27 initial successful build/run commands;
the next historical-sampling driver correctly failed because its required old blob
was absent. After fetching and SHA-1-verifying that exact old blob, the unchanged
driver passed current debug/optimized 98,516 checks and rejected the old per-row
publication behavior. No Git commit ancestry was invented. Four additional build/run
commands passed the latest-owner stream fixture. Snapshot execution and archived
integrity cannot replace full-history CI, Apple runtime or physical-device trials.

| Original current-run artifact | SHA-256 |
| --- | --- |
| Statistics Linux attempt1 / 11077203869 | 9140940d6bf429300db0c019a9a1b4ec5877984979cac91a4343dcf8258a173e |
| UDP Linux prerequisite attempt1 / 11076984820 | 775f416568e9281fda5886f63ca22294fb006d7927101f79eef5d334884ae80e |
| UDP Apple prerequisite attempt1 / 11077118150 | 4d3113d6d65dce6edf6ce30b307fbe23752d0c0562669e48e0e88d5b1bfd17a2 |
| Statistics Apple failed Simulator setup attempt1 / 11077981699 | 1b56462fee1951bb1765331969114143eebeb121e65a7962a000a1e68c72a8a8 |
| Statistics Apple attempt2 / 11078915623 | 8a5b09acce134acb2a271e0d39c3a485723621885f4db9753143d99534890fe4 |

All five current-run original ZIP SHA-256 digests and CRCs were checked. The final
statistics Linux/native Apple/UI source archives contain the same111 bytes-and-mode
entries and reconstruct the tested tree. The failed setup's two source archives also
match that source. Prerequisite source archives instead identify the exact69-file
UDP6f9848e4 owner, irrespective of aggregate workflow metadata. Both final native
archives match each other and the preceding source on243 regular files and30 symlink
targets. Full manifests and the actual formatter output match. The recorded Simulator
executable digest is retained as a runner observation; the executable itself is not
included or independently rehashed here.

The two earlier statistics artifacts were also hash/CRC/source checked, not counted
as new execution. Clean native reversal and reapplication of all seven patches
restores the identical source. The final source archive, publication metadata and
reversible project patch accompany the original evidence. Offline verification checks
integrity and correspondence, not a new compilation, network or physical execution.

### Publication and remaining limits

The final publication changes only README and this identical feature specification;
all other 109 tested paths retain their bytes/Git modes. Its direct parent and tree
identify documentation publication separately from runtime execution. No other
branch, native patch order, device permission, host, release or IPA is changed.

In/Out remain successful destination-side payload I/O, not client-side accepted bytes,
remote-delivery acknowledgements, IP/SOCKS headers, retransmissions, DNS-resolver or
whole-interface/billed traffic. Snapshots are independent atomic reads, not a global
transaction. Counters persist across Stop/Start but not process restart, distinct IP
entries persist for process lifetime, and finite integer/display precision remains.
These explicit contracts must not be recast as discovered defects or silently altered.

The known fixed-port multiple unknown-peer ownership/close limitation and valid
same-IP first-sender race remain separate UDP restrictions. Physical iOS27 SideStore
standalone installation, LiveContainer guest/shared-process execution, real background
survival and device CPU/RAM/energy/maximum-throughput measurements remain unperformed.
No new IPA or release-composition approval is implied. No newly reproduced production
regression or required current-suite failure remains within the new executed scope;
finite tests do not certify all possible deployments as defect-free.
