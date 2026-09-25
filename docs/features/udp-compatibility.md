# UDP compatibility for the native iOS SOCKS5 relay

## Final re-audit scope — 2026-09-26

This is the independent `feature/udp-compat`, not an integrated application.
The three established native patches are unchanged. This revision repairs a
remaining peer-test port-reservation mismatch and binds audit inputs to their Git
revision. Local old/current controls passed; a new native/Apple CI run is required
before this revision is recorded as verified. Earlier passes are historical results.

The complete preceding README is preserved byte-for-byte in
`docs/history/udp-before-final-audit-20260926.md`. It retains the original user
observations, two-patch audits, introduction and correction of peer filtering,
failed runs, later successful runs and exact artifact identifiers. Its earlier
"two patches" and verification statements describe those historical revisions.
This README and `docs/features/udp-compatibility.md` are identical.

## Target, baseline and ownership

The intended user environment is a physical **iOS 27 iPhone**, installed through
**SideStore** independently or run as a **LiveContainer guest**. Signing, container,
permissions and host behavior differ. Neither an SDK compile nor a Simulator test
establishes either physical installation path. The configured minimum stays
**iOS 17.2**, not certification of every intervening OS. Record exact toolchain,
OS/build, tested revision and installation method for each actual execution.

Main remains `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`. Build/features.json declares
only `udp`, the patch order and fixed source pins. Build/upstream.json preserves
app `180012e8b9dbaa2002a68ebd2c75bccebcfb789c`, server
`b3585289622561caf4b8789b436cc8820ecd6be0` and that server's submodule revisions.
These are the established verified snapshot, not floating upstream HEADs.
The committed XCFramework stays the unpatched shared baseline. The standard feature
build applies declared patches when rebuilding its native library before linking.
This audit does not replace that framework or make an iPhone archive/IPA.

No statistics, Background, JSON storage, server-controller or custom-icon feature
is included. Existing app configuration provides single-scene ownership and a
local-network usage explanation. No BGTask, NetworkExtension, resolver replacement,
new permission, host-ID override or LiveContainer IPA patch is introduced.
The current independent server UI and its defaults remain unchanged; continuous
background execution belongs to the separately composed Background feature.

## Three patches and their reasons

| Patch | Responsibility |
| --- | --- |
| `hev-udp-port-zero.patch` | In the server's `hev_socks5_session_udp_bind`, avoid the invalid early UDP connect when the expected client source port is zero. Preserve nonzero connect/error behavior, binding and reply order. |
| `hev-udp-sockaddr.patch` | In core UDP receive/reply paths, normalize an AF_INET result into IPv4-mapped sockaddr_in6, preserving IPv4/port and Darwin length. Restore every reusable receive address capacity before the next receive. Existing IPv6 scope/flow stays unchanged. |
| `hev-udp-peer-filter.patch` | Use the TCP peer for unknown-port discovery and the established UDP peer afterward; normalize and compare source addresses/scope and established ports, compact accepted descriptors, and continue receiving after fully discarded batches with the existing cancellable coroutine yield. |

These repair separate boundaries, not alternative versions of one fix. The
ASSOCIATE request's unknown remote/client port zero is different from local
`UDP Listen Port = 0`. Selecting an ephemeral local port does not remove the need
for the initial-connect guard. The original IPv4 address problem could encode a
reply as `[::]:53` instead of its actual source; normalization is not NAT64 or DNS
translation. The earlier user-reported Moonlight success is historical evidence
for that configuration, not a new test of all physical deployments.

Each batch obtains expected peer information once; source-address arrays use the
existing bounded batch size. Accepted descriptors are compacted without copying
payloads. The all-rejected path must yield and keep draining, not fabricate EAGAIN
while a valid datagram remains queued. Genuine I/O errors, empty-queue results and
cancellation retain their normal meaning. Existing sockets, buffer sizes, vector
I/O, workers and coroutine lifetime are retained. Peer comparisons, address storage
and getpeername add real CPU/stack/syscall work; no heap history, additional timer,
thread, listener, dispatcher, per-packet logging or measured zero-cost claim exists.

## Preserved operating policy and limits

**Use UDP Listen Port = 0 for multiple unknown-client associations.** Each TCP
UDP ASSOCIATE control session receives its own negotiated local relay endpoint;
this is not a new socket or port per packet. Clients keep using the configured TCP
SOCKS endpoint, negotiate, then send to returned BND.ADDR/BND.PORT. The network must
permit the negotiated UDP endpoint. Neither code defaults nor saved values are
automatically changed: the existing UI UDP-port default remains `1080`.

Fixed ports remain selectable. Distinct accurately advertised client endpoints
have required passing profiles. One unknown-client association can work, including
the historical user example. Multiple unknown-client associations sharing one fixed
port have an accepted ownership/independent-close limitation: timeout, refusal or
another association's closure can affect actual delivery. This is not merely lost
statistics attribution. No shared-port dispatcher, association identifier, automatic
fallback or client modification is added. A successful observation on one host/run
does not establish the limitation has disappeared.

Source filtering is not cryptographic authentication. Same-IP first-port races,
fragmentation/FRAG/RSV policy, arbitrary datagram sizes and truncation, empty payload,
address-family binding and arbitrary VPN/hotspot routing remain the documented
scope limits. This is not full RFC or security-conformance certification. RFC 1928
specifies source restrictions and optional fragmentation separately; the existing
bounded repair is not expanded into a different protocol implementation.
Original failed aggregate results must not be assigned to a particular scenario
without its individual log. In particular, an unpatched 8/9 total alone never
proves the concurrent-close case failed or exclusively attributes the cause.

## Findings in this re-audit

The prior main network fixture already reserved a dual-stack wildcard, but the
separate `udp_peer_regression.py` still reserved only `::1` while launching a `::`
listener. The exact old reservation can accept a port occupied on IPv4. The peer
fixture now sets IPV6_V6ONLY=0 and reserves `::`, matching the real server. Existing
first-sender/queued-continuation cases, payloads, deadlines and cancellation tests
are unchanged. Actual socket controls execute the extracted reservation statement:
old accepts the occupied port; current rejects EADDRINUSE and matches wildcard
scope when free. This proves the fixture mismatch, not a prior runner's unknown
errno or elimination of every reservation-release-to-bind race.

The audit previously read working files while publishing `git archive HEAD`.
It now checks both working-tree-versus-HEAD and index-versus-HEAD before recording
sources or reaching native tools, and again before final success. This includes the
case of a staged edit whose working file has been restored to HEAD. Eight old/current
boundary cases use real isolated Git repositories and stop intentionally at the
next expensive source-check boundary. They do not simulate a successful native run.
The existing seven regression methods remain, with two peer-reservation methods
and the input-boundary method added. Earlier success-marker controls are retained.

These are test/audit corrections only. No application code or native patch has
changed. A clean Git check binds tracked input at its check points, not an adversarial
atomic filesystem snapshot; unrelated untracked files and toolchain dependencies
are not certified by it. Do not run overlapping audits in one workspace.

## Validation commands and evidence rules

Use a full Git checkout for historical blobs, main ancestry and source checks:

```sh
python3 Tests/udp_compat_audit.py
```

The existing branch workflow runs Linux and Xcode 27, without IPA packaging. It
retains all 58 mandatory native profile executions per host, four exact old peer
controls, eight current peer/queue cases, source-address/capacity/canary checks,
ASan/UBSan and optimized strict-aliasing builds, formatter 18, pinned source and
reverse-patch checks. Darwin also performs actual C and app Swift SDK checks.
Fixed-port/unknown-peer failures are separately recorded observations, not hidden
inside mandatory passes. Test counts contain repeated configurations, not an equal
number of independent physical-device trials. The 65,536 port-value loop does not
exercise every network address or every system library path.

New attempts invalidate the old overall SUCCESS marker while preserving prior
diagnostic logs. Inspect process/job exit, tested SHA/tree, individual logs and
summary, original ZIP digest/CRC and source bytes/modes together. A passing local
fixture, old green badge or failed attempt's partial output is insufficient.
The source archive identifies the exact committed input; a later documentation-only
commit must be separately compared before applying that evidence to its runtime.

Statistics must inherit the completed UDP owner as an actual Git ancestor, with
its mapped source/tests/documents and prerequisite workflow pin matching that owner.
Do not copy selected patches while leaving the recorded dependency stale. This
review does not move main, unrelated features or release, add branches or update an
IPA. README and its identical feature copy are updated only with observed outcomes.

## Unperformed physical boundaries

SideStore signing/install and permissions, LiveContainer loader/container/host
behavior, actual iPhone IPv4/IPv6/hotspot/VPN paths, Moonlight, lock-screen survival,
phone/Bluetooth events and battery/throughput measurements remain unperformed for
this revision. Historical Simulator/native/IPA results retain their own revision
limits; no new physical compatibility is inferred. Accepted source/operating limits
remain explicit even when every required host test passes.

Primary protocol/address contracts, not execution evidence:
- https://www.rfc-editor.org/rfc/rfc1928
- https://pubs.opengroup.org/onlinepubs/9699919799/functions/recvmsg.html
