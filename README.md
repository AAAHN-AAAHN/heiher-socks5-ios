# UDP compatibility — adaptive contiguous datagram buffers

## Scope, environment and prior evidence

This is the standalone `feature/udp-compat` owner. Its complete preceding README,
including all historical results and failures, is retained at immutable commit
`6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5`. The detailed earlier reviews remain in
`docs/reviews/udp-header-validation-20260929.md` and
`docs/reviews/udp-dynamic-resume-20260929.md`; the pre-buffer specification remains
`docs/history/udp-before-dynamic-buffer-20260929.md`. They describe their own
revisions, not new executions. The current README and feature specification match.
`docs/top-level-principles.md` applies unchanged.

The primary targets are a physical iOS27 device installed independently by SideStore
and a LiveContainer guest. These signing, container, permission and process/session
environments are distinct. Configured minimum OS remains iOS17.2. Actual builds in
this review are native Linux/macOS and iPhoneOS27 syntax/type checks, not runtime
certification for every OS at or above that minimum. No new Simulator, physical
installation, iPhone archive, IPA or release integration is part of this review.

Main75335d201cb1e541bb153e9899badbc11ccf1973 is the real baseline ancestor.
Server b3585289622561caf4b8789b436cc8820ecd6be0, core162dd996299fc2d2bff2dd63728f8a2cd71ed31a,
task328f35d903221b51811b3d02b277d665dfbdc75f and yaml162227cd7d2b6108bc8bc133273e11413222ddf4
remain pinned. The committed XCFramework is the unpatched baseline input, not a new
compiled product containing these changes. A product build must rebuild its declared
patches. No UI, app setting, entitlement, host, NetworkExtension or background mode
is changed here. The other feature owners and release retain their independent refs.

## Four patches and preserved runtime contract

Apply the existing patches in this order, using their declared repository roots:

1. `hev-udp-port-zero.patch`: server root; avoid connecting an unknown UDP port zero.
2. `hev-udp-sockaddr.patch`: core; normalize IPv4 socket addresses for IPv6 storage.
3. `hev-udp-peer-filter.patch`: core; enforce the control peer and learned UDP port.
4. `hev-udp-dynamic-buffer.patch`: core; complete datagrams, adaptive buffers and
   the existing RSV/FRAG guard. It changes only `src/core/src/hev-socks5-udp.c`.

The public `HevSocks5UDPMsg` addr/buf/len representation and interfaces are unchanged.
Payload remains contiguous; existing header/address/payload send vectors remain.
One datagram is never silently cut into two independent UDP messages. An allocation
limit is not a protocol length limit, and neither implies delivery through every path.

### Capacity, demand history and cleanup

```c
#define UDP_BUF_SIZE 1500
#define UDP_BUFFER_GROW_STEP 500
#define UDP_BUFFER_HOLD_SECONDS (5 * 60)
#define UDP_BUFFER_CLEANUP_SECONDS 60
```

Each slot starts in the original 1,500-byte slab. Reserve max(1500,ceil(required/500)*500)
in one jump: 48,001 ->48,500;30,001 ->30,500;65,537 ->66,000. There is no separate
65,536-byte allocation cap. Rounding, metadata and pointer arithmetic reject numeric
overflow, and allocation failure remains possible. Required length includes the
address/header bytes actually occupying that slot, not just forwarded payload.
The UDP wire format and existing 16-bit UDP-over-TCP payload field remain bounded;
IPv6 jumbograms are not supported by this change.

An extended slot owns one allocation: a 64-bit bucket-expiry array followed by its
contiguous payload capacity. Each 500-byte bucket above 1,500 retains only its last
actual demand time plus 300 seconds. Smaller input never renews a higher bucket;
packet count does not accumulate history. Resizing copies history, not stale payload.
Capacity is reused without repeated per-packet allocation, full-capacity initialization
or a separate joining copy; allocation remains necessary at growth/shrink. Small demand skips history timestamp/allocator work; this does not mean
the entire relay can never read a clock while large buffers remain allocated.

The original base slab stays allocated. Default batch count10 means20 base slots,
30,000 base bytes, plus32-byte per-slot descriptors on ARM64. A48,500-byte replacement
has752 history bytes;66,000 has1,032. These are requested ownership sizes, not RSS or
allocator-size-class guarantees. Holding large messages across many associations
still needs real memory; this policy cannot make that required memory disappear.

One cleanup deadline per association checks the highest bucket whose expiry is
strictly later than now. It is not reset by every packet. With demand48,001 at A,
30,001 at A+120s and a sweep phase A+17s, capacities become30,500 atA+317s and1,500
atA+437s, absent later large demand. Return to1,500 frees replacement and history.
A failed shrink keeps the old usable allocation and retries only at the next sweep;
new allocation and old allocation can coexist momentarily during a successful shrink.

The existing owner Hev task/timer can wake an idle relay at its60s cleanup deadline.
There is no new thread, task, Swift timer, registry, global lock or logger. Base-only
owners need no maintenance wakeups. Cleanup wakeups do not reset the communication
timeout; the app's original60s UDP timeout is unchanged and can close an association
before a300s hold expires. Closing frees owned buffers without waiting for retention.

Shrink occurs only after I/O references are released. Pending send or incomplete
TCP-frame receive, scheduler delay, sleep and process suspension can postpone it.
Apple uses its continuous CLOCK_MONOTONIC_RAW clock; Linux uses CLOCK_BOOTTIME where
available. User wall-clock edits do not alter this policy. Free releases ownership,
not a promise of immediate or byte-exact physical RAM reduction.

### Receive, peer validation and forwarding

Apple sizes the next datagram with SO_NREAD, not aggregate FIONREAD. A zero result
uses a one-byte non-consuming probe and requery to distinguish an empty queue from
an empty datagram. Linux uses MSG_PEEK|MSG_TRUNC without copying payload to user space.
The owner is the sole reader between sizing and consuming in the supported path.
Each mixed-queue message is sized separately; actual MSG_TRUNC/capacity are checked
again. The existing recvmmsg wrapper receives one message at a time so flags reach
the caller. This costs a length-query syscall and Linux bulk-receive amortization;
existing send batching and cooperative scheduling remain.

Zero-length UDP payload is valid; an empty queue is EAGAIN, not an empty message or
TCP EOF. Rejected batches yield and continue rather than falsely claim exhaustion.
Peer IP/port/scope filtering is preserved. First-peer binding follows implemented
size, truncation, RSV/FRAG and address-length checks. Both reserved bytes and FRAG
must be zero; unsupported SOCKS fragments are dropped, not reassembled. These checks
do not certify every malformed address, DNS answer or untrusted-network history.

The non-Apple/non-Linux fallback uses geometric full non-consuming probes, with
500-byte-rounded reservation. It may temporarily reserve excess capacity and is not
certified on a third OS by Apple/Linux results. The actual target paths reserve from
the next message's queried length, not repeated500-byte full-payload peeks.

UDP-over-TCP requires the complete declared frame and validates address/header
consistency and subtraction bounds before use. Incomplete bytes, invalid frames and
cancellation cannot masquerade as positive message counts. A completed preceding
message is preserved when a later frame fails. Partial outgoing frames are terminal,
not followed by another frame. Public supplied-buffer callers keep their capacity
and signatures; only owner-managed relay buffers acquire dynamic growth/reclamation.
Growth failure terminates the association after a completed prefix rather than
consuming a misleading partial datagram or retrying the same queue head indefinitely.

On Apple EMSGSIZE only, the existing sender examines that socket's SO_SNDBUF and
raises its limit only when insufficient for the next unsent message. At most one retry
per message is allowed; completed prefixes are not duplicated. Normal sends add no
getsockopt/setsockopt. This is not a host/sysctl edit. Its socket queue limit lasts
until close, separately from300s/60s user-space retention, and is not eager equal-sized
resident allocation. Path, family and framing limits remain errors when unresolved.

### Supported boundary and reproduction

Fixed-port multiple unknown-peer associations have a retained ownership/independent-
close limitation. It remains an observation-only failure, not a current passing
configuration. The valid same-IP first-sender race is also not resolved here. The
ordinary port-zero/default and declared fixed-known profiles are separately required.
No new throughput, physical background-survival or unlimited delivery claim is made.

Run the unchanged complete-history entrypoint:

```sh
python3 Tests/udp_compat_audit.py
```

It needs a clean full-history checkout, pinned native sources, clang-format18 and the
appropriate host tools. An archive-only local replay cannot provide missing Git
ancestry or Apple execution. No older test/assertion/timeout/warning gate is removed.
Primary contracts, not execution evidence, remain Apple's recvmsg/getsockopt and XNU
SO_NREAD/socket behavior, POSIX recvmsg, and RFC1928 SOCKS framing. Historic references
and detailed original failure records remain in the immutable preceding README.


## Final submission recheck — 2026-09-30

This review starts at `6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5` and the
four-patch native source described above. No new production defect was reproduced.
All four patches, public interfaces, native pins, app/Swift/project/plist/defaults,
framework, workflow and 1500/500/300s/60s policy remain byte/mode-identical.
Only `Tests/udp_stream_boundaries.c` and two existing driver lists changed before
validation. The new fixture is not part of the app and adds no runtime allocation,
copy, syscall, timer, thread, polling or packet-recording cost.

The fresh tested commit is `411bd82df80e8f0d3d66242431c36d9be840b1e0`, tree
`bb82c72d0487e05da448d9cc2536bf95c38df2e8`, 70 tracked files. Run
`36665546022`, attempt 1, passed both Linux and Xcode27 jobs without a rerun; terminal metadata was updated
at 2026-09-30T03:52:45Z. These results belong to this exact source;
all referenced earlier run records remain historical, not replacement evidence.

### Additional framing and completed-I/O boundaries

The new fixture includes the actual patched C implementation and substitutes only
three stream-I/O wrapper results. It does not rewrite parsing, allocation, clock,
cleanup or the public API. Each sanitizer/optimized execution checks 145,459 cases:

- Valid IPv4, IPv6 and maximum-length NAME frames, payloads from zero through 65,535,
  five first-header splits, caller-supplied and managed buffers, with/without an
  already completed prefix. Exact address/payload bytes and chosen capacity match.
- Every missing-byte position of a 2,048-byte payload frame for those address forms,
  with EOF, EAGAIN or cancellation-style results. Incomplete bytes are not returned
  as a positive message count; a preceding complete message stays available.
- All 65,536 type/header-byte pairs at a fixed NAME-length boundary. Inconsistent
  headers cannot request a body or publish an address; consistent but incomplete
  frames still fail. This is not all possible DOMAIN contents or DNS behavior.
- Every completed-send result from -2 through the full two-frame byte count. Partial
  frames are terminal, never successful messages followed by another frame. A
  65,536-byte payload is rejected before sending because the wire field is 16-bit;
  this does not impose a 65,536-byte allocation cap.

The exact suite total is 660 complete-receive, 77,172 truncated-receive, 65,536
header and 2,091 send cases. These are deterministic codec-boundary cases, not
145,459 independent network or physical-device trials. Existing live socket tests
remain separate. Three disposable local mutations that accept an incomplete body,
accept a short send, or return partial bytes as message count fail the new assertions;
none is committed. Original assertions, negative controls, deadlines, warning gates
and formatter18 requirements were retained.

### New execution results and provenance

| Layer | Actual new result |
| --- | --- |
| Stream boundaries | 145,459 cases pass in ASan/UBSan and O3/strict-aliasing modes on both native hosts. Required formatter18 output matches the new fixture exactly. |
| Existing buffers | 192,000 demand updates and 10,738 sweeps match the full-history oracle. Rounding/overflow, growth and shrink failures, zero-length/queued/truncated input and independent timeout/Stop tests pass. |
| Address/peer/header | 65,536 port values, normalized families/canaries and 3,060 RSV/FRAG combinations pass. Actual required profiles total 58, plus eight peer cases, 34 header profiles and 426 large/mixed network records per host. Grouped records are not independent device trials. |
| Prior failure controls | Old address/port/peer defects and the three-patch 2,048-to-1,490 truncation remain observable in their specific old controls. Four old header controls reproduce invalid forwarding/first-peer behavior. Their expected failures are not current implementation successes. |
| Real retention | Linux demands 120.025654s apart, shrink to 30,500 at 300.184861s and 1,500 at 420.296662s. macOS demands 120.002862s apart, corresponding shrink times 300.019727s and 420.031822s. No input follows the second demand. |
| Real idle maintenance | Linux cleanup/communication exit 60.055956/70.010857s; macOS 60.001892/70.008528s. Maintenance and idle expiry remain separate. |
| Source/tooling | Common 46 input/marker cases, ten driver tests, full-history ancestry/pins, clean worktree/index, formatter18 and exact native reversal pass. |
| Actual Apple SDK | Patched C/session syntax and the unchanged two Swift files pass iPhoneOS27/ARM64 minimum17.2 checks with empty required compiler diagnostics. Xcode27.0 27A266a, Swift6.4, macOS27.0 26A428 are recorded. No Simulator or IPA is generated by this workflow. |

The 300-second hold observation uses real UDP, allocator, clock and Hev timers in a
native helper fixture, with a test-only 600-second communication timeout. It sends
48,001 bytes and, about 120 seconds later, 30,001 bytes; no data follow. This is not
a full server-splice retention measurement or a change to the app's 60-second UDP
timeout. The separate idle fixture seeds expired history and observes 60-second
maintenance independently from a 70-second communication deadline. Neither implies
a hard scheduling deadline under stalled I/O, sleep or iOS suspension.

| Original new artifact | SHA-256 |
| --- | --- |
| Linux 11076331860 | 27018bac6f52c23bc5d3f3a09846102cbf304262124aec84d23a5988dd08c056 |
| macOS 11076044234 | aaf2455d59663cbd5745247fd9776f5e492d1b5b91e2da9587d99549f4d572aa |

Both new original ZIP digests/CRCs and source archives were inspected. Their 70 file
bytes/Git modes reconstruct the tested tree and preserve the existing 69 source
paths except the driver. Native archives match the preceding verified source on all
243 regular files and 30 symbolic-link targets. Native UDP remains blob
`fb6cfb61ca6e1b466c6e20ff3018cda814ecc4f4`, SHA-256
`84ae81b486940a4ae15370f3708908cd6d2163abdf1549e7079b96f4876448b0`.
The original baseline tree and both prior native archives were independently checked.

Supplemental local archive replay completed 30 build/run commands: five actual-source
fixtures in ASan/UBSan and O3/strict-aliasing modes, four existing live network drivers,
and three mutation build/failing-run pairs. It is not full-history CI or Apple/device
execution. Local clangd17 formatting was provisional; the new CI's unchanged
clang-format18 gate is authoritative. Sanitizer scope includes the actual C unit in
the fixture, not every prebuilt library path in the whole application.

An exploratory Clang17 analyzer still reports the existing `getpeername` output /
address-family initialization path warning. It was not reproduced as a runtime
memory error. Its full diagnostic is retained; no warning suppression or speculative
runtime edit was made to turn that exploratory result into a clean report. Mandatory
Apple syntax/typechecking is a separate result, not proof all tools emit no notices.

The existing extra receive-length syscall, Linux receive-batching tradeoff, base-plus-
replacement memory and shrink-allocation costs remain. The unchanged observation-only
benchmark compares the old three-patch binary with the full dynamic implementation,
not this test-only revision with its identical production parent. Median server CPU
microseconds per relayed datagram at 64/1,200 bytes are Linux 7.356/7.670 old versus
7.567/8.133 dynamic (+2.87%/+6.03%), macOS 14.293/12.497 versus 10.829/11.270
(-24.24%/-9.82%). Three interleaved 12,000-roundtrip/window16 trials per condition
remain noisy host observations, not universal speedups or device footprints. This
review adds no product overhead and does not claim measured global minimum CPU/RAM,
zero resident footprint, or a device-energy improvement. Avoiding unnecessary
production changes is deliberate, not omission of an identified fix.

Only README and its identical feature specification change in the final publication;
the other 68 of 70 paths retain the tested bytes and modes. Its parent/commit/tree
identify publication, not another runtime execution. The other seven branches and
release are unchanged. The preceding statistics-still-old wording is corrected:
statistics has independently incorporated the prior UDP owner, while this new test/
document review is not automatically merged into any downstream branch.

No new reproducible production regression or required current-test failure remains
within this executed scope. The accepted fixed-port unknown-peer multi-association
ownership limit and valid same-IP first-sender race remain explicit restrictions,
not repairs performed by this review. No new Simulator, IPA, release integration,
physical SideStore standalone, LiveContainer guest, real background/suspension or
device CPU/RAM/energy/maximum-throughput trial was performed. Those layers require
their own evidence; finite tests do not certify every possible deployment/history.
