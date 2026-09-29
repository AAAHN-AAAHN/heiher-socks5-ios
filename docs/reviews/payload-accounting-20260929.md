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

## Supplemental local execution

Before publication, Linux rebuilt both native modes from the preceding authenticated
CI source archive and passed the existing native suites and four debug/optimized
Swift model executions. The new wrapper/boundary driver passed locally. An initial
new fixture lacked hev-task-io.h before the socket header; adding that test include
fixed its compile error without changing production headers. A separate full-history
sample driver could not run in the archive-only checkout; that failure is not a
native accounting failure and is not labeled a completed full local audit.

The final published boundary driver also passed separately with both local compiled
hosts. Earlier run36435371952 is preserved prior-source evidence, not the new run.
The full-history CI below supplies the Git-dependent sample/ownership checks that
the archive-only local workspace could not execute. Physical iOS27 SideStore
standalone, LiveContainer guest execution, device background survival, power and
throughput remain unperformed. No IPA or release merge is part of this audit.

Reproduce from a clean full-history checkout:

```sh
python3 Tests/Statistics/audit.py
```


## Final exact-source verification

Tested commit: `d3f1c35984e7cc383de59608bae41e3aa389d71e`.
Tested tree: `55e97808ca0ab926b9d445ebca93e07b27c3c287`.
Run `36513303702`, attempt1, completed all four jobs successfully: the exact UDP
owner prerequisites on Linux/macOS and the current statistics audit on Linux/macOS,
including its unchanged actual Simulator test. No retry, assertion deletion,
warning suppression or timeout increase was used to reach this result.

| Layer | Inspected current results |
| --- | --- |
| New wrapper fixture | Linux buffered and splice each pass34 platform-batch plus32 forced-single-message cases. Actual macOS buffered passes32 native single-message cases. ASan/UBSan run on the included real wrapper. |
| New network boundaries | Each of the three native modes passes54 real loopback cases:24 client-outbound,21 destination-inbound and9 UDP-over-TCP. The162 executions repeat the same54-case design, not162 distinct specifications or physical iPhone trials. Actual lengths, payload bytes, counter deltas and quiescent IP sums are checked. |
| Existing network/accounting | The original10 scenarios pass twice per mode; peer rejection/queue continuation, real client-IP TCP/UDP attribution, socket churn, Stop/Start and2000 small echoes per mode retain their original tests. |
| Partial I/O and counters | Existing actual-source TCP/UDP probes retain partial success, EAGAIN, EOF, errors, cancellation and failed-client-delivery checks. Eight writers/800000 updates retain exact sums. Collector/snapshot/cardinality guards, scoped ASan/UBSan and macOS aggregate/client/expanded-registry TSan pass. |
| Models and guards | Existing aggregate/client models, rounding controls and98,516 exact-sample checks per compiler mode pass. Source pins, main/UDP ancestry, tracked worktree/index checks, baseline/driver controls, formatter and exact native reverse checks pass. |
| Apple SDK | Five production Swift files and patched C/headers pass iPhoneOS27 ARM64/iOS17.2 checks with warnings-as-errors. Both compiler diagnostic logs are empty. |
| Simulator | Original uninstrumented iPhone16/iOS27.0 build24A434 XCTest passes:1case,0failures,0skips,129.013seconds case time. Original Start/Stop, native UDP, Spd./Vol. table and portrait/landscape conditions remain. runtimeWarnings=[] and cleanup=[]. Five original exported PNGs were inspected; no injected counter values or edited screenshot pixels. |
| Physical/product scope | No physical SideStore/LiveContainer, device background/energy/throughput verification, new iPhone archive/IPA or release merge. |

Apple host: Xcode27.0 27A266a, iPhoneOS27.0, Apple Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428. The raw build log still contains, for example,
AppIntents metadata-extraction diagnostics. Empty compiler/runtime-warning summaries
do not mean that every tool/framework message is absent.

## Original artifacts and preservation

| Artifact | SHA-256 |
| --- | --- |
| Statistics Linux11010008605 | 54f1df2fe088fa15ef8eec9a82d3d52d4a3730ef480865eac26c4e2fd07f0d0e |
| Statistics macOS11009979380 | 20ca14f4bfa9f9eb5feafc20604c8337ebd72e98222bdf63ce9711db5feb8970 |
| UDP Linux11010451592 | ed28590b32ef81ac702220cafcf6193cfc98cb89001e59c4dd3a7ea1f006e8c0 |
| UDP macOS11009717370 | 7333902025025c913bad5db2a5ef04564c4f58b179a5279d3f08612d44086771 |

All four downloaded ZIP digests match GitHub metadata and all CRCs pass. The three
Statistics source archives have the exact tested commit comment and93 identical
tracked file bytes/Git modes; independently reconstructed trees equal55e97808.
The two prerequisite archives contain57 identical files from UDP9909aa5f, not the
triggering statistics commit. The243 regular native-source files/modes also match
between current Linux/macOS and the preceding successful artifacts. No native patch
or production Swift change is concealed by the added tests.

The closing commit changes only this dated review and the identical README/feature
specification. The README update appends the new contract/results reference while
preserving all45,977 preceding bytes. The other90 of93 paths remain byte/mode-equal
to the tested source. This documentation closure is not a separately executed build.
Other seven branch refs are retained; no feature composition, background interval,
settings, icon, release or build9 IPA is changed.

The final conclusion is successful-I/O accounting coverage within the defined
socket boundary, not lossless transport of arbitrary original datagrams. Known
fixed-port multi-association, buffer/truncation, snapshot timing, finite-counter,
malformed-protocol and physical-deployment limits are not erased by a passing run.
This completes the requested payload accounting revalidation without inventing a
production repair or expanding the measurement boundary.
