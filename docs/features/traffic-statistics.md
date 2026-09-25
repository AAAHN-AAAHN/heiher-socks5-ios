# Traffic statistics for the native iOS SOCKS5 relay

## Final re-audit scope — 2026-09-26

This independent feature measures successful external socket I/O and explicitly
inherits the completed UDP compatibility owner. The three statistics patches and
all production Swift remain unchanged. This revision strengthens native/UI source
identity, UI working-directory binding and failed-attempt product markers, and
inherits the corrected UDP peer-test reservation. The statistics network fixture
also now reserves the dual-stack wildcard it launches, not just IPv4 loopback.
The new combined native/SDK/Simulator run 36197421806 passed all four jobs.
Revision-linked outcomes, earlier failure evidence and preserved limits are recorded
below; older green runs are not substituted for this new execution.

The preceding complete specification is preserved verbatim in
`docs/history/statistics-before-final-audit-20260926.md`, including all historical
failures, accepted accounting limits and earlier UI execution. The corresponding
UDP history is retained with its owner. This README and
`docs/features/traffic-statistics.md` are identical.

## Target, baseline and feature boundary

Primary intended use is a physical **iOS 27 iPhone**, through **SideStore standalone
installation** or **LiveContainer guest execution**. They have separate signing,
container, local-network permissions and host lifecycles. SDK compilation and
Simulator execution are not either physical installation. The configured minimum
remains **iOS 17.2**, not certification of every OS since that version. Record actual
Xcode/SDK/host/Simulator builds and tested commit/run separately from intended use.

The unchanged main baseline is `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
Build/features.json retains the exact upstream app/server/submodule pins and orders
three UDP patches followed by three statistics patches. The committed XCFramework
is the unpatched baseline: builds requiring stats APIs must rebuild the declared
patched library before linking. This audit creates no iPhone archive or IPA and
does not replace the committed framework. A temporary Simulator-only library is
rebuilt for the actual UI test and remains a separate test product.

Only Statistics and the original Server UI are present. Statistics is first in tab
order, but the standalone initial selection remains Server and is not persisted.
There is no JSON store, Background service, separate server-controller feature,
custom icon, VPN/NetworkExtension, resolver replacement or new permission. Server
options, defaults, app root/project/plist and native startup behavior are preserved.
The separately maintained integrated release is not automatically refreshed.

## Exact accounting contract

| Metric | Meaning |
| --- | --- |
| In | Positive bytes returned by reads/receives on the external side of the relay. |
| Out | Bytes accepted by successful external-side writes/sends, not remote acknowledgement or guaranteed delivery. |
| Total | Display sum of independently sampled In and Out counters. |
| Speed | Counter differences divided by the actual monotonic sampling interval. |

TCP and UDP accumulate in the same two process-lifetime UInt64 counters. Stop/Start
within the process does not reset them; a new process starts from zero. Counters are
not JSON settings or a durable billing ledger. An external read remains In even if
later client delivery fails. Partial writes add only accepted bytes. Failed requests
and unsent datagram suffixes add nothing. UDP output sums only the returned successful
send prefix; UDP input is counted before forwarding to the client.

HTTP/TLS/QUIC headers or control bytes inside the external socket payload are
included, as is client DNS relayed through these sockets. Client-facing SOCKS
negotiation/authentication/UDP framing is not counted again. IP/TCP/UDP wire headers,
OS ACK/retransmission, other applications and VPN/interface overhead are excluded.
Hev's getaddrinfo delegation to the system resolver does not expose its internal DNS
wire lengths here; that traffic remains excluded. No resolver rewrite, packet capture,
wire-size estimation, per-connection classification or measurement expansion is added.

The two relaxed atomic counters prevent lost concurrent increments/data races for
each number; they do not form a single atomic pair snapshot. UInt64 is finite and can
wrap. Large Double display totals have finite precision. Existing batch send wrappers
may yield before returning the successful prefix, so accounting visibility can lag
individual sends. This is not a syscall timestamp ledger or total cellular usage.

## Implementation responsibilities and cost

`hev-stats-task-io.patch` extends the existing buffered/Linux-splice transfer helper
with optional accumulation and a synchronous transfer callback. The old public API
is a no-callback wrapper over the same implementation. Only side B's external reads
and writes are reported; callback delivery occurs before the loop's cancellation
boundary. No duplicate relay loop or packet-to-Swift dispatch is introduced.

`hev-stats-core.patch` owns two fixed atomic counters, connects the external TCP
callback and UDP forwarders, and preserves partial/error/bind/cancellation behavior.
`hev-stats-server.patch` exposes a small C query; both output pointers must be nonnull,
as the Swift call supplies. Querying totals neither enumerates sessions nor performs
network I/O. The three statistics patches still affect nine C/header files with
97 net added lines; inherited UDP modifications are not charged to that count.

TrafficStatistics.swift computes UInt64 differences before Double conversion. First
sample, decreased counters and a non-increasing clock reset the rate baseline.
TrafficStatisticsView.swift samples immediately on visible/active entry and about
every second thereafter; cancellation stops only presentation sampling, not native
counters. Reentry starts a fresh display baseline. Uptime, not wall-clock time,
measures the interval. Decimal KB/MB/GB are bytes; Kbps/Mbps/Gbps are bits per second.
The display adds converted totals to avoid UInt64 addition overflow.

Costs are bounded native comparisons/counter operations and periodic visible UI
queries/formatting. There is no per-packet allocation/history, extra relay socket,
thread, timer, disk write or new native path in this revision. Timing, energy and
maximum throughput were not benchmarked; minimal code is not proof of zero overhead.

## UDP inheritance and preserved operating limits

The completed UDP owner `7f603a7e063422df460fb171d3b95b36cc6230af` is an
actual Git parent/ancestor, not merely a README label.
Its source/tests/documents are mapped byte-for-byte, including executable modes;
the reusable prerequisite workflow and audit constant pin the same completed SHA.
Sixteen paths are explicitly mapped, including the newly preserved UDP history.
Statistics tests do not edit the inherited UDP audit to masquerade as a UDP-only app.

Use **UDP Listen Port = 0** for multiple unknown-client associations. This is local
endpoint allocation per association, distinct from the client's unknown source port
in its request. Default `1080` and fixed-port selection remain unchanged. Fixed
ports with several unknown-client associations retain their accepted independent-
closure/ownership limitation; observation failures are reported, not counted as
required passes. Peer filtering does not certify cryptographic identity, every
same-IP first-port race, fragmentation, datagram size or arbitrary network routing.
No dispatcher, automatic fallback, client protocol or operating-policy change occurs.

## Re-audit findings and exact corrections

The native audit and UI audit previously allowed working/index changes while
publishing a HEAD archive. Both now reject working-tree-versus-HEAD and
index-versus-HEAD differences before source/native/Apple work and again before final
success. This catches an index-only staged change even if the working file is
restored. UI's existing before/after hash checks remain. These checkpoint comparisons
are not an atomic filesystem snapshot or certification of arbitrary untracked input.

UI output commands now use ROOT rather than the caller's working directory. A real
unrelated Git repository control shows the old query returned the wrong repository's
HEAD; the current query stays bound to its own source root. UI retries clear only
SUCCESS and the two old Simulator app/library hash markers before rejection paths,
retaining diagnostic logs. Product markers identify their phase, not whole-run success.

The original statistics network fixture reserved only IPv4 loopback while starting
a dual-stack wildcard listener. Its exact reservation accepts a port occupied on
IPv6; the corrected reservation uses AF_INET6, IPV6_V6ONLY=0 and `::`, matching
the server without retrying or weakening test deadlines. Four actual-socket
old/current free/conflicting-port cases establish that mismatch and correction.
Reservation release-to-bind races are not claimed eliminated.

Tests/Statistics/input_probe.py executes exact old/current entry points with isolated
real Git fixtures. Sixteen native/UI clean/unstaged/staged/index-only cases, two cwd
controls, four workspace/optimized failure-marker cases and four reservation cases
pass locally: 26 cases in four test methods. The fixtures
stop intentionally at a downstream source/SDK boundary and never claim to execute
Hev, Apple SDK or Simulator. Existing three native stale-success tests and all prior
network/model/sanitizer/UI assertions and deadlines remain unchanged.

## Validation and outcome recording

Use a complete Git checkout for original blobs, dependency ancestry and source gates:

```sh
python3 Tests/Statistics/audit.py
# On the actual Xcode 27 host, after the native audit:
python3 Tests/Statistics/ui_audit.py
```

The normal workflow first validates the exact UDP prerequisite on Linux and macOS.
Statistics then clean-builds actual Linux buffered/splice and Darwin buffered modes,
checks object symbols, runs each mode's twenty network executions and eight peer/queue
cases, counter stress with eight writers/800000 updates, actual-I/O ASan/UBSan, Darwin
counter TSan, 10000 model samples and six pipe framing/deadline cases. Formatter 18,
pins, composition and patch reversal remain required. Darwin checks nine affected
C/header files and all five production Swift sources against the iOS 27 SDK.

The existing real Simulator XCTest uses an isolated source/project copy, scrolls
and taps Start/Stop in portrait/landscape, verifies native SOCKS greetings and their
cessation, and navigates both tabs. Four full-screen attachments and XCTest/process
verdicts are separate evidence. The test does not certify live traffic display,
every field/keyboard/Dynamic Type/iPad configuration, physical installation or phone
interruptions. Optional platform diagnostics and test deadlines are not weakened.

Native SUCCESS and UI SUCCESS cover separate phases. Inspect complete workflow jobs,
source SHA/tree/mode, original ZIP digest/CRC, per-test logs and cleanup; old green
badges or partial failed output do not establish success. Preserve each failed
attempt and distinguish a rerun from an earlier job result carried into its listing.
A later docs-only commit must remain byte-identical in all build/test/runtime inputs.
No synthetic counter stress or repeated case is relabeled as an independent device
trial or equivalent actual network volume.

## Explicitly unperformed boundaries

SideStore signing/install, LiveContainer loading/container behavior, physical
permissions, iPhone IPv4/IPv6/hotspot/VPN paths, real interruption/lock/background
survival, Files UI, power/throughput and every supported OS/device remain separate,
unperformed tests for this revision. Standalone statistics includes no keep-alive.
Main, unrelated feature refs, integrated release, branch count and existing IPAs
remain unchanged. The detailed historical evidence remains in the archived spec.

## Completed final re-audit — 2026-09-26

Final tested source: `e90faf827611a72abf0a4e6994d99cb43ea1e671`, tree
`6a53de56c3dbdcf9963fb828d927548ec670a928`, 78 files. Run **36197421806**,
attempt 1, completed successfully in all four jobs: the exact UDP prerequisite
on Linux/macOS, then statistics Linux and statistics macOS including actual UI.
No earlier success or partially completed job was substituted for this matrix.

The prerequisite archives contain the completed **UDP 7f603a7e** source, not the
statistics trigger SHA. All sixteen owner mappings and source modes match it.
Each prerequisite passed 58 required UDP profiles, eight peer/queue cases and all
ten driver methods. In its observation-only fixed-unknown profiles Linux workers 1
passed 9/9, Linux workers 4 and macOS workers 1/4 passed 8/9 with the retained
concurrent-close timeout. A single 9/9 observation does not remove that limitation.
The independent UDP run 36196306325 recorded 8/9 for both worker counts on both hosts.

Statistics passed twenty network executions and eight peer/queue cases in each of
Linux buffered, Linux splice and Darwin buffered modes, identified from actual
object symbols. Eight-writer/800000-update counter checks, partial/error/cancel
I/O probes with ASan/UBSan, Darwin production-counter TSan, 10000 model samples,
six pipe-reader cases, three existing audit-driver cases and all 26 new input/cwd/
marker/reservation cases passed. Pins, composition, formatting and exact patch
reversal passed. Input/final working-tree and index logs are empty. The nine affected
C/header files and five production Swift files passed actual iPhoneOS 27 SDK checks
at the unchanged ARM64/iOS17.2 target; compiler diagnostic logs are empty.

The original Simulator XCTest passed **one test, zero failures and zero skips**
in **130.416 seconds** (test case time, not workflow duration). Actual scrolling,
Start/Stop taps, SOCKS greeting availability/cessation, and both tabs in portrait/
landscape were exercised. Four full-screen original attachments and the stored
xcresult root/test records were inspected. xcodebuild exited successfully and
cleanup.json is []. Two AppIntents metadata-extraction warnings and debugger/
Simulator diagnostics remain; this is not a claim of universally warning-free or
hang-free execution. No test assertion, 900-second test deadline or optional
system-diagnostic collection setting was changed to produce this success.

The intermediate candidate `d9fac7e788f8449a25302466db5ffbc2caa48c34` in run
36197029599 had native/SDK success but failed before XCTest on a 120-second
Simulator bootstatus timeout; shutdown/delete each exceeded 30 seconds. Its original
failure artifact is preserved, with native SUCCESS but no UI SUCCESS or app hash.
Its completed Simulator-library phase hash is not an overall success. The subsequent
source adds the independently reproduced statistics-reservation correction and four
controls. The final run is a new-source execution, not a same-source retry or proof
that the port change caused the unrelated CoreSimulator boot recovery. The internal
boot-stall cause remains unestablished.

Actual Apple environment: Xcode 27.0 `27A266a`, iPhoneOS 27.0, Apple Swift 6.4
`swiftlang-6.4.0.34.1`, macOS 27.0 `26A428`. Actual UI: iPhone 16 Simulator,
iOS 27.0 `24A434`. SideStore/LiveContainer and physical runtime remain unperformed.

| Original final-run artifact | SHA-256 |
| --- | --- |
| UDP prerequisite Linux 10890696359 | 465413617d6c7a85f59104eae2e361ec6b140c6418db4b534f068800260a39d8 |
| UDP prerequisite macOS 10890479416 | 224812616f356f98ad67215af221ba3186f6fadd2990f8274c81447795a89a56 |
| Statistics Linux 10890960240 | 901b6aa1b4895c3b9db22f486e8a2be883a94054473d50a18de2c52530b22b6f |
| Statistics macOS/UI 10891760071 | 74b6124075ec74a7e9e1032f5eea2bdb176c9658ca7169bdb9c77592cadc38df |

Intermediate failure artifact 10890598987 has SHA-256
`003c5966c0f1ecf94c201a2819f980934ed68660dfdd828684fbea5efe2a1978`.
All downloaded ZIP CRCs/digests and genuine source comments were checked. Native and
UI archives match all 78 tested paths, modes and bytes, and all 78 UI source hashes
match. The final documentation-only commit changes this README and its identical
feature specification; the other 76 files remain identical to the executed source.
The previous 75-file source is recovered by exact reverse application of the
complete audit patch. All native patches, application code, project, plist, baseline
framework, build inputs and source pins are unchanged from the review start.
Main, Background, server/persistence/icon, release and the eight-branch count remain
unchanged. No IPA is built or relabeled. The offline companion verifier checks
source/artifact identity and patch round trips, not a new native or Apple execution.
