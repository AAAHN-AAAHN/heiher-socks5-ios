# SOCKS5 for iOS: traffic-statistics

This is the focused `feature/traffic-statistics` branch.
For the complete app use `release/integrated`; pristine upstream remains on `main`.

Build and verification: [instructions](docs/build-and-validation.md).
The following specification is also preserved verbatim at `docs/features/traffic-statistics.md`.

# Traffic statistics: native counters and a sampled iOS display

## Purpose and branch boundary

`feature/traffic-statistics` adds both the C measurement path and the Swift display.
Its sole feature prerequisite is `feature/udp-compat`: accurate native UDP testing
on Darwin requires the two compatibility repairs. It does not include background
execution, JSON configuration storage, the custom icon, or the settings lifecycle
controller. Statistics is not a UI that guesses byte counts from an interface.

The owner requested a display resembling the concise Python proxy statistics:
In/Out instantaneous rates, cumulative In and Out, and their combined total. The
observation point is explicitly the external-facing side of this application.
Counting both client-facing and external-facing sockets would double-count relayed
bytes and invert the meaning of generic process receive/transmit totals.

## Measurement contract

- In is payload successfully read from an external-facing relay socket.
- Out is payload accepted by that external-facing socket's successful write/send.
- Total is In plus Out. TCP and UDP share these process-wide sums.
- Out is not remote receipt or acknowledgement. In remains counted if forwarding
  to the hotspot client later fails.
- SOCKS negotiation and UDP encapsulation, DNS resolver queries made by the proxy,
  IP/TCP/UDP headers, VPN overhead, and transport retransmissions are excluded.
- Counters last for the app process, including server Stop/Start. They are not
  configuration and are not restored by JSON import. No concurrent reset API exists.
- Each 64-bit counter is atomic; the pair is not a simultaneous transactional snapshot.

## C implementation and patch boundaries

`hev-stats-task-io.patch` extends HevTaskSystem's existing splice implementation.
The old `hev_task_io_splice()` remains an uninstrumented wrapper over the same loop.
`hev_task_io_splice_with_stats()` accepts an optional synchronous callback reporting
reads from side B and writes to side B. The buffered `readv`/`writev` and Linux
`splice` paths preserve their buffers, partial writes, EOF, error handling and yield
behavior. Successful byte counts are published before the loop yields or exits.
Callbacks must neither block nor yield. This is not a copy of the TCP relay loop.

`hev-stats-core.patch` wires the SOCKS5 external side into that callback and adds two
`_Atomic uint64_t` counters to the existing misc module. The counters use relaxed
operations because they publish numbers, not the lifetime or contents of another
object. UDP Out sums only the successful prefix returned by the existing sendmmsg
wrapper. UDP In sums the received lengths before forwarding. Batch aggregation
avoids an atomic update for every individual datagram when several are processed.

`hev-stats-server.patch` exposes `hev_socks5_server_stats()` through the public C
header used by Swift. It does not add an independent server, packet sniffer, or
process-wide symbol hook. All three patches are separate from the UDP repairs.
The statistics C changes remain 102 additions / 5 deletions (net 97 lines).

## Swift implementation

`Socks5/Statistics/TrafficStatistics.swift` calculates deltas using monotonic uptime.
It subtracts UInt64 totals before converting deltas to floating-point, preserving
small changes when cumulative counts are large. A non-increasing timestamp or
counter decrease resets the sampling baseline instead of showing a negative rate.

`TrafficStatisticsView.swift` reads totals approximately once a second only while
its tab is visible and the scene is active. Task cancellation stops UI sampling,
not the native counters or network. Re-entry starts a fresh rate baseline. There is
no dispatch to Swift per packet and no network delay to form UI batches. Totals use
decimal KB/MB/GB; rates use decimal Kbps/Mbps/Gbps, with bytes multiplied by eight.
The native totals still advance in the background whenever the server can execute.

## Efficiency and non-goals

No new relay sockets, payload buffers, growing histories, packet logs, locks, or
per-packet tasks are introduced. The optional callback and atomic arithmetic have
nonzero cost. Busy multi-worker contention is possible; no measurement currently
justifies worker-local arrays, periodic merging, padding, or forced inlining.
The feature is resource-light, not mathematically proven to minimize CPU use among
all implementations. No packet capture, connection history, graph, traffic limit,
reset service, or interface-wide accounting was requested or added. The two Swift
files and three C patch files keep the previously verified implementation and style.

## Tests and historical decisions

`traffic_stats_regression.py` uses actual Hev sockets and exact asymmetric TCP
amounts, known/unknown IPv4 and IPv6 UDP, one-way UDP, header exclusion, four-worker
concurrent TCP/UDP, idle reads, and process-lifetime totals after a server restart.
`traffic_statistics_model.swift` checks units, elapsed-time rates and re-entry.
Existing UDP tests are run first. Linux buffered and splice paths and macOS buffered
I/O are separate test targets. Historical audit probes exercised partial writes,
EAGAIN, EOF, EPIPE, ECONNRESET, concurrent counter reads, and sanitizer runs;
those old logs remain in the archive history and are not presented as new results
unless rerun in the current workflow.

Interface-only counters were rejected for this feature because they include other
apps or duplicate the two proxy hops. Runtime syscall hooking and reimplementing
I/O in Swift were also rejected: the core already knows the bytes and direction.
The integrated release copies these production statistics sources without changing
the measurement contract. Read `docs/build-and-validation.md` for the actual build
and test commands and their platform limits.
