# Traffic statistics — aggregate and client-IP payload accounting

## Target and unchanged baseline

The primary target is physical iOS27/iPadOS27 installed independently with SideStore
or executed as a LiveContainer guest. Signing, containers, permissions and shared
host process state differ; neither Xcode direct installation nor Simulator execution
substitutes for those targets. Configured minimum remains iOS17.2. SDK compilation,
Simulator, native tests, device archive/IPA and physical execution are distinct
verification levels. Original principles remain in docs/top-level-principles.md.

This feature extends `feature/traffic-statistics` at
`bb07d1795f010d624b1924cc06203af9aeb3c6a2`. Composition remains main75335d20 ->
UDP9909aa5f -> statistics. The completed Background9d87d7cf, other feature branches,
main, release8577bb1f and the previously supplied build9 IPA are not changed.
This standalone branch does not include Background, settings persistence, the
separate ServerController or the custom icon. No new IPA or release merge is part
of this feature implementation. The unchanged committed XCFramework is upstream
baseline input; products must rebuild and link the patched native library.

## Measurement contract

Existing aggregate In/Out remains authoritative and unchanged in meaning. In counts
successful payload reads from destination-side sockets; Out counts successful
payload writes to those sockets. Destination-side is a socket role, not a test for
public versus private destination addresses. TCP buffered/splice and UDP batch
boundaries are preserved, including partial successful I/O before error and external
receive bytes even when later forwarding to the client fails. System DNS resolver
traffic, SOCKS framing, IP/TCP/UDP headers, retransmissions, peer acknowledgements and
VPN/radio/billing usage remain outside the boundary. No packet inspection is added.

At the same existing accounting events, each amount also increments the bucket of
the SOCKS control connection's observed peer IP. Ports are ignored: TCP connections,
UDP associations and Hev UDP-over-TCP from one IP share a row. IPv4 and its mapped
IPv6 representation normalize to one IPv4 key; real IPv6 keeps its scope identifier.
An explicitly supplied UDP endpoint does not replace the requester's control-peer
identity. UDP peer discovery/filtering and forwarding policy are unchanged; fixed
UDP-port multi-association restrictions remain, and UDP Listen Port0 is still the
recommendation. No client protocol change, MAC/name discovery or device fingerprint
is introduced. NAT-hidden clients sharing one observed IP cannot be separated; a
changed IP is a different bucket. Same-IP reassignment merges usage by design.

Totals and IP buckets live for the process, not a connection. Stop/Start, closing
connections or hiding the screen does not erase usage. A new app process starts at
zero. No disk history, reset/export API, destination history or extra network request
is added. Failure to obtain/normalize the peer or allocate its bucket must not stop
relay: the aggregate and an explicit Unattributed bucket still receive the bytes.
Unattributed is hidden only while both its totals are zero.

## Native implementation and concurrency

The task-io statistics patch and its exact byte-count arithmetic are unchanged.
TCP uses the existing synchronous callback context. UDP carries the same context
through its two existing forwarding functions. A context is obtained once per relay
from the control socket, never per packet. No base object layout or native worker
scheduling policy changes. Original three UDP patches, native source pins, shared
build files, framework input, project/plist and permissions stay unchanged.

The core collector keeps a 256-bucket address hash registry and immutable process-
lifetime entries allocated by libc, not the task allocator. This deliberate lifetime
survives native worker/server teardown and avoids per-packet reference counting or
use-after-free during snapshots. Memory grows linearly with distinct observed IPs,
not packets or reconnects; entries are not silently evicted or reassigned. Allocation
failure sends that relay's usage to Unattributed. This is not an unlimited-memory
promise and hostile high-cardinality inputs remain a resource consideration.

A short mutex protects only lookup/registration and capturing a list head/count.
Byte updates use existing relaxed aggregate atomics plus relaxed per-IP atomics;
they do not take that mutex, allocate, stringify, query addresses, yield, call Swift
or log. Immutable links let readers enumerate a captured list without holding the
registry lock. Entries are never removed while relay code holds their pointer.

The additive public API `hev_socks5_server_client_stats(rows, capacity)` copies
caller-owned rows (id, numeric address, In, Out). It returns required capacity;
NULL queries the size. ID0 is Unattributed, IDs1..N are stable registry indices.
Only min(capacity, count) rows are written. If registration races the size query,
older rows still fit and newer rows appear at the next sample; no dangling native
pointer crosses into Swift. Existing aggregate API remains available unchanged.

Counter pairs and different rows are independently sampled, not transactional.
During concurrent traffic, aggregate and row sums can temporarily differ. At rest,
the sum including Unattributed must equal the aggregate (subject to UInt64 wrap).
Do not add global per-packet locking merely to force a visual live snapshot equality.

## Swift model and screen

The existing total sections remain. A new Clients by IP section lists stable rows
with expandable In/Out speeds and accumulated In/Out/combined usage. The existing
TrafficStatistics delta/format model is reused per native ID; no second formula or
native sampling thread is added. Counters are subtracted as UInt64 before Double
conversion. First samples, nonincreasing times or decreased counters establish a
zero-rate baseline. Decimal KB/MB/GB and Kbps/Mbps/Gbps retain their existing meaning.

One visible/active-tab task samples the aggregate and rows immediately and about
once per second using monotonic systemUptime. Leaving the tab or inactive scene
cancels the task; returning starts fresh speed baselines, not fresh native totals.
This is unrelated to Background's 0.5-second recovery timer, which is untouched.
Native counters continue while the server runs even when the view does not sample.
The list is stable by registration ID rather than jumping around with current speed.

Costs: one IP lookup/registry lookup per relay, extra per-direction atomic additions,
process-lifetime memory per distinct IP, and visible-tab snapshot/format work. There
is no zero-overhead claim or measured iPad energy/throughput improvement. Local UDP
fixture timing is an observation, not a physical-device or before/after benchmark.

## Validation and reproduction

Use a full clean Git checkout with historical objects:

```
python3 Tests/Statistics/audit.py
# On the recorded Xcode27 host:
python3 Tests/Statistics/ui_audit.py
```

The workflow preserves exact completed UDP prerequisites. Shared main/native-input,
index, source-pin, reverse-patch, marker and port-reservation guards remain. Only
four explicit statistics runtime paths may change from bb07d179: two Swift files
and the stats core/server patches; the task-io and UDP patches stay frozen.

The native audit retains original aggregate/partial-I/O tests and adds real dual-stack
TCP/UDP and UDP-over-TCP attribution, same-IP multiple connections, asymmetric TCP,
fd churn, Stop/Start, and 2000 small UDP exchanges. A direct actual-collector fixture
injects only peer lookup/allocation failures and tests mapped addresses, IPv6 scope,
unknown fallback, snapshot capacity/canaries, reentrant enumeration, concurrent
registration/writers/readers, stable IDs and quiescent equality. ASan/UBSan apply to
the included collector; macOS TSan additionally checks its actual concurrent paths.
Test-only injection is not a physical network event. Swift model tests cover per-IP
baselines/rates, unknown visibility, idle counters, overflow/time edges and tab reset.

The uninstrumented Simulator test retains original Server controls, real greetings,
orientation/scrolling/navigation gates and adds a real locally relayed UDP payload
plus expanding its client-IP row. No production source is replaced by test doubles
in that app. The committed source remains distinct from the disposable product copy.

### Completed implementation and validation — 2026-09-28

The tested source is `065855d41f61dba1c96e8b27e5ec44ad184e68e1`, Git tree
`4a72eb9d14c3f325cfeb22cc2bf7b61343ee0741`. Run `36382538730`, attempt 1,
completed all four jobs successfully: exact UDP prerequisites on Linux/macOS and
statistics on Linux/macOS, including the actual uninstrumented Simulator app.
The closing commit updates only README and this identical feature specification;
the other 85 of 87 tested paths retain their exact bytes and Git modes. It does not
claim a new execution of a documentation-only commit.

| Evidence layer | Actual result and scope |
| --- | --- |
| Prerequisite ownership | Both jobs checked out UDP9909aa5f, not the triggering statistics commit. Both original 57-file source archives match. Main ancestry, all 17 mapped owner files, original three UDP patches and source pins remain exact. |
| Existing aggregate accounting | Linux buffered/splice and macOS buffered pass the original network scenarios (20 executions per mode), eight peer/queue cases, 8 writers/800000 aggregate updates and partial-I/O/cancellation probes. Existing external read/write boundaries and the task-io patch are unchanged. |
| Real native IP attribution | Each mode passes dual-stack control-peer attribution, same-IP connections/associations, known/unknown UDP endpoints, asymmetric TCP/half-close, UDP-over-TCP, concurrent TCP/UDP, socket-number churn, and Stop/Start retention. Per-IP sums including Unattributed equal aggregate totals at rest. |
| Collector concurrency/failures | The actual collector fixture passes IPv4-mapped normalization, IPv6 scope, lookup/allocation failures, no hot-path lookup, snapshot capacity/canaries, callbacks outside the lock, concurrent registration/reads and eight writers. ASan/UBSan pass on the included collector and boundary probes; macOS also passes actual-collector and aggregate TSan. These are scoped sanitizer targets, not whole-program sanitizer certification. |
| Swift models | Existing 10000-sample aggregate model passes. The per-IP model passes debug/optimized: independent rates, first/idle samples, stable IDs, unknown visibility, counter/time edges and resetting view baselines without resetting native totals. |
| Guards and Apple SDK | Common 46-case and statistics 26-case input/marker checks, three audit-driver and six pipe-reader cases, format/reverse-patch, clean source/index and composition checks pass. Patched native C/headers and five production Swift files typecheck for ARM64/iOS17.2 against iPhoneOS27 with warnings-as-errors and empty diagnostic logs. |
| Simulator product and UI | The disposable product rebuilds and links the patched native library. iPhone16/iOS27.0 build24A434 runs one XCTest successfully, zero failures, 71.368 seconds case time. Both portrait/landscape exercise actual Start/Stop, SOCKS greetings, a real 64-byte UDP payload, client-row visibility/expansion and tab navigation. Original four screenshots inspected; cleanup is []. No production mocks or injected counter values are used in that app. |
| Archive/IPA and physical devices | No iPhone archive/IPA or release merge is produced. SideStore standalone and LiveContainer guest execution, physical-device/network behavior and before/after power/throughput/latency are unperformed. |

Original CI artifact ZIPs were SHA-256/CRC verified. Linux native, macOS native and
Simulator source ZIPs share the expected commit comment and all 87 files/modes;
independent Git-tree reconstruction matches the tested tree above. The two UDP
prerequisite source ZIPs independently match the owner ref and each other. The
closing documentation files are the only final-source differences.

A supplemental Linux/Swift6.2.1 replay independently rebuilt the exact patched native
source and reran buffered/splice network/accounting/collector tests plus ASan/UBSan,
and both Swift models in debug/optimized modes. Another local test ran 24 concurrent
TCP+UDP tasks using distinct IPv4 control peers127.0.0.2/127.0.0.3 to the same
server/destinations. Their directional totals were20544/20676 bytes, respectively;
the aggregate was41220 bytes per direction, also retained over Stop/Start. This is
local loopback verification, not a physical LAN or device test. It does not replace
the full-history CI provenance checks or Apple execution.

The 2000 sequential 64-byte UDP echo fixture per mode remains only a local timing
observation: this run's Linux buffered/splice medians were0.141/0.143ms and macOS
buffered0.166ms. It is not an old/new benchmark, maximum packet-rate test or evidence
of no overhead. IP-cardinality memory growth and independent live snapshots retain
the limitations described above. In UI, a single localhost client was exercised;
multiple actual device rows, every Dynamic Type/keyboard case and iPad layouts were
not physically tested. Screenshots do not certify every cell is visible at once.

Recorded Apple host: Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428. Compiler diagnostics are empty, but raw build
logs retain tool/framework diagnostics; not every warning category is claimed absent.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux10953452120 | 4e3bd8a38d124498902820333f358f33bafbacda572ebcaaa89e3057fa38a823 |
| Statistics macOS10953129549 | ed426a1edcdaa41cc17bc3ac95b3ca6bb1313d446fc99f61098d66f7d81226be |
| UDP Linux10953122325 | 9c235a1c7f9b4da9223a84aa2362fd4e632a87471c35253a3b95b2a585ef49c6 |
| UDP macOS10952633248 | a6712a2508a3041f954d62072f387c0bb4f210762c1dd85fcbf45ab64d59c9af |

### Retained UI failures and their correction

Earlier implementation runs did not pass all UI gates. Run36377790407 left the
landscape Form at0percent after application-level swipes. Its artifact10951348700
(SHA25658c031f7412f7e1eb66317d1a6cee60498b3255735a87af7298031ea7af6d420)
was retained by the preceding resume. Commit12a70a4 targeted the recorded CollectionView
instead; run36379621481 then scrolled to100percent past the retained expanded client
header. The raw accessibility snapshot still contained its Total Out0.13KB; the
header was above the visible cells. That attempt failed the client-button assertion
(82.596-second XCTest) and subsequently exceeded the existing900-second xcodebuild
process timeout. Original artifact10953370179 is preserved unchanged, SHA256
08605fba59db7df76b84f7153b84e79f23f56243e4443613c2774cfffef6770b; cleanup was [].
This evidence identifies a test scroll-position problem, not lost native counters.
The later result-completion timeout's internal cause is not established.

Commit065855d4 changes only the test gesture sequence: use a bounded return to the
existing top section, then short content drags to find the IP header without skipping
it. The test still requires both orientations, reachable client header, expansion,
actual payload, Server control behavior and original timeouts. No production layout,
accounting, sampling, native code, assertion removal or timeout increase was used to
manufacture a pass. The final fresh run passes all these gates. Earlier failures
remain failures and are not retrospectively relabeled successful.

The preceding aggregate-only specification and its successful36226383235 results
are preserved exactly in docs/history/statistics-before-client-ip-20260928.md.
Only feature/traffic-statistics advances. Background9d87d7cf and its0.5-second audio
recovery are unchanged, as are the other feature/main/release refs and old build9 IPA.
Physical SideStore, LiveContainer, real device IPv4/IPv6/VPN/hotspot/Moonlight, long
locked-iPad operation, power and before/after throughput/latency remain unperformed
for this new feature. The existing build9 IPA does not contain these changes. A
future release integration must inherit this feature and run its combined validation.
