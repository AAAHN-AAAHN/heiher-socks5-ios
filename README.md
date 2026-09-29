# Traffic statistics with the latest UDP compatibility owner

## Completion — 2026-09-29

The latest UDP integration and all applicable full-history native, SDK and Simulator
checks passed at the exact source recorded in the final section below. The original
implementation checkpoint is retained as historical context, not a current pending
CI result. Physical installation/execution remains untested for this revision.

## Integration and ancestry

This composition integrates completed UDP owner
`6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5` into statistics owner
`a5c4e6af4f51b64e1e47c0b2c84fd4cc2af661ee`. Both are actual parents of the
integration, not merely labels. Main `75335d201cb1e541bb153e9899badbc11ccf1973`
remains the baseline ancestor. The full-history Linux/macOS native and iOS27
Simulator verification is now complete; exact evidence is recorded below.

The exact preceding README is retained in
`docs/history/statistics-before-dynamic-udp-20260929.md`; earlier reviews remain
historical evidence. In particular, their former 1500-byte UDP truncation and
UDP-over-TCP rejection are not descriptions of this new composition. This README
and `docs/features/traffic-statistics.md` are identical. The inherited UDP README
is preserved exactly at `docs/branches/feature-udp-compat.md`, alongside its complete
feature specification, tests, four patch files and dated reviews.

## Environment and responsibility

The primary target is a physical iOS27 device installed independently by SideStore
or executed as a LiveContainer guest. Signing, permission, container and process
boundaries differ. Native host/SDK/Simulator results do not certify either physical
path. The configured minimum remains iOS17.2; that does not prove execution on all
OS releases. No host, entitlement, permission, background mode or installer is
changed. The four principles in `docs/top-level-principles.md` apply unchanged.

Only statistics plus its completed UDP dependency are present. This is not a new
release, Background, persistence, icon or separate ServerController integration.
Root tabs remain Statistics and Server. All five production Swift files, Xcode
project, Info.plist, app resources and defaults are byte-identical to a5c4e6af.
Neither a new archive/IPA nor a modification of the existing build9 is implied.

## Exact source and patch composition

Source pins remain server b3585289622561caf4b8789b436cc8820ecd6be0,
core162dd996299fc2d2bff2dd63728f8a2cd71ed31a,
task328f35d903221b51811b3d02b277d665dfbdc75f and
yaml162227cd7d2b6108bc8bc133273e11413222ddf4. The original app pin and committed
unpatched XCFramework baseline are unchanged. A product build must rebuild the
manifest's patches; the baseline binary is not the newly composed implementation.

Apply, in order:

1. `hev-udp-port-zero.patch` — initial unknown client port handling.
2. `hev-udp-sockaddr.patch` — IPv4/IPv6 receive-address normalization.
3. `hev-udp-peer-filter.patch` — source validation and rejected-queue continuation.
4. `hev-udp-dynamic-buffer.patch` — adaptive contiguous receive buffers, reclamation,
   full datagram handling, Apple sendspace and RSV/FRAG checks.
5. `hev-stats-task-io.patch` — destination-side TCP payload callbacks.
6. `hev-stats-core.patch` — aggregate/control-peer-IP counters and UDP callbacks.
7. `hev-stats-server.patch` — existing public snapshot API.

All four UDP patches are exact owner bytes. The task-I/O and server statistics
patches are also unchanged. Only the UDP hunks of the statistics core patch are
adapted; its registry, TCP, public headers and callback implementations remain exact.
Shared Build/check.py/build.sh, baseline manifest and upstream pins are not edited.
The prerequisite workflow executes the fixed completed UDP owner, not the statistics
checkout. Exact mapped-source and actual-ancestor checks enforce ownership.

## Meaning of Total, In, Out and IP rows

Counters represent successful destination-side payload I/O, not the application's
whole network footprint. Out is what the destination socket accepted for sending;
In is what the destination socket actually returned to the relay. Client-side reads,
SOCKS headers, length probes/peeks, allocation capacities, OS wire headers and
retransmissions are not added again. Out does not confirm remote delivery. In remains
counted if later client delivery fails or a received datagram is rejected.

Normal full datagrams now retain their complete lengths, including 2048, 48001 and
65000-byte tested payloads. Invalid client RSV/FRAG input contributes no destination
Out; empty payload contributes zero bytes, not an artificial packet charge. If an
unexpected destination read is truncated, count only its actual copied return length,
not its advertised original length or allocation capacity; discard the incomplete
message rather than forward it. Memory and protocol/path limits remain distinct.

TCP buffered and Linux splice callbacks are unchanged. UDP Out sums only the final
successful prefix returned by the existing send helper, including Apple retry without
duplicating previous successes. UDP In is accumulated before descriptor filtering and
before the all-rejected early return or client send. Thus completed reads survive
later query/allocation/send failure. A process-lived IP reference is stored once in
the association's private UDPBuffers state; buffer growth, shrink and cleanup do not
clear or move that reference. No public UDP ABI change or extra lookup per packet.

Rows are keyed by the SOCKS TCP control-peer IP, not destination or client UDP port.
IPv4-mapped addresses normalize to IPv4; IPv6 scope participates where present.
Same-IP associations share a row. NAT-shared IPs are not separate physical devices.
Failed identity/allocation uses Unattributed while preserving aggregate bytes.
The 256 hash buckets are not a 256-IP cap. Distinct IP entries persist for process
lifetime, so memory grows with distinct peers; relay callbacks use relaxed atomics
without taking the registry mutex. Stop/Start and tab changes do not reset counters;
process restart does. No persistent disk history is added.

Total and row fields are independent atomic snapshots, not one transaction. During
active traffic their sums can temporarily differ; after traffic settles, sum of all
IP/Unattributed rows equals Total. uint64 counters eventually wrap and Double/UI
formatting has finite precision; rounded displayed rows need not algebraically sum
exactly. Tests compare raw counters independently of display rounding.

## Preserved presentation and sampling

Total appears first, then IP rows in registration order. Each table has In / Out /
Sum columns and Spd. / Vol. rows, explicit three decimals, decimal KB through PB and
Kbps through Pbps. Sum is computed without altering raw accumulation. The existing
single approximately one-second sampling task runs only for the visible active tab.
Returning to the tab rebaselines the rate while volume remains cumulative; sampling
uses monotonic uptime. Existing cancellation guards and one value publication are
preserved. No second renderer, timer, observer or diagnostic UI is added.

The actual Simulator test retains original Start/Stop, native listener, small IPv4
and IPv6 relays, scrolling, alignment and portrait/landscape assertions. It adds
2048- and 48001-byte real relays for each control-peer IP and verifies exact Total/IP
In, Out, Sum values in the unchanged app after Stop. Each orientation contributes
64+2048+48001=50113 bytes each way per IP. These are test peers, not UI mock counters.

## Adaptive-buffer policy and resource cost

The inherited policy is unchanged: base1500, growth rounded up by500, HOLD300seconds,
CLEANUP60seconds. Each actual demand updates only its own 500-byte expiry bucket;
small demand does not extend old large capacity. The owner task independently wakes
for cleanup when needed, separate from communication timeout. No added thread,
Swift timer, global pool or lock. Capacity has no arbitrary65536 allocation cap,
but numerical overflow, allocator failure and protocol lengths remain checked.

Apple uses SO_NREAD; Linux uses length-only MSG_PEEK|MSG_TRUNC. Sizing never counts
as In. There is one extra query per datagram and Linux bulk-receive amortization is
reduced. History adds about1.6percent of large replacement capacity. The original
base slab remains beside expanded contiguous replacements. Shrink can momentarily
own both old/new allocations; failure retains valid old storage for the next sweep.
Freeing ownership does not guarantee immediate RSS reduction. Extended blocks are
freed on shutdown and may be reclaimed only when no I/O references them. Scheduling,
blocked I/O and suspension can delay the60second maintenance opportunity.

This integration adds one private pointer per association (8bytes on ARM64), not per
packet or size bucket. The existing per-batch sum and aggregate/IP atomic additions
remain. No payload concatenation, allocation per packet, new history, timer or
retention algorithm is introduced by statistics. Prior host benchmarks are prior
observations, not measurements of this exact integration or iPhone energy claims.

## Validation and reproduction

Use a clean full-history checkout: `python3 Tests/Statistics/audit.py` for native,
policy, registry, model and applicable SDK checks, then on a real Apple toolchain
`python3 Tests/Statistics/ui_audit.py` for Simulator. The workflow first reruns the
independent exact UDP owner on both hosts. A source ZIP lacks required historical
Git objects and cannot replace this checkout. A native/Simulator pass is not an IPA
build or a SideStore/LiveContainer physical execution.

Existing TCP partial-error/cancellation, UDP successful-prefix, registry concurrency,
all-IP sums, mapped address, fd churn, Stop/Start, sanitizer/TSan, Swift model/sampling,
source pins, formatter18, clean index/worktree and exact reversal gates remain.
Former small-buffer boundary cases now require full payload and exact per-IP deltas;
the old owner remains a negative control. New composed tests cover peek exclusion,
raw In before all/mixed rejection, partial query/allocation/send failure, Apple retry,
failed UDP-over-TCP client delivery and buffer cleanup without counter reset.
A real48001 then30001-byte input120seconds later is relayed by the composed forwarder;
after the two actual300second holds, Total and its IP still read In78002, Out0.
Independent UDP/header network tests also run against the statistics-linked binary.

The source merge, fresh execution identities and limits are recorded in
`docs/reviews/statistics-dynamic-udp-20260929.md`. No prior SUCCESS marker or old source
archive may be reused as a new successful run. No assertion, timeout, warning or
formatter gate is weakened for this integration.

## Remaining boundaries

Use local UDP Listen Port0 for multiple unknown peers; the existing default1080 is
not silently changed. Fixed-port unknown-peer association/independent-close limits
and valid same-IP first-sender races are not solved by this integration. No SOCKS
fragment reassembly, new authentication, host repair or arbitrary network routing is
added. Normal UDP and UDP-over-TCP use different headers. User-space buffer capacity
does not override wire/path limits or guarantee delivery. Native allocator, socket
send high-water and process lifetimes remain distinct documented resource scopes.

Physical iOS27 SideStore install/run, LiveContainer guest load, actual background
survival, calls/Bluetooth, device energy and maximum throughput remain separate
unperformed evidence levels until actual records exist. This composition does not
update release/integrated or the other feature owners. All evidence is scoped, not
a proof that every possible network and scheduler history is free of defects.

## Exact-source verification — 2026-09-29

Run `36550874934`, attempt 1, completed successfully at 2026-09-29T10:09:34Z.
All four jobs passed: independent Linux/macOS UDP prerequisites at
`6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5`, and Linux/macOS statistics at
`c89a2d8bf4dcdae0320d0340bb4f2d9ceb9d4757`. The latter merge has both the prior
statistics owner and this UDP owner as real parents, tree
`be4647c36c54e659d4e6981edf5313306da2345d`. No source rewrite or retry was needed
to obtain the terminal CI result. A documentation-only closure is not a new execution.

Each native mode passed the retained TCP/UDP and registry gates, 111 complete-payload
boundary cases, 24 composed accounting cases in sanitizer and optimized modes, and
18 additional mixed/concurrent/restarted associations. Linux exercised buffered and
splice I/O; macOS exercised buffered I/O plus the applicable ThreadSanitizer gates.
The 111 cases require full original bytes beyond the former 1500-byte limits, not
truncated-prefix success. Normalized peer rows and the aggregate are checked together.
Queries, headers and unused capacity do not count. Successful send prefixes and
actual destination reads remain counted even when later work fails or is rejected.

Actual elapsed reclamation retained Total and peer In=78002, Out=0 after real
48001-byte and 30001-byte inputs and no subsequent payload. Capacity 48500 -> 30500
occurred at 300.103060s on Linux / 300.024134s on macOS after the first input;
30500 -> 1500 occurred at 420.209849s / 420.038323s. The fixture uses its own long
communication timeout, not a changed application timeout. These are observations,
not hard scheduling guarantees under blocked I/O or process suspension.

The unchanged production app also passed one iPhone16/iOS27.0 Simulator XCTest,
zero failures/skips, case time 121.009s, with empty runtimeWarnings and cleanup.
In each orientation it relayed 64, 2048 and 48001 payload bytes through each of
127.0.0.1 and ::1. Portrait Total In/Out=100.226KB and each peer=50.113KB;
landscape after Stop/Start Total In/Out=200.452KB and each peer=100.226KB.
The corresponding Sum cells were checked from the unrounded values. Screenshots,
exact source archives and XCTest results were inspected, not just a status badge.

The native/Simulator toolchain was Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4,
and macOS27.0 26A428. Required C/Swift SDK compiler diagnostic files are empty.
The UI build retains AppIntents metadata-extraction notices; an empty compiler or
runtime-warning result does not mean every tool emitted no diagnostic.

All four original artifact ZIP digests and CRCs were checked. The three statistics
source archives contain the same 110 files and Git modes at the tested merge; both
UDP prerequisite archives contain the same 69-file UDP owner. All 29 mapped UDP
paths and five production Swift files are preserved. Native archives agree on 243
regular-file bytes/modes and 30 symbolic-link targets. POSIX symlink permission bits
differ between host tar formats (0777/0755); Git symlink types/targets, not these
host permission bits, establish their source identity. Compared with the prior
statistics native source, only hev-socks5-udp.c changes. Within that file, the latest
UDP owner gains fourteen statistics C lines and no removals.

Supplementary archive-based Linux rebuilds passed actual-source accounting in ASan/
UBSan and optimized modes, all 111 network cases and the 18-association integration.
Three disposable mutations (skip rejected In, drop partial Out, remove IP attribution)
each fail the unrelaxed oracle. Mutants and test substitutions are not production.
These supplemental checks do not replace the full-history CI or Apple results above.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux11026110312 |09b0421a690186e205a2769c02f14e569684b3d58ce8102d9fdc6f4d45889a33|
| Statistics macOS11024774724 |657475d0b98db511773958a84951cd42b7bf88e56a17cdc465176f8dc76f32f6|
| UDP Linux11025051707 |18fe21af5c73cf440e576d93d74bc2f0adfe091441d2c381912900ee4bb9c679|
| UDP macOS11025317455 |1ef49780f7bd87b82cdf03ba72d91eabf4cb643ea9ce7f2329f2ade460f59095|

No failing mandatory case remains in this executed integration scope. Existing
fixed-port unknown-peer association lifetime restrictions, valid same-IP first-peer
races, independent live snapshot reads, process-lived IP-registry growth, wire/path
bounds and allocation failures are not eliminated. No claim is made for physical
SideStore standalone or LiveContainer guest execution, device background/power or
maximum throughput. No IPA or release integration occurred. Other branch heads are
unchanged. The operational statistics boundary remains successful destination-side
payload I/O, not all application or interface wire traffic and not remote delivery ACKs.

## Documentation closure and correspondence

This closure changes only README.md, its byte-identical feature specification and
`docs/reviews/statistics-dynamic-udp-20260929.md`. All other 107 of the 110 tracked
paths retain the tested commit's exact bytes and Git modes, including the runtime,
all seven patches, tests, workflows and pinned dependencies. The completed UDP
owner remains `6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5`.

The publication commit descends directly from the tested statistics merge
`c89a2d8bf4dcdae0320d0340bb4f2d9ceb9d4757`. Its own Git metadata supplies the final
commit/tree identity; the run above supplies execution evidence for the unchanged
code. No new runtime execution is claimed for this documentation-only commit.
