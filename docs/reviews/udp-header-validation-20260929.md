# UDP header validation closure — 2026-09-29

## Scope and source

Resume `feature/udp-compat@164cdfb89fd1c4c3889ec00bbee97dd6ca4c7eb4`.
The previous review reproduced both forwarding of nonzero RSV/FRAG and first-peer
capture by an invalid same-IP UDP sender. The original three-patch source reproduces
this too; it was not introduced by the adaptive-buffer implementation. The accepted
fixed-port/multiple-unknown-association limit is a separate issue and is not repaired
here. A valid same-IP first-sender race is not eliminated by rejecting invalid headers.

RFC 1928 section 7 defines two reserved zero bytes and a fragment byte. This server
does not reassemble SOCKS fragments; nonzero FRAG is rejected. This is not IP-level
fragmentation. There is no destination protocol change or fragment reassembly feature.

## Minimal production change

Update the existing fourth `Patches/hev-udp-dynamic-buffer.patch`, not its three
prerequisites. Exactly two C lines test `udp->rsv[0] || udp->rsv[1] || udp->rsv[2]`
and continue before peer connect/association or address processing. The existing
minimum length and MSG_TRUNC checks precede the new reads, so all three bytes exist.
Discarded-only batches retain the prior cancellable draining behavior. UDP-over-TCP
uses the overlapping fields for its different frame lengths and is deliberately
not subjected to the zero-prefix rule.

This adds three bounded byte tests and a branch, with no heap allocation, clock,
lock, thread, timer, packet history or logging. No throughput or energy improvement
is inferred from that operation count. All 1500-byte base, 500-byte rounding,
300-second demand retention, 60-second safe cleanup, contiguous payload ownership,
Apple sendspace handling and source pins are unchanged. Two lines of C do not make
every possible network or process history correct by construction.

README and the matching feature specification now describe the actual checks rather
than claiming all malformed inputs are covered. Old reports remain historical
results, not the validation authority for this new source. The app/Swift, public C
headers, original three patches, framework baseline, shared build/check scripts,
workflow and other seven branch refs must remain unchanged.

## Required regression evidence

The existing source-inclusion fixture retains all its previous assertions and adds
3060 one-invalid-byte cases (255 values x 3 bytes x 2 receive families x 2 association
states). Each must drain the rejected record before returning the valid record and
must not connect to a first peer prematurely. Combined invalid bytes, twelve rejected
records, EAGAIN and cancellation are additional cases. These replace only OS I/O
outcomes, not the production parsing or filtering body; they are not physical trials.

The new loopback driver uses the real server and sockets. Its 34 grouped profiles
cover six invalid prefix patterns, IPv4/IPv6, workers1/4, empty/small/enlarged payloads,
known and learned peers, DOMAIN addressing, all-rejected queues longer than the
batch and mixed invalid/valid queues. It checks no invalid destination payload,
continued exact valid roundtrips, source address, message count and no extra message.
Four separate old-source controls require the former forwarding and peer-capture
failure, not merely a timeout. Bounded quiet waits are observations, not unbounded
proofs of absence. Deterministic byte-wise fixtures supply complementary coverage.

All original 426 dynamic-buffer network records, mandatory UDP/peer profiles,
192000-demand policy oracle, ASan/UBSan and optimized tests, real 60s/70s timer and
actual 300s/420s retention checks remain. No test threshold, timeout, compiler flag,
formatter rule or failure status is weakened. New driver deadlines apply only to
new runs. Existing observation-only limits are not promoted to required passes.

## Supplemental local execution

The current source was rebuilt locally from authenticated prior CI native files.
Local source fixtures and real header regression pass; the unchanged dynamic source
without the guard reproduces the original fault. This archive-only workspace cannot
supply full Git-history controls, Apple SDK, macOS execution or a physical device.
The first local patch-generation attempt failed a reverse-apply context check before
any publication; regeneration from the exact old input fixed the preparation step.
Local formatting uses clangd17; the existing CI clang-format18 gate remains mandatory.
The complete-history CI and original artifacts below now supply the exact-source
Linux/Apple verification that the archive-only local workspace cannot provide.

No new IPA, release merge, Simulator, physical iOS27 SideStore standalone or
LiveContainer guest trial is claimed. Physical signing, permissions, background,
energy and maximum-throughput conditions remain separate unperformed evidence levels.

Primary protocol source: https://www.rfc-editor.org/rfc/rfc1928.html

## Final exact-source execution

Run `36544027330`, attempt 1, completed successfully on both Linux and Xcode27;
its terminal metadata was updated at 2026-09-29T08:49:56Z. No retry or relaxed gate
was required. The tested commit is `d7c2d56c351298d771cc04b0bd601d8229f42e6b`, tree
`5be8bf675f91cf157d916df02e39bef5bef3156c`. Prior run36535518245 is separate evidence
for the pre-header-fix source and is not relabeled as this execution.

| Layer | Results inspected on both hosts |
| --- | --- |
| Byte-wise actual source | 3060 nonzero-byte/family/association combinations in ASan/UBSan and optimized strict-aliasing modes; original mapping/peer/reply tests and rejected-queue/cancellation cases retained. These are controlled OS-boundary fixtures, not 3060 physical trials. |
| Real header I/O | 34 grouped profiles pass in each host: invalid forwarding blocked, valid client can acquire its peer after invalid first input, known/learned peers, IPv4/IPv6/numeric DOMAIN, empty/2048-byte valid payloads, rejected-only and mixed queues, workers1/4. |
| Old controls | Four prior three-patch profiles reproduce invalid forwarding and first-peer capture. An additional local pre-guard dynamic binary reproduces the same defect. Absence waits remain bounded; exact source fixtures complement those observations. |
| Existing transport | 58 mandatory profile executions and eight peer/queue cases remain successful; all 426 dynamic-network records pass, including large payloads and UDP-over-TCP. Grouped repeats are not independent device trials. |
| Policy and ownership | 192000 demand updates and 10738 sweeps match the full-history oracle per policy run. Overflow, allocation/shrink failure, actual socket truncation, empty datagrams, successful prefix and timeout/Stop gates pass in sanitizer/optimized modes. |
| Source/build guards | 46 common source/marker controls, ten driver tests, original pins and main ancestry, clean worktree/index, formatter18, exact native reversal and unchanged public/app inputs pass. |
| Apple SDK | Patched C/session and the two unchanged Swift files pass iPhoneOS27 ARM64/iOS17.2 checks. Both compiler diagnostic logs are empty. Native host: Xcode27.0 27A266a, Apple Swift6.4 swiftlang-6.4.0.34.1, macOS27.0 26A428. |
| Physical/product layers | Not run: Simulator, iPhone archive/IPA, release integration, physical iOS27 SideStore standalone or LiveContainer guest execution, device background/power/maximum throughput. |

The guarded source retains the real timing tests and unchanged policy constants:

| Observation (seconds) | Linux | macOS |
| --- | ---: | ---: |
| Independent idle cleanup | 60.047411 | 60.002248 |
| Separate 70s communication exit | 70.010439 | 70.002315 |
| Gap between actual 48001/30001-byte inputs | 120.060154 | 120.012464 |
| 48500 -> 30500 after first input | 300.217154 | 300.039094 |
| 30500 -> 1500 after first input | 420.301105 | 420.053164 |

No input follows the second demand in the long test. The live fixture retains real
clock, production receive/allocation/Hev timer and 300s/60s constants, using its own
600s communication timeout to observe both holds. The application timeout is not
changed. This is not a hard scheduling guarantee under blocked I/O or iOS suspension.

## Resource and diagnostic review

This header repair adds only three byte checks and a conditional skip: no new
per-packet allocation, copied payload, clock query, socket call, lock, timer or
retained state. The pre-existing dynamic-buffer sizing syscall, history storage,
base-slab duplication and Linux receive-batch tradeoff remain documented costs.

The unchanged observation-only CI benchmark interleaves three old/new trials per
size, 12000 roundtrips/window16/workers1. Medians below are server-child CPU
microseconds per relayed datagram, including startup/Stop, excluding client/echo.
The old side here is the genuine three-patch source; both sides transfer these
small payloads completely.

| Host / payload bytes | Three patches | Current | Difference |
| --- | ---: | ---: | ---: |
| Linux / 64 | 9.136625 | 9.121500 | -0.17% |
| Linux / 1200 | 9.033958 | 9.765833 | +8.10% |
| macOS / 64 | 11.237417 | 10.417292 | -7.30% |
| macOS / 1200 | 11.867542 | 10.085583 | -15.02% |

These noisy hosted loopback observations do not establish an iPhone speedup or a
worst-case overhead. Live-association RSS median deltas are +8192/+8192 bytes on
Linux and 0/+16384 bytes on macOS for 64/1200-byte payloads. These are post-exec
snapshots, not peaks or physical footprints. The inherited wait4 child high-water
counter may include pre-exec parent pages and is not used as application footprint.

A supplemental local benchmark compares the pre-guard dynamic source to the current
two-line guard, not to the three-patch source. The unchanged driver's historical
old-three-patch label is explicitly remapped in the saved input metadata. CPU
medians are 3.875417 -> 3.984958us for64bytes and4.467875 -> 3.616708us for1200bytes.
The variation is not evidence of a bounded regression or universal improvement.

Three disposable source mutations each remove one byte check; every mutant fails
the unrelaxed rejection/yield assertion. No mutant is published. The separate local
Clang17 static analyzer returns the same one getpeername-initialization-path warning
before and after. No corresponding new runtime memory failure was reproduced. The
warning and its path are retained, not suppressed or labeled warning-free; empty
SDK compiler diagnostics have a different scope. The previous exploratory -Wextra
signed-loop warnings also remain historical non-required diagnostics, not fixed by
this small header change.

## Artifact identity and closure

| Original artifact | SHA-256 |
| --- | --- |
| Linux11021642786 | 267e0d5053d190670f0dd7d420fb19e67b428b0c901f0fa56396c3fbabf92c6b |
| macOS11022203481 | b0fc6bb3c13ed67ccf715ce08b4a20ef537959250014c7ad63103668ac0ea102 |

Both downloaded original ZIPs match GitHub digest metadata and pass CRC checks.
Each source archive identifies d7c2d56c and has identical 69 file bytes/Git modes;
independent tree reconstruction equals5be8bf67. The two native archives match243
regular files and30 symlinks, including executable modes. Compared with the prior
native source, only src/core/src/hev-socks5-udp.c differs, by exactly the two-line
guard. Current C blob is `fb6cfb61ca6e1b466c6e20ff3018cda814ecc4f4`, SHA-256
`84ae81b486940a4ae15370f3708908cd6d2163abdf1549e7079b96f4876448b0`.
The updated fourth patch SHA-256 is
`93b447da99de5c766f4d142203214748d98f4ffc4ddf3a26f7bc1f7894a07754`.
Reverse/reapply restores the exact three-patch source and current C respectively.

This final closure updates three documentation paths only: README, its identical
feature specification and this review. The other66 tested paths are unchanged.
Original three patches, public headers, source pins, baseline framework, app/Swift,
project/plist/assets, shared build/check scripts and workflow remain unchanged.
Only feature/udp-compat advances. Other seven branch refs, statistics and release/
build9 are preserved; downstream incorporation requires its own deliberate work.

The last review's confirmed RSV/FRAG forwarding/peer-learning defects and overly
broad README claim are resolved. No new failing mandatory case remains in this
scope. The separately accepted fixed-port unknown-peer multi-association close
restriction still reproduces in observation-only profiles on both hosts/workers.
Valid same-IP first-sender races, protocol/path bounds, lifetime/scheduling and
physical deployment are not universally certified by this run. Use per-association
UDP port0 for the existing recommended multi-unknown-peer deployment. No dispatcher,
new authentication, host workaround or unrelated repair is invented for completion.
