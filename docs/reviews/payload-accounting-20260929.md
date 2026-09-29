# Destination-side payload accounting revalidation — 2026-09-29

## Scope and unchanged implementation

Resume the last request in Branch · 차단된 업로드 진행: verify completeness within
already-defined payload relay accounting, not whole-app/iOS/wire traffic. Baseline:
feature/traffic-statistics@16449f7412c3a0635cb457e121277a64175724f6.
All production Swift, six native patches, source pins, baseline framework, app
resources, project/plist, defaults and workflows are unchanged. Other seven branch
refs, Background's0.5second timer and release8577bb1f/build9 are not updated.
The existing visible/active1second statistics sampling remains unrelated to audio.

The source trace covers the session dispatch to TCP and both UDP transports, the
existing buffered/Linux splice callback, destination UDP send/receive forwarders,
actual task-system message wrappers, aggregate/IP collector, C API and Swift sample.
Client-side negotiation/framing/resolver I/O is not another missing destination
relay counter. TCP urgent/OOB data, malformed protocols, arbitrary forwarding success
and process termination at arbitrary instructions are not certified by this review.

## Added verification, no runtime repair

Tests/Statistics/payload_boundaries.py reuses the actual native statistics host and
includes the original socket-wrapper translation unit unchanged. Only system call
outcomes are scripted in that fixture. It checks successful message prefixes before
EIO/EPIPE/ECONNRESET/EMSGSIZE/EINTR, EAGAIN retry/cancellation, nonblocking return and
zero-byte datagrams. Linux exercises34 native-batch and32 forced-single-message
cases with ASan/UBSan; the forced variant is not an Apple-runtime test. Darwin
executes its own32 single-message cases. These sanitizer results cover the included
wrapper, not the entire program or every coroutine interaction.

The real loopback portion performs54 cases per native mode using IPv4, IPv6 and a
nine-byte numeric IPv4 address carried as ATYP DOMAIN. It checks actual destination
payload, returned payload, aggregate deltas and the quiescent sum of IP counters.
Sizes span the relevant limit minus/at/plus one and selected values through4096.
An empty destination datagram contributes zero bytes. Oversized UDP-over-TCP has
an explicit250ms no-datagram observation, alongside the source's length rejection;
this bounded wait is not a general network-delivery proof. Numeric DOMAIN fixtures
do not test external DNS providers or every domain length.

Two lines add this driver to every existing native_checks mode. All original native,
partial-I/O, collector, model, source/ancestry, formatter, SDK and Simulator gates,
workflow requirements and timeouts remain. Tests and temporary fixtures are not part
of the app. Test work increases; production objects, wakeups and I/O do not.

## Distinguish accounting coverage from relay loss

The current UDP buffer is1500bytes, not a guarantee of a1500byte payload in every
direction. In UDP-in-UDP, outbound framing occupies10bytes for an IPv4 address,
22for IPv6, or7+N for an N-byte domain. The maximum copied outbound payload is
1490/1478/(1493-N), respectively. Oversized datagrams can be truncated before the
destination send. Out must count only the bytes actually sent, not the discarded tail.
Destination-to-proxy UDP receives have1500bytes available for payload; an oversized
response can be truncated to1500before In is counted. Client response framing is
added afterwards and is not counted a second time.

UDP-in-TCP first removes three framing bytes and rejects declared payload greater
than1500-address_length:1493for IPv4,1481for IPv6,1496-N for DOMAIN. This is a separate
parser condition, not the UDP-in-UDP threshold. These are existing relay limits,
not new statistics fixes. No larger buffer, truncation policy, dispatcher, resolver,
packet history or client-protocol change is added.

Within successful destination-side socket results, no counter omission has been
reproduced in the inspected paths. Already-read In survives failed client delivery;
only a successful Out prefix is included. Batch completion can delay publication;
live aggregate/row snapshots are not transactional, and UInt64 is finite. Thus the
result cannot honestly be phrased as all original application payload is always
relayed or represented regardless of size, failure, loss or process termination.

## Execution checkpoint

Before publication, Linux rebuilt both native modes from the preceding authenticated
CI source archive and passed the existing native suites and four debug/optimized
Swift model executions. The new wrapper/boundary driver passed locally. An initial
new fixture lacked hev-task-io.h before the socket header; adding that test include
fixed its compile error without changing production headers. A separate full-history
sample driver could not run in the archive-only checkout; that failure is not a
native accounting failure and is not labeled a completed full local audit.

Fresh exact-commit Linux/macOS CI, source archives and applicable Apple verification
must be inspected before closing this checkpoint. Earlier run36435371952 is prior
source evidence, not the new run. Physical iOS27 SideStore standalone, LiveContainer
guest execution, device background survival, power and throughput remain unperformed.
No IPA or release merge is part of this payload-only audit.

Reproduce from a clean full-history checkout:

```sh
python3 Tests/Statistics/audit.py
```
