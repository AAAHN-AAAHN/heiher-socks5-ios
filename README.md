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

### Execution status

Implementation candidate; current complete native/SDK/Simulator results must be
recorded after the actual run. Local isolated collector code has passed concurrent
and failure-boundary tests, including ASan/UBSan, and the new pure Swift model passes
debug/optimized. Those supplemental local checks are not a complete linked native
build, Apple SDK or Simulator result. All failures remain failure evidence until
resolved and a new exact-source run completes; no earlier pass is borrowed.

The preceding aggregate-only specification and its successful36226383235 results
are preserved exactly in docs/history/statistics-before-client-ip-20260928.md.
Physical SideStore, LiveContainer, real device IPv4/IPv6/VPN/hotspot/Moonlight, long
locked-iPad operation, power and before/after throughput/latency remain unperformed
for this new feature unless separately recorded. An old build9 IPA does not contain
these changes. Final release integration must inherit this feature and run its own
combined validation.
