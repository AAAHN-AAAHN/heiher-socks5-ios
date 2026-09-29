# UDP compatibility — adaptive contiguous datagram buffers

## Scope and target

This revision starts at `feature/udp-compat@9909aa5f5f41ec87bb3edd976923b2d668e00f08`.
Main `75335d201cb1e541bb153e9899badbc11ccf1973` remains the real baseline ancestor.
The complete preceding specification is preserved byte-for-byte in
`docs/history/udp-before-dynamic-buffer-20260929.md`; all earlier histories remain.
This README and `docs/features/udp-compatibility.md` are identical. The original
four user principles in `docs/top-level-principles.md` remain unchanged.

The primary target is a physical iOS27 device installed independently with SideStore
or run as a LiveContainer guest. These signing, permission and process environments
are different. Native host tests, iPhoneOS SDK compilation and Simulator results do
not replace either physical path. Configured minimum OS remains iOS17.2. No host,
permission, entitlement, NetworkExtension, background mode or Swift UI is changed.

Only this UDP owner advances. Statistics, Background, server-control, persistence,
icon, main and release/build9 are not updated. The statistics branch and release
still pin the previous UDP owner and do not automatically acquire this feature.
Their later incorporation needs actual ancestor/membership/patch and combined tests.

## Patch order and unchanged inputs

The existing three patch files retain every byte: port-zero, sockaddr normalization,
then peer filtering. A fourth `Patches/hev-udp-dynamic-buffer.patch` applies only to
`src/core/src/hev-socks5-udp.c` after them. Source pins, public C headers and the
HevSocks5UDPMsg addr/buf/len representation are unchanged. No second relay engine,
scatter/gather payload representation or new public API is introduced. The existing
header/address/payload send vectors remain; a datagram is never split into several
independent UDP messages.

Server b3585289622561caf4b8789b436cc8820ecd6be0, core162dd996299fc2d2bff2dd63728f8a2cd71ed31a,
task328f35d903221b51811b3d02b277d665dfbdc75f and yaml162227cd7d2b6108bc8bc133273e11413222ddf4
remain pinned. The committed16-file XCFramework is still unpatched baseline input;
a product build must rebuild the declared patches. Shared Build/check.py/build.sh,
workflow, app, project/plist, defaults and resources remain unchanged.

## Exact allocation and retention contract

```
#define UDP_BUF_SIZE 1500
#define UDP_BUFFER_GROW_STEP 500
#define UDP_BUFFER_HOLD_SECONDS (5 * 60)
#define UDP_BUFFER_CLEANUP_SECONDS 60
```

Each receive slot starts in the original1500-byte base slab. A larger actual message
requires capacity max(1500, ceil(required/500)*500), allocated in one jump. Examples:
48001 ->48500,30001 ->30500,65537 ->66000. There is no separate65536 allocation cap.
Size rounding, combined metadata/payload allocation and pointer arithmetic reject
numeric overflow. This is not unlimited RAM or an extension to UDP wire-length or
the existing16-bit UDP-over-TCP data-length field. No IPv6 jumbogram support is added.
Required length includes the SOCKS address/header bytes occupying that receive slot,
not only the payload eventually forwarded. Kernel send/receive queues are separate.

An expanded slot owns one replacement allocation containing its bucket-expiry array
followed by contiguous payload capacity. Each500-byte bucket above1500 stores one
64-bit last-demand-plus300seconds value. Actual demand updates only its own bucket,
not the currently allocated maximum. Small messages do not renew any large bucket.
The array grows with capacity, not packet count; it is about1.6percent of replacement
capacity at large sizes. Allocation occurs only at growth/shrink, not every packet.
Only history is copied during resizing; stale payload is not copied or zero-filled.

The original base slab remains, so an expanded slot has1500 base bytes plus its
replacement and history. Default batch count10 means20 base slots (30000 bytes),
plus the private per-slot descriptors. On ARM64 those descriptors are32bytes each.
An expanded48500-byte slot has752bytes of history; a66000-byte slot has1032bytes.
These are requested byte sizes, not resident-memory or allocator-size-class promises.

There is one next-cleanup deadline per association, not per packet/bucket. A sweep
runs at safe relay boundaries every60seconds while extensions exist, and chooses
the highest bucket whose expiry is strictly later than the sweep time. With demand
48001 at A and30001 at A+120s, an independent sweep phase at A+17s gives48500 ->30500
at A+317s and30500 ->1500 at A+437s, absent later large demand. Expired high history
is removed with the shrink; all history is freed on return to the base slot.

The same Hev task timer wakes an otherwise idle owner at its cleanup deadline.
Maintenance wakeups do not restart or replace the independent communication timeout.
No Swift timer, additional thread, task, registry, global lock or periodic logger is
created. Base-only owners do not request maintenance wakeups. The original60s UDP
communication timeout is preserved: an association may terminate before a300s hold
expires. Termination frees all owned buffers immediately, regardless of retention.

Shrinking is never performed while a send or incomplete TCP-frame receive references
the data. Such operations, OS scheduling, sleep and process suspension can delay a
sweep;60seconds is a scheduling interval, not a hard real-time reclamation guarantee.
Apple uses its continuous CLOCK_MONOTONIC_RAW clock; Linux uses CLOCK_BOOTTIME where
available. User wall-clock changes do not change retention. free() releases ownership
but does not promise immediate or byte-exact resident-memory reduction. Failed shrink
retains the usable old allocation and retries on the next sweep, not every packet.

## Full receive, parsing and forwarding

On Apple, SO_NREAD queries the next datagram's length (not FIONREAD's aggregate
queue count). A zero-length result is distinguished from an empty queue with a
one-byte non-consuming probe and requery. Linux uses a zero-copy-to-user
MSG_PEEK|MSG_TRUNC length query. Normal payload is not repeatedly copied by full
peek. The owner is the sole reader of its socket between sizing and consuming.
Actual receive is still checked for MSG_TRUNC, capacity and address validity.
The existing recvmmsg wrapper is used with one message so its output flags reach
the caller; the unrelated generic recvmsg wrapper is not changed.

Each message in a mixed queue is sized separately, rather than assuming the first
message's length describes later batch members. This adds a length-query syscall
and gives up Linux bulk-receive syscall amortization. Existing send batching and
coroutine scheduling remain. Empty UDP payload is valid and forwarded as zero bytes;
empty queue is EAGAIN, not an empty datagram or EOF. All-rejected input continues
through the original cooperative yield instead of mistaking rejection for queue
exhaustion. Peer IP/port filtering and normalized IPv4/IPv6 behavior are preserved.
The first peer is bound only after basic header/length validation; malformed/truncated
input cannot be forwarded as a valid prefix. No SOCKS fragment reassembly is added.

The non-Apple/non-Linux fallback uses full non-consuming probes with geometric
capacity growth. That fallback is not the optimized target path and may temporarily
retain extra500-byte-rounded capacity until a sweep. It is not certified on another
physical platform by Linux or Apple tests. Target Apple/Linux paths reserve directly
from the actual next-message length.

UDP-over-TCP reads its declared frame length, reserves before consuming the body,
and requires a complete frame. Address/header consistency and subtraction bounds are
validated before use. Incomplete header/body, invalid frame and cancellation cannot
be returned as a positive message count equal to a partial byte count. A partial
outgoing TCP frame is terminal rather than followed by another frame. Public
contiguous-buffer callers retain their supplied capacity and signatures; they do
not secretly acquire owner-managed growth or reclamation.

If growing a slot fails, the association becomes terminal after any completed
prefix; the queued oversized datagram is not consumed as a misleading partial payload
or retried in a busy loop. After actual receive, unexpected MSG_TRUNC is rejected,
not forwarded. No additional payload log, fingerprint or traffic counter is added.
Protocol-invalid or path-untransmittable sizes still fail; allocation capacity does
not override MTU, IP family, SOCKS framing overhead or successful delivery semantics.

## Apple large-send socket boundary

Darwin's UDP send high-water mark can be below a valid large datagram (the inspected
public XNU source defaults udp_sendspace to9216). On an actual EMSGSIZE only, the
sender checks that socket's SO_SNDBUF and raises it only when smaller than the next
unsent message. At most one retry per message is allowed; rejected/clamped settings
or repeated EMSGSIZE cannot spin or duplicate the successful prefix. Normal sends
add no getsockopt/setsockopt. Linux continues its original wrapper-call path.

This is local socket configuration, not sysctl, host modification or a new privilege.
The send high-water mark remains until socket close and is not the user-space500B/
300s/60s allocation policy. It denotes a queue limit, not an eagerly allocated equal
resident region. Existing SO_RCVBUF configuration and all application options remain.
Even after adjustment, unsupported/path/protocol errors remain errors, not success.

## Verification and reproduction

```
python3 Tests/udp_compat_audit.py
```

Run in a clean complete-history checkout. The inherited baseline/source/index,
original patch negative controls, peer/queue, fixed-port mandatory cases, formatter18,
address sanitizer/strict-aliasing, Apple C/Swift SDK and exact reverse checks remain.
The old three-patch binary is retained as a negative control:2048 outbound IPv4 bytes
arrive as1490 there, while the new network test requires the complete original.
The old address fixture receives only NULL adapter arguments for the private changed
signatures; its assertions are not removed. Shared validator/workflow are unchanged.

New actual-source unit tests exercise rounding beyond65536, exact300s/60s history,
192000 demand updates against a full-history oracle, small-demand timestamp/allocator
avoidance, allocation/shrink failure and independent timeout/Stop. Real IPv4/IPv6 I/O
checks queued empty/small/large datagrams, actual MSG_TRUNC and failure after a valid
prefix. Darwin's sender fixture checks lazy growth, preserved prefixes and bounded
failure retry. These substitute syscall/time/allocator boundaries only, not production
function bodies; sanitizer scopes do not certify the entire program.

A real Hev-timer fixture waits without network I/O, with seeded expired history, to
observe the unchanged60s cleanup and a separate70s communication deadline. It does
not wait300seconds for a new real packet; the exact300s policy is separately tested
with a controlled clock. The network driver checks full IPv4/IPv6/numeric-DOMAIN,
known/unknown peers, both directions, empty/mixed queue, UDP-over-TCP frames up to65000,
malformed partial frames, workers1/4 and concurrent associations.426 recorded cases
include grouped concurrent repeats, not426 unique independent device trials.

An observation-only benchmark interleaves three old/new trials at64 and1200payload
bytes,12000 loopback roundtrips/window16 per trial. It checks equal contents/message
counts, server child CPU, wall time, graceful Stop and post-exec resident snapshots.
The raw wait4 high-water mark is also retained but may inherit the forking Python
parent's peak; it must not be represented as the native server's footprint. Results
are noisy local host observations, not maximum throughput, device power, or a claim
that the extra length query is free or always faster.

## Execution checkpoint

Local Linux rebuilt the exact prior native archive after reversing only the statistics
patches. Original default9 UDP and8 peer/queue tests, the old address fixture, new
policy/I/O/send fixtures and426 recorded network cases passed. The real timer observed
cleanup near60s and communication exit near70s. Local formatter uses clangd17; the
mandatory original clang-format18 gate and full Git ancestry checks still require
fresh CI. The archive-only workspace cannot substitute for those history checks.

Initial new fixture compilation lacked _GNU_SOURCE before system headers; the test
was corrected, not production flags weakened. A malformed-frame test initially
required EOF even when the OS correctly reset a connection with unread data; it now
accepts only EOF or ECONNRESET and still requires no destination payload. Original
failure logs are retained. No failure is retroactively counted as a pass.

Fresh exact-source Linux/macOS CI results and artifact identities must be checked
before closing this checkpoint. No new Simulator, device archive/IPA or release
integration has been performed. Physical iOS27 SideStore and LiveContainer, actual
calls/background suspension, extended network/energy/throughput measurements remain
unperformed. Known fixed-port unknown-peer multi-association ownership limits remain.

Primary API contracts, not execution evidence:
- https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getsockopt.2.html
- https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/sys/socket.h
- https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/netinet/udp_usrreq.c
- https://pubs.opengroup.org/onlinepubs/9699919799/functions/recvmsg.html
