# UDP compatibility — adaptive contiguous datagram buffers

## Completion — 2026-09-29

The agreed dynamic-buffer implementation and scoped verification are complete.
Run `36535518245`, attempt 1, passed both Linux and Xcode27 jobs at tested commit
`1c5b37d5a6901d455ddecf604b55ad60b91a35cb`, tree
`cb394fdad0e088c5b8b8d9ee32553fcd04967b4a`. Its 67-file source and both original
artifact archives were independently verified. This closing commit changes only
README, the identical feature specification and the dated completion review; the
other 64 paths retain the tested bytes and Git modes. It is not a new execution.
The implementation was already posted at04f570c0 when this resume began. The resume
corrected test readiness/Apple fixture defects and added real elapsed retention
coverage; production remains byte-identical to that initial implementation.

Full failure history, additional replay boundaries and resource observations are in
`docs/reviews/udp-dynamic-resume-20260929.md`. No known new implementation failure
remains within the executed scope. This is not a proof over every input/event history
or a substitute for physical SideStore and LiveContainer tests. No IPA is produced.

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

## Retained initial implementation checkpoint — superseded by completion below

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

At the initial implementation checkpoint, fresh exact-source Linux/macOS CI and
artifact verification were still required. They are completed in the record below. No new Simulator, device archive/IPA or release
integration has been performed. Physical iOS27 SideStore and LiveContainer, actual
calls/background suspension, extended network/energy/throughput measurements remain
unperformed. Known fixed-port unknown-peer multi-association ownership limits remain.

Primary API contracts, not execution evidence:
- https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getsockopt.2.html
- https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/sys/socket.h
- https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/netinet/udp_usrreq.c
- https://pubs.opengroup.org/onlinepubs/9699919799/functions/recvmsg.html


## Final verification record

The final source was checked out with complete history on both hosts. All required
jobs passed in run36535518245 on attempt1, updated2026-09-29T07:25:32Z. No original
assertion, warning gate, formatting gate or timeout was removed or relaxed. The
new real-hold test has its own490s deadline; the preceding timer test retains90s.
Earlier failed executions are retained, not retrospectively classified as passing.

| Evidence | Actual result and scope |
| --- | --- |
| Original UDP behavior | Each host passes all58 mandatory profile executions, eight peer/queue cases, address/canary/strict-aliasing tests and retained exact-old controls. |
| Dynamic network behavior | Each host completes426 recorded cases covering full empty/small/large datagrams through65000bytes, both directions, IPv4/IPv6/numeric DOMAIN, known/unknown peers, mixed queues, UDP-over-TCP, malformed/partial frames, workers1/4 and grouped concurrency. These are not426 independent physical-device trials. The exact old three-patch control still forwards only1490 of2048bytes. |
| Policy and failures | Actual helper tests in ASan/UBSan and optimized modes pass192000 demand updates and10738 cleanup sweeps against full-history reference,500B rounding beyond65536, arithmetic overflow, growth/shrink failure, no timestamp/allocation calls for small demand, independent timeout and Stop. All test-owned allocations are released. |
| Actual socket paths | IPv4/IPv6 empty queue and zero datagram, mixed input, lengths/content/capacity, forced MSG_TRUNC and valid-prefix-before-allocation-failure pass. Apple lazy SO_SNDBUF repair retains successful prefixes and has bounded rejected/clamped/repeated-failure retries. |
| Real idle timer | Linux cleanup60.038222s and separate communication exit70.001896s; macOS60.009056s and70.003721s. No I/O or extra production task is needed for the cleanup wake. |
| Real300s retention | The added live fixture receives48001bytes and30001bytes about120s apart. With no subsequent packets, capacity48500 becomes30500 at300.228695s on Linux /300.018513s on macOS, then1500 at420.318498s /420.030160s. Production clock, interval constants, allocation, receive and owner timer are not substituted. This is an isolated native fixture, not a physical installation. |
| Build/source guards | The46 common source/marker controls,10 dedicated driver tests, main ancestry, original pins/framework/patch preservation, formatter18, exact fourth/all-patch reversal and clean input/final worktree/index gates pass. |
| Apple compilation | The patched C/session sources pass ARM64/iOS17.2 checks against iPhoneOS27. The two unchanged production Swift files pass the existing SDK typecheck. Both diagnostic logs are empty. Toolchain: Xcode27.0 27A266a, Apple Swift6.4 swiftlang-6.4.0.34.1, macOS27.0 26A428. |
| Unperformed levels | No new Simulator, iPhone archive/IPA, release integration, SideStore standalone installation, LiveContainer guest execution, physical background survival or device power/throughput benchmark. |

The live-retention fixture adds only test tasks. It uses its own600s communication
wait to observe both holds; application timeout/defaults are not changed. Its timing
assertions allow bounded scheduling slack and do not establish a real-time deadline.
The earlier seeded60s timer test remains separately useful and is not relabeled as
a new300s wait. The old fixture's original readiness failure returned EAGAIN before
input arrival; fixed two-second test-only readiness waiting now preserves the
original content/truncation/failure conditions. Sender fixture names/prototypes were
corrected for Apple compilation without changing the production sender.

### CPU and memory observations, not a device performance guarantee

The unchanged interleaved benchmark checks12000 roundtrips per trial, window16,
workers1 and three trials per variant/payload. The figures below are medians of
server-child CPU microseconds per relayed datagram, including startup/Stop. Client/
echo CPU is excluded. Both variants transfer identical small payloads in full.

| Host / payload | Original three patches | Dynamic buffers | Median ratio change |
| --- | ---: | ---: | ---: |
| Linux /64bytes |12.951|13.079|+0.98%|
| Linux /1200bytes |13.811|15.493|+12.18%|
| macOS /64bytes |11.455|10.679|-6.78%|
| macOS /1200bytes |12.282|10.608|-13.63%|

These short hosted loopback trials vary; they neither prove a universal speedup nor
bound the worst regression. In particular the extra length query and loss of Linux
receive batching are real costs. No performance assertion was weakened to pass;
the benchmark is observation-only. Post-exec live-association median RSS differed
by8KiB/4KiB on Linux and16KiB/16KiB on macOS for64/1200byte cases. These snapshots
are not peaks or iOS app footprints. Raw wait4 high-water values are retained but
can include the forking Python parent's pre-exec memory and are not used as footprint.
Large-message retention/RSS and all physical energy/performance remain distinct.

A supplemental controlled-clock allocation replay performs1000000 repeated large
bucket updates with one initial allocation,49252 unchanged owned bytes, unchanged
cleanup phase and zero remaining ownership after cleanup, in ASan/optimized modes.
It verifies bounded bookkeeping/allocation behavior, not real-clock CPU latency.
The original base memory remains additional to that replacement/history figure.

### Artifact identity and preserved scope

| Original artifact | SHA-256 |
| --- | --- |
| Linux11018901052 |2bb559389f0ab1c0b957374201490382bd5d2928fd1e8cbfc52d4ad1b35510d4|
| macOS11018841278 |dfe718d6df052b2640f52d29a1ac7204fb488c840a96f3a6bd0038044b467f27|

Both original ZIPs pass CRC/digest verification. Their source archives have the same
actual tested commit comment and all67 bytes/modes; independent tree reconstruction
matchescb394fda. Their native archives agree on243 regular files and30 symbolic
links including executable modes. Patched UDP C remains blob
`7c9a16e398873ce4bc4a5f2eb5f68f9261c750a7`, SHA256
`8d1c54239db15a068ae13c394ca5b71f0109add0d2ea6e26ca1884696e901bf7`.
The fourth patch SHA256 is
`72303ae2d482a7fd8eb87c34219a9247956f508281438411fbcb21538342bd56`.

No new production correction was needed after the initial04f570c0 implementation.
The three original patch files, all public headers, app/Swift/project/plist/resources,
source pins, baseline framework, shared build/check scripts and workflow remain
unchanged. Fixed-port unknown-peer concurrent ownership limitations remain: this
run's observation-only independent-close case fails for workers1/4 on both hosts.
That accepted pre-existing restriction is not relabeled as repaired by this work.
The other seven refs, previous statistics owner and release/build9 remain unchanged.
A downstream build must deliberately incorporate the new UDP owner and revalidate
its own patches and counters; standalone UDP success is not integrated success.
