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

## Execution checkpoint

The current source was rebuilt locally from authenticated prior CI native files.
Local source fixtures and real header regression pass; the unchanged dynamic source
without the guard reproduces the original fault. This archive-only workspace cannot
supply full Git-history controls, Apple SDK, macOS execution or a physical device.
The first local patch-generation attempt failed a reverse-apply context check before
any publication; regeneration from the exact old input fixed the preparation step.
Local formatting uses clangd17; the existing CI clang-format18 gate remains mandatory.
Fresh exact-commit CI and the original artifact bytes must be examined before closing.

No new IPA, release merge, Simulator, physical iOS27 SideStore standalone or
LiveContainer guest trial is claimed. Physical signing, permissions, background,
energy and maximum-throughput conditions remain separate unperformed evidence levels.

Primary protocol source: https://www.rfc-editor.org/rfc/rfc1928.html
