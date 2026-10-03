# Payload traffic statistics and client-IP tables

## Purpose and scope

This feature measures payload processed at the proxy's destination-side sockets and presents cumulative volume and observed transfer rate for Total and each client IP. The intent is to count successful I/O without losing completed work when a later operation fails, while keeping packet processing independent of UI visibility and sampling.

The feature inherits UDP compatibility and adds three native statistics patches plus Swift value models and a table view. It is not an interface monitor, VPN billing meter, remote-delivery acknowledgment counter or per-device identification system. The control-peer IP identifies an observed network endpoint, not a unique person or device.

## Functional behavior

### Measurement boundary

In is payload successfully read from destination sockets into the proxy. Out is payload successfully accepted by destination-side socket writes. Positive completed I/O is counted once even if a later read, write, cancellation or client delivery fails. Requested capacity, unsent bytes and buffer sizes are not counted as completed transfer.

SOCKS and transport headers, length queries, peeks, retransmissions, client-side duplicate measurements and system-resolver internals are excluded. UDP-over-TCP framing bytes are excluded from payload counts. An empty datagram is a valid message with zero payload bytes. This is a precise measurement boundary, not a claim that the destination application received every socket-accepted byte.

Retransmission exclusion refers to lower-layer retransmission outside these measured I/O calls. If an application submits identical payload again and the proxy performs another successful destination-side read or write, those bytes count again. The collector neither inspects content nor deduplicates application messages.

Total combines all counted clients. Every association retains the reference for its normalized TCP control-peer IP. Multiple connections from that same IP use one registered entry. Attribution failures use Unattributed without dropping the aggregate measurement. Closing an association or using Server Stop/Start does not reset process totals; a new application process starts new counters.

### Rate and display

`TrafficStatistics` derives rate from cumulative-counter differences divided by the actual elapsed monotonic sample time. The first sample, a non-increasing time or decreasing counters establishes a new baseline with zero rate rather than a negative or invalid interval result. Raw counters and rates are retained independently of display rounding.

The tables show In, Out and In + Out for speed and volume. In + Out is formed before display rounding. Volume uses SI KB/MB/GB/TB/PB and speed uses SI Kbps/Mbps/Gbps/Tbps/Pbps after conversion from bytes per second to bits per second. Values are rounded to exactly two decimal places using a fixed formatting locale. They describe observed traffic, not link capacity.

The native counters continue as traffic is processed. The view samples only while its tab is visible and the scene is active. Re-entering the view establishes a fresh rate baseline without resetting native cumulative volume. IP rows use stable registration IDs; Unattributed appears first when nonzero. Registration-order display is not lexical IP sorting.

## Implementation and ownership

`hev-stats-task-io.patch` provides the I/O accounting hook without changing the behavior of callers that use the existing entry or a null callback. `hev-stats-core.patch` owns aggregate counters, normalized control-peer registration and per-IP counters in `src/hev-socks5-misc.c` within the core repository; it also connects destination-side TCP/UDP I/O to those counters. `hev-stats-server.patch` exposes the server-facing snapshot functions and copies core snapshots into caller-owned public rows in `src/hev-main.c` and `src/hev-main.h` within the server repository. These three patches follow the inherited UDP patches in the manifest.

The native registry is process-lived and entries are append-only. Registration and snapshot coordination occur outside the per-packet lookup path. An association obtains its client reference once; successful I/O updates the appropriate counters through that reference rather than searching or reallocating the registry for every payload. Aggregate and per-IP reads are independent atomic snapshots, not one globally locked transaction.

`hev_socks5_transfer_client()` reads the TCP control peer, normalizes IPv4-mapped addresses and includes a native IPv6 scope identifier in the registry key. A 256-bucket table and one registration mutex locate or create a process-lived entry with a stable positive ID. ID 0 is the Unattributed fallback when lookup, address conversion or allocation cannot provide an entry. `hev_socks5_transfer_add()` uses relaxed atomic additions for the aggregate and chosen entry; snapshots take a stable list reference and invoke row callbacks after releasing the registry mutex.

UDP accounting uses the actual successful send result, message count and per-message length. It does not add a failed suffix or count completed messages again when an Apple send is retried. Destination receive bytes are accounted at the successful read boundary before a later rejection or client-forwarding failure could discard that observation. Peeking to learn a receive size never contributes payload.

The UDP buffer owner retains the association's client reference independently of payload storage. Growing, shrinking or releasing a temporary buffer therefore does not replace IP attribution or erase cumulative counters. The buffer hold interval and cleanup cadence belong to the UDP owner, not the statistics registry.

`TrafficStatisticsView` uses one visibility/scene-keyed Swift task. It samples immediately, then awaits approximately one second between samples and exits on cancellation. There is no hidden-tab sampling loop. A capacity query followed by a bounded native row snapshot tolerates concurrent registration: existing rows fit and newly required rows are reported for the next visible sample.

`hev_socks5_server_stats()` requires two non-null output pointers. `hev_socks5_server_client_stats(nil, 0)` returns required row capacity, including ID 0; a subsequent call copies up to the supplied capacity and returns the currently required count, not merely the copied count. No registry pointer escapes through this interface. A larger return causes the view to show that new clients will be included in the next sample instead of indexing beyond its row array.

The view builds a local `ClientTrafficStatistics` value snapshot and publishes it once, rather than publishing dictionary state after each row. All rows use the same Grid renderer, consistent directional columns, monospaced numbers and accessibility identifiers. The table is scrollable; view tests distinguish content accessibility from simultaneous visibility of every footer or row.

## Design rationale and resource cost

Counting at successful destination I/O gives a stable operational meaning across buffering, short writes, cancellation and protocol framing. Counting requested send lengths would overstate failed work; counting only successful end-to-end relays would lose reads when client delivery fails. The chosen boundary deliberately avoids both interpretations.

Association-local references keep registry lookup and allocation out of the packet path. Atomics permit concurrent writers without adding a global per-packet lock. Append-only entries preserve stable IDs and cumulative totals across connection lifetimes, at the cost of memory that grows with distinct registered IPs for the process lifetime.

Visible-only sampling avoids continuous UI work when statistics cannot be seen. Row snapshots and sorting still cost memory and CPU proportional to the registered data, and publishing a value does not make those costs zero. Independent live snapshots can briefly disagree with the aggregate while writers are active. UInt64 counters have finite range, and converting large counts to Double for display has finite precision. Neither display rounding nor rate-baseline resets change native totals.

## Verification contract

`Tests/Statistics/audit.py` checks the frozen functional composition separately from current-parent documentation inheritance. Its executable UDP prerequisite must equal the current declared UDP parent. The inherited test inventory is discovered from that parent’s complete `Tests/` tree and compared by contents, Git mode and staged index, so a newly inherited test cannot silently disappear from a manually maintained list. `Tests/udp_buffer_network.py` accepts only ENOTCONN/ECONNRESET from an already closed malformed stream; no-forwarding and EOF/reset assertions remain mandatory. The reusable UDP workflow is preserved under its dedicated workflow filename. Its native stages exercise buffered and Linux splice modes, actual collector behavior, concurrent registration/snapshot operations and sanitizer/optimized configurations. Null-callback and existing-entry paths must retain the same I/O and yield behavior.

The TCP accounting matrix combines read/write outcomes, cancellation points and attribution modes, requiring exact completed-byte totals and no movement in unrelated IP entries. The unchanged parent `udp_stream_boundaries.c` also runs directly on this seven-patch engine under sanitizers and optimization in each supported native I/O mode; the separate UDP prerequisite is not a substitute for this composed-engine execution. The inheritance regression rejects a missing or changed parent fixture, wrong mode or staged content, a stale executable/document prerequisite and omission from the composed execution list. UDP accounting fixtures cover partial message success, peeks, truncation, allocation failures, client delivery failure and platform retry boundaries. Actual loopback tests compare complete payload content, returned addresses, Total and each affected IP, including payloads larger than 1,500 bytes.

The live-retention forwarder uses actual UDP, allocator, clock and native timer behavior. After 48,001 and 30,001 bytes of input, the required cumulative In is 78,002 bytes in both Total and the registered IP even after expanded capacity is reclaimed. The fixture's long observation timeout is not the application's timeout setting.

Swift model tests cover delta/time/reset and formatting boundaries. The sampler contract executes the actual sampling body with controlled native rows and publication observations; it rejects per-row publication and hidden/cancelled activity that violate the view contract. The actual Simulator UI tests exchange known IPv4/IPv6 payloads, verify displayed Total/IP values and retain cumulative values across Stop/Start and orientation changes. Test-case counts are not counts of independent device deployments.

## Operation and limitations

The standalone branch provides the Statistics and Server tabs. The integrated release composes the same statistics implementation with server control, durable settings, background services and the icon. The statistics implementation does not own persistence or restart policy. A new UI model baseline can show zero instantaneous speed while existing native volume remains nonzero.

Use the branch's dedicated workflow or `python3 Tests/Statistics/audit.py` from a clean full-history checkout. Its UDP prerequisite and functional source references remain the declared tested inputs. The document parent may describe the same frozen UDP implementation through a current document snapshot; documentation work does not alter the native patch composition.

The inherited fixed-port multiple-unknown-peer UDP restriction remains. IP attribution is neither authentication nor device identity. Physical iOS 27 SideStore standalone and LiveContainer guest behavior, real VPN/hotspot traffic, background scheduling and device resource measurements require separate evidence. Configured minimum iOS 17.2 and SDK/Simulator results do not certify those physical layers.

## Related documents

The [UDP implementation](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/udp-compat/docs/features/udp-compatibility.md) defines inherited transport and buffer behavior. The [shared build guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) defines evidence boundaries. The current-parent document copies are recorded in `docs/documentation.json` and retained under `docs/branches` and `docs/features`.
