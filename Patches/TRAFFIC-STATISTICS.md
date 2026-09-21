# External-side traffic statistics

Apply the two existing UDP compatibility patches unchanged, followed by:

1. `hev-stats-task-io.patch` in `third-part/hev-task-system`.
2. `hev-stats-core.patch` in `src/core`.
3. `hev-stats-server.patch` in the server repository.

All sources remain pinned to the revisions used for the working UDP build.
`Tests/apply_traffic_stats.sh` checks those revisions before applying the patches.

## Meaning

- In: payload bytes successfully read from the external-facing relay socket.
- Out: payload bytes successfully written to the external-facing relay socket.
- Total: In plus Out, without counting the client-facing hop a second time.
- TCP and UDP are combined. SOCKS5 negotiation/headers, IP/TCP/UDP headers,
  resolver traffic, VPN overhead and transport retransmissions are not counted.
- Out means accepted by the local socket, not acknowledged by the remote peer.
  In is counted even if subsequent delivery to the hotspot client fails.
- Two process-lifetime 64-bit atomic counters persist across server restarts.
  They reset when the app process restarts; no concurrent reset API is added.
  Each counter is read atomically, but the pair is not a transactional snapshot.

## Implementation

The existing splice API remains available. A new optional synchronous callback
reports only reads from side B and writes to side B. Both the buffered path and
the Linux splice path keep their original buffering, I/O calls, scheduling and
error handling. SOCKS5 supplies a callback that only updates the two counters.
UDP sums successful datagram lengths once per returned batch. The receive path
counts before forwarding to the client; the send path counts successful sends.
No new socket, relay loop, data copy, task, lock or packet log is introduced.
The counters use relaxed atomics: they publish numbers, not other shared state.

The Statistics tab is between Server and Background. The separate Swift module
samples approximately once per second only when this tab is visible and the app
is active. Speeds use actual monotonic elapsed time and counter deltas, with a new
baseline on re-entry. Native counters do not depend on sampling or tab visibility.
Capacity units are decimal KB/MB/GB; rates are decimal Kbps/Mbps/Gbps.

## Validation

CI checks upstream C formatting, native TCP/UDP payload and source integrity,
exact asymmetric In/Out byte counts, handshake exclusion, one-way UDP, concurrent
workers, idle reads, and stop/start retention. Tests are not part of the IPA.
A pure Swift test checks units, elapsed-time sampling and baseline behavior.
Existing UDP compatibility tests remain unchanged. No measured performance or
battery improvement is claimed; phone streaming and background behavior still
require device testing after installation.
