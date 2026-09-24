# Traffic statistics for the native iOS SOCKS5 relay

## Supported versions, installation environments and verified scope

Historical environment re-audit: **2026-09-23**; current closure is recorded below. The intended support environment,
configured minimum OS, SDK build and actual runtime tests are different claims.
The native-only audit descriptions later in this document describe their own
scoped checks; the separate re-audit below also built IPAs and ran Simulator tests.

| Boundary | Version/environment and evidence |
| --- | --- |
| Configured minimum iOS | **17.2**, unchanged. This deployment target is not evidence that every iOS version from 17.2 onward was tested. |
| Primary intended environment | **iOS 27.0 on a physical iPhone**, installed independently with **SideStore** or run as a **LiveContainer guest**. These are separate installation/execution paths, not interchangeable with Simulator or Xcode installation. |
| Verified iPhone build | **Xcode 27.0 (27A266a), iPhoneOS SDK 27.0, ARM64**. The unchanged production build produced an IPA; archive identity, metadata, linkage and ZIP integrity passed. |
| Verified runtime | **iOS 27.0 Simulator (24A434)**: the actual app launched with its original Bundle ID and a controlled remapped ID. The native-relay test shell used the same rebuilt library bytes as the app. This is not the owner's physical 27.0 (24A437) build. |
| SideStore status | Installation-related source/dependency review and controlled ID-remap tests completed. Actual SideStore signing, provisioning, installation and physical-device launch were **not performed**; no specific installed SideStore version is certified. |
| LiveContainer status | Host/guest dependencies were reviewed. Actual loader transformation, JIT-less signing, host permissions, installed version/options and physical guest execution were **not tested**. No blanket LiveContainer compatibility certification is claimed. |

Verified functional scope: the native statistics network scenarios passed **40/40**
executions on Linux (buffered/splice) and **20/20** on Darwin (buffered). Counter,
partial/error/retry I/O, sanitizer, Swift model and type checks passed. The iOS 27
Simulator native fixture passed **20/20** scenario executions across original and
remapped IDs. Its test shell did not exercise production Start/Stop buttons or
Statistics-tab transitions. That historical run used UDP at
`49784b7c78a99dab824eceeb071e459bc94b2e90`. The current dependency and its
workflow/document copies were subsequently updated again in the reconciliation
record below. The original two UDP repairs remain; an inherited peer filter was added.

Known limits remain explicit: use **UDP Listen Port = 0** for concurrent
unknown-client associations. The Simulator screenshot also shows the inherited
Server screen extending behind the floating tab bar near its bottom controls;
unobstructed layout/hit-testing and whole-app UI acceptance are **not established**.
Actual device/host local-network permissions, hotspot/VPN transitions, physical
IPv4/IPv6 paths, lock-screen survival and energy/throughput remain untested here.

This branch contains UDP plus statistics, but no Background feature. Its two native
counters and visible/active-scene SwiftUI sampling do not use BGTaskScheduler,
NetworkExtension, host-ID scheduling or feature-specific signing entitlements.
No BGTask whitelist, forced LiveContainer Bundle ID option or host IPA edit is
required by this implementation. Ordinary installer signing and local-network
permissions still apply. Continuous background operation needs the separate
`feature/background` (silent audio/location) composition; this re-audit does not
merge it or certify `release/integrated` as a whole.

Tested production revision: `eee9269965e3236fd05c40506648aef4a865aebf`.
Evidence: [run 35815248222](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/actions/runs/35815248222)
completed with **all four jobs successful**. Its audit-control commit is
`c644dcfa8976094e8443511c3f4c869536a34d5b`, not the production revision above.
The [immutable full review](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/7b397d0251ca0f167b93ed2e4a8713c3599e977c/Validation/FINAL-REVIEW.md)
records toolchain, tests, known limits, artifact hashes and earlier failed attempts.
Adding this support record changes documentation only, not the tested executable
sources, deployment target or previously delivered IPA.

**README maintenance rule:** for future code or verification changes, update this
section and its identical feature-document copy with the minimum OS, intended
installation paths, exact tested OS/build and tool/host versions (or explicitly
unknown), tested commit/run, passed/failed/not-run scope and remaining limits.
Keep SideStore standalone, LiveContainer guest, SDK/Simulator and physical-device
evidence separate. Never promote a successful build into unperformed device tests.

## Scope and final measurement decision

This is `feature/traffic-statistics`. It combines the finalized UDP prerequisite
with one independent feature: native transfer counters and a Statistics tab. The
complete app is on `release/integrated`; this branch does not add Background
services, JSON settings, the custom icon, or the settings lifecycle controller.
The owner has explicitly retained the existing measurement scope. This review
adds no DNS resolver, packet capture, interface counters, estimated headers, or
new traffic category.

The main baseline is `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`. It combines iOS app
`180012e8b9dbaa2002a68ebd2c75bccebcfb789c` with unpatched server
`b3585289622561caf4b8789b436cc8820ecd6be0`. Exact submodules are in
`Build/upstream.json`; `Build/features.json` selects UDP plus statistics and six
ordered patches. These are reproducible pins, not automatic upstream tracking.

The current UDP prerequisite is `66e7196ef5faccc43d9b154cab21a94e4466a77e`.
The preceding reconciliation used `34cc49f01bbbcb4cc1ed9b7e050640f7cae14c72`;
`05524e3fb917f2a0e5264bc9919118fcc484cb11` and
`49784b7c78a99dab824eceeb071e459bc94b2e90` belong to older verification.
The earlier prerequisite `ae466dab1a394af0c83f3dc36e51755f25f91910` was merged by
`d34e49478d7e061b8824e9f431b40998db25f8b2`, the original statistics-review start.
The current prerequisite is also merged as a Git ancestor, not merely cited in a
README. Fifteen inherited files, including the peer-filter/queue correction and
its tests, workflow and completed reviews, are preserved byte-for-byte. The original
statistics production-code freeze is unchanged. The retained UDP recommendation is local **UDP Listen Port = 0**.
The known fixed-port / unknown-client / concurrent-association limitation is not
declared repaired. The combined workflow checks the exact UDP-only checkout first,
then the statistics composition; neither runtime implementation is rewritten.

## Purpose and why measurement belongs in the core

The owner wanted a small Python-proxy-like display of In/Out rates, cumulative In
and Out, and their combined Total, with minimal native overhead. The observation
point is the external-facing half of the relay, not both proxy hops and not all
traffic of a VPN/interface. Counting the client's upload receive and the external
upload send together would count the same transfer twice.

The existing C I/O already knows the successful byte count and socket direction.
The patch exposes those numbers rather than adding a Swift socket implementation,
process-wide I/O hook, packet sniffer, descriptor registry, or another transport.
The app only samples two numbers and renders them. All original relay buffers,
coroutines, retries and error returns remain in use.

## Exact In/Out contract

| Metric | Counted event |
| --- | --- |
| In | Positive byte counts returned from reads of external-facing relay sockets. |
| Out | Positive byte counts accepted by successful writes/sends to external-facing relay sockets. |
| Total | The displayed sum of cumulative In and Out, not a third independently maintained counter. |

TCP and UDP share process-lifetime totals. They begin at zero before server startup,
survive ordinary server Stop/Start, and reset when the process is replaced. They
are not persisted settings. Out does not mean that the remote endpoint acknowledged
or received the bytes. In is retained when the later write to the hotspot client
fails. Failed attempts are not added, and reattempting an unaccepted suffix is not
a second transfer. The public API requires two non-null output pointers.

### Included and excluded data

All bytes inside the external socket's stream/datagram payload are counted; no
HTTP, TLS or QUIC parser removes their headers or control messages. Client DNS
traffic relayed through these same sockets is counted like other data. Conversely:

- Client-facing SOCKS5 negotiation, authentication and UDP encapsulation are not
  external-facing relay payload and are not counted a second time.
- IP/TCP/UDP headers, OS-generated ACKs/retransmission and another app's VPN overhead
  are below this measurement boundary. No guessed header constants are added.
- Hev's own `getaddrinfo()` work is delegated to the system resolver. The DNS wire
  messages produced internally are not available as relay I/O buffers or lengths.
  Neither fake IP use alone nor every DNS message implies such an exclusion.
- API addresses, `sockaddr`/`iovec` metadata, local synchronization socketpairs,
  failed request lengths and connect/bind/shutdown calls are not payload bytes.
- Unread kernel-queued data and any truncated-away part never returned to Hev are
  not included. Existing UDP buffer/security/association limits remain unchanged.

This is therefore **successful external socket I/O**, not total radio usage,
remote-delivery confirmation, application file-body size, or whole-system traffic.
The owner's final decision is to keep this boundary, not replace the resolver just
to obtain DNS byte counts.

### When values become visible

TCP reports once per existing splice loop, before yield/exit evaluation. UDP In is
published after the external receive batch and before forwarding to the client.
UDP Out is published after the existing sendmmsg wrapper returns its successful
prefix. That wrapper may yield while waiting to complete a batch: bytes accepted
by earlier underlying sends can become visible later. The one-second rate display
uses counter deltas and actual elapsed time, not individual syscall timestamps.
This reporting delay is retained intentionally; no per-datagram Swift dispatch or
new lower-I/O hook is introduced. A process kill can interrupt reporting, and the
process totals are not a durable ledger.

## Independent file inventory and inherited boundaries

Before this review, 24 paths differed from main: 14 statistics-owned paths and
10 verbatim UDP dependency paths. The project file contains both UDP plist wiring
and statistics additions, so only its statistics delta is independently reviewed.
The audit produces the current complete inventory rather than hiding test/doc
changes behind a runtime-only list.

| Statistics-owned path | Purpose |
| --- | --- |
| `Build/features.json` | Select the three statistics patches after the three inherited UDP patches and declare the common main baseline. |
| `Patches/hev-stats-task-io.patch` | Optional byte-report callback in the existing buffered/Linux splice implementation; preserve the legacy API. |
| `Patches/hev-stats-core.patch` | External-side TCP/UDP wiring and two relaxed atomic counters. |
| `Patches/hev-stats-server.patch` | Small public C query API used by Swift. |
| `Socks5/Statistics/TrafficStatistics.swift` | Value model, time deltas and decimal unit formatting. |
| `Socks5/Statistics/TrafficStatisticsView.swift` | Rates/totals form and visibility/scene-scoped sampling task. |
| `Socks5/AppRoot.swift` | Two-tab composition and the visibility signal to Statistics. |
| `Socks5/Socks5App.swift` | Use AppRoot as the scene root. |
| `Socks5.xcodeproj/project.pbxproj` | Register three added Swift files and their group; preserve framework linkage and existing settings. |
| `Tests/traffic_stats_host.c` | Test-only C host for querying live process totals and restarting the actual server. |
| `Tests/traffic_stats_regression.py` | Real sockets, asymmetric and concurrent transfers, header exclusion, idle and server restart checks. |
| `Tests/traffic_statistics_model.swift` | Actual production-model tests, including large totals and 10,000 deterministic samples. |
| `README.md` | Canonical feature specification and operating boundaries. |
| `docs/features/traffic-statistics.md` | Identical canonical specification at the feature-document path. |
| `.github/workflows/verify-build.yml` | Run the pinned UDP-only prerequisite and require its success before the statistics native/type audit; no app archive or IPA. |
| `Tests/Statistics/audit.py` | Source identity/inventory, enforced I/O modes, native probes and iOS type checking. |
| `Tests/Statistics/tcp_probe.c` | Include actual I/O code; script partial writes, failures and cancellation boundaries. |
| `Tests/Statistics/udp_probe.c` | Include actual UDP forwarders; check successful-prefix sums and receive-before-delivery-error semantics. |
| `Tests/Statistics/host_probe.py` | Test-only pipe framing, silence/partial-line deadlines, EOF and bounded rows. |
| `Tests/Statistics/audit_driver_probe.py` | Failed/rejected retry regression: invalidate an old success marker while retaining diagnostic logs. |
| `Tests/Statistics/counter_probe.c` | Real counter/public-getter stress with concurrent writers and readers. |
| `docs/reviews/traffic-statistics-20260922.md` | Focused findings, evidence scope and final disposition. |
| `docs/reviews/traffic-statistics-20260923.md` | Follow-up final review, stale-success regression and matching completion evidence. |
| `docs/reviews/udp-statistics-alignment-20260923.md` | Latest-UDP merge, complete dependency map, preserved runtime and joint verification evidence. |

The following fifteen files are dependencies, not independent statistics edits:
three UDP patches; six `Tests/udp_*` files; `Socks5/Info.plist`; the UDP feature
specification and both dated UDP reviews; `docs/branches/feature-udp-compat.md`
(verbatim UDP root README); and `.github/workflows/udp-compat-audit.yml` (verbatim
UDP workflow under another name). The mixed build manifest still selects UDP plus
statistics; its source pins and ordered UDP patch prefix match the prerequisite.
The project retains the UDP metadata plus its separate statistics registration.
The exact mapping is enforced by UDP_FILES in Tests/Statistics/audit.py.

The isolated UDP audit retains its UDP-only guard and runs on its own pinned
checkout through the unchanged reusable workflow. The statistics workflow requires
that job before its own matrix; it never invokes the UDP-only driver on a combined
manifest or modifies an inherited file to make that guard pass. The audit verifies
that the workflow checkout ref equals its UDP pin. This is a reproducible snapshot,
not an automatic promise to follow future remote branch movement.

Common baseline build scripts, source locks and the committed unpatched framework
are also unchanged. New tests and documents are not app target sources/resources.
The original Server screen, including its upstream lifecycle behavior, is not
rewritten by this feature; the separate server-control feature owns its later controller.

## C implementation, correctness and standard style

### Task-system patch: existing TCP I/O, optional observation

`src/lib/io/basic/hev-task-io.c` and its header in HevTaskSystem gain a callback type
and `hev_task_io_splice_with_stats()`. The original `hev_task_io_splice()` remains a
thin no-callback wrapper over the same implementation. Two lower helper variants
accept optional accumulators. Successful reads from side B and writes to side B
are reported; side A is never added to these external counters. Positive returns
alone advance counts, so EOF, EAGAIN and failure codes cannot become unsigned bytes.
The callback runs synchronously and must neither block nor yield. The active caller
only adds counters. Existing circular buffers, pipes, partial writes, half-close,
error processing and cancellation points are retained, not copied into a new loop.

### Core patch: fixed-size counters and UDP batch sums

In `src/core/src/hev-socks5-misc.c`, two static `_Atomic uint64_t` objects are
zero-initialized. Independent relaxed fetch-add/load operations prevent lost
updates and data races without a lock protecting unrelated state. They publish
numbers only, not other objects or their lifetimes. Querying the pair is not an
atomic two-value snapshot. No reset operation competes with worker updates.
Unsigned 64-bit arithmetic is finite and can wrap modulo 2^64; this is not an
unlimited-precision accounting system. The display re-baselines observed decreases.

The private header declares the writer and the public core header the getter.
`hev-socks5-tcp.c` supplies the callback to the existing side-B relay. In
`hev-socks5-udp.c`, Out sums only the successful prefix of `dvec[].msg_len`; values
in unsent suffix entries are never counted. In sums received lengths before client
forwarding, so a subsequent client send error does not erase an external receive.
The existing batch size and syscall/retry behavior do not change.

### Server API patch

`src/hev-main.c` forwards `hev_socks5_server_stats()` to the core getter and
`src/hev-main.h` declares its uint64 outputs inside the existing C/C++ linkage block.
Swift passes two distinct initialized local UInt64 variables. No session enumeration,
allocation or network operation is performed by querying the API. Both pointers
are contractually non-null; defensive branches for a caller the app does not make
are not added to a hot query path merely to lengthen the implementation.

The three statistics patches change nine C/header files, 102 additions and five
deletions (net 97 lines). Existing GNU C dialect and upstream class/interface,
header guards, naming, indentation and formatter rules are preserved. Public header
declarations and iOS ARM64 compilation are checked. The patches remain byte-identical
to the working pre-review version; no speculative optimization is introduced.

## Swift, UI lifecycle and resource cost

The two Statistics files remain 109 lines combined. The model subtracts UInt64
values before converting the deltas to Double. It uses monotonic uptime supplied
by the view, not civil time. First entry, counter decreases and non-increasing sample
times establish a zero-rate baseline. Finite timestamps and nonnegative byte/rate
inputs are the internal caller contract. Capacity formatting is not arbitrary-input
validation. Large totals are converted separately before their displayed sum so
UInt64 addition cannot trap; formatting is rounded to two decimal places.

The view is MainActor-isolated. Its task identity is `isVisible && scenePhase ==
.active`. On entry it queries once, then sleeps approximately one second between
queries. Cancellation during sleep exits; a second cancellation guard precedes the
next sample. Hidden/inactive states do not run the sampling loop. Re-entry resets
only the display baseline, never the native counters. It makes no Swift callback
for each packet. Task lifecycle and UI wiring are source/type checked; device view
transitions and lock-screen scheduling are not simulated by headless model tests.

Tabs are Statistics then Server; this isolated branch initially selects Server.
Persistence/last-tab restoration belongs to the settings feature, not this one.
There are no graphs, packet logs, connection histories, extra sockets, dynamic
counter maps, repeating storage writes, or per-packet tasks. Added cost is bounded
scalar accounting and display formatting while visible. Shared atomic updates may
contend under heavy multi-worker load; no measured bottleneck justifies per-worker
arrays or merge timers. Functional tests do not establish zero overhead, a speedup,
or absolute optimality among all possible implementations.

## Final verification and corrected coverage

Run on a clean checkout with Python 3, Clang, make, Swift and clang-format 18:

```sh
python3 Tests/Statistics/audit.py
```

The GitHub workflow first runs the unmodified UDP-only audit at the pinned UDP
commit on Linux and macOS, in separate jobs/checkouts. Only after both succeed does
it run this statistics audit. Running the command locally performs the statistics
composition checks; it does not silently launch the separate UDP audit. Run that
on its pinned checkout when reproducing the complete two-branch verification.

The audit checks main and current UDP ancestry, all source pins, frozen UDP blobs, all unchanged
production files, the entire main-to-feature diff, statistics registration/wiring,
and exact upstream formatting of the nine affected C/header files. It applies the
six ordered patches to freshly fetched pinned code and reverses them afterward.

A review finding concerned the inherited build script's Linux mode labels.
HevTaskSystem defaults `ENABLE_IO_SPLICE_SYSCALL` to 1. Merely using empty CFLAGS
for a run called buffered does not disable that Makefile option. Historical log
names alone therefore do not prove two different native server paths. This focused
audit passes the actual Make variable as 0/1, cleans between variants and inspects
undefined symbols of the built I/O object: buffered must reference its circular
buffer implementation and not splice; splice must reference splice and not the
circular buffer. Generic readv/writev wrappers exist in both builds and cannot
discriminate them. macOS is buffered.
The shared main-owned build script is not changed in this branch-only review.

The interrupted audit run `35712649925` was not successful. Its macOS make failed
when `V=1` activated an upstream `undefine` directive unsupported by that runner's
make. Its Linux buffered tests passed, but an incorrect assertion expected common
readv/writev wrappers to disappear in splice mode. The audit now uses
`ECHO_PREFIX=` for verbose commands and verifies the actual splice/circular-buffer
symbols. Neither fix changes production code. Test probes are formatted with the
same upstream style and exact formatter equality is required, not just archived.

Each confirmed mode executes the existing ten live-network statistics scenarios
twice. Tests use ephemeral relay ports and do not turn the accepted UDP limitation
into a new release gate. The counter probe performs 800,000 actual add calls from
eight threads with concurrent public API reads; large synthetic additions are not
presented as petabytes of network traffic. TCP and UDP probes include real patched
translation units with scripted I/O boundaries and run under ASan/UBSan. macOS also
instruments the production counter implementation with TSan. Supporting libraries
are not all sanitizer-instrumented, and leak detection is not a whole-app leak audit.

On macOS the nine C/header files undergo iOS ARM64 syntax-only checks. All actual
Swift app sources are typechecked against the iPhoneOS SDK and the patched public
C header via a temporary module map, without building an XCFramework or linking an
app. No `build-apple.sh`, Xcode archive, IPA packaging, release update or other branch
write occurs. Header type checking is not an iPhone binary/linker or UI test.

Tests use temporary files, bounded waits, explicit failures and cleanup. The native
host's complete response line has a monotonic deadline, EOF handling and a bounded
4096-byte buffer; silence and partial lines cannot bypass it. Startup failure cleans
up the process, and the echo handler has a read deadline. Assertions must be enabled.
The driver removes an earlier SUCCESS.txt before starting or rejecting a new
audit attempt. A failed retry must not leave a previous pass marker usable as
current evidence; existing diagnostic logs are retained. Three test-only cases
exercise a rejected existing checkout, a failed source check, and a fresh failure.
Actual results belong to the matching commit's `artifacts/statistics-final-audit/` logs, tested-commit.txt,
source.zip and inventory.json, not to a reused historical build badge.

## Disposition and primary references

The retained scope is successful external socket I/O. No production accounting,
DNS policy, UI mode or unit definition is changed in this review. The separately
owned UDP peer/queue correction is inherited exactly, not reimplemented here.
The necessary improvements are reproducible statistics-only checks, accurate
coverage/limits documentation and bounded test failure behavior. Known UDP limits
remain accepted and explicitly inherited; functional review is not universal
security, protocol, battery or future-iOS certification.

- Apple task lifecycle: https://developer.apple.com/documentation/swiftui/view/task(id:priority:_:)
- Apple monotonic uptime: https://developer.apple.com/documentation/foundation/processinfo/systemuptime
- C11 draft, atomics and unsigned arithmetic: https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf
- Statistics reviews: `docs/reviews/traffic-statistics-20260922.md` and
  `docs/reviews/traffic-statistics-20260923.md`.
- Latest dependency alignment: `docs/reviews/udp-statistics-alignment-20260923.md`.
- Frozen UDP operating policy: `docs/features/udp-compatibility.md`.
- Main/build policy: `docs/main-baseline.md` and `docs/build-and-validation.md`.

Repository paths above are root-relative. The root README and this feature's copy
are intentionally identical; neither replaces or edits the separately preserved
UDP README and its historical evidence.


## Six-feature closure recheck (2026-09-24)

Input: `63f7689fbcff6cd195e8816eeca556f4cb890311`. The prior branch kept the
correct UDP repair bytes but pinned an older owner commit and copied workflow/docs.
This closure includes final UDP `05524e3fb917f2a0e5264bc9919118fcc484cb11`
as the actual second parent of test commit
`16fb2f2ffcadcd4e0c248850a3670bf2e44b74af`, tree
`5dbb0f57676ddb941b6df539d70f9b95710f6028`. All twelve dependency files match
that owner's exact paths/bytes. The prerequisite checkout and audit constant agree.
This corrects dependency freshness, not a difference in the working UDP algorithm.

Both workflows now select Xcode27 instead of macos-15 and put only clang-format-18,
not all of LLVM18/bin, ahead of the default tools. The actual SDK is recorded and
required to be 27.x. No native patch, app source/resource/project, baseline lock,
runtime sampling or model-test behavior changes. The audit Python delta is only
its UDP commit constant; all source-freeze and negative-control gates remain.

Run `35929832540` passed all four jobs on the first attempt: Linux/Xcode27 UDP
prerequisites followed by Linux/Xcode27 statistics. Latest-owner UDP profiles passed
58/58 mandatory scenarios per host. Statistics passed 40 network executions on
Linux (buffered/splice) and 20 on Darwin (buffered), with actual object-symbol mode
checks, counter stress, partial/error I/O ASan/UBSan, Darwin counter TSan, 10000 model
samples, driver-failure controls and exact patch reversal. The compiled counter
stress remains synthetic accounting, not measured petabytes of network traffic.
iPhoneOS 27 C syntax and five production Swift typechecks passed without diagnostics.

Xcode 27.0 `27A266a`, iPhoneOS 27.0, Apple Swift 6.4 and macOS 27.0 `26A428`
were recorded for the statistics job. Source archives contain 70 exact files.
Own Linux artifact `10780911174` SHA-256:
`ccb80a507aa76e5d8820fe3dd609f0ecbcbc62406cfc3f46ce2d683138251c4b`.
Own macOS artifact `10780224484` SHA-256:
`eacb5684c0874d8647f097cef944742a5bae08eb72a555b48a6fe51f53bcd9f1`.
Prerequisite Linux artifact `10780199520` SHA-256:
`c3248b13f246d2ad5ca78786b3a67ff328271559f0c5cafe7c3353728876ed49`.
Prerequisite macOS artifact `10780841062` SHA-256:
`42afdd76f5e332972cf58f457d027d39144d0d8b4fe12d05164eac7b73ab00ed`.
Both prerequisite source archives contain the final UDP owner's exact 49 files,
including the final documentation, rather than just similar runtime patches.

The independent responsibility remains successful external-facing socket-byte
accounting and visible/active UI sampling. No server-control, persistence,
Background, icon, resolver replacement or whole-interface accounting is added.
Known fixed-port/unknown-client observations remain failures outside the mandatory
profiles, under the accepted port-zero operating guidance. The earlier Server-tab
layout observation is not declared resolved: this fresh run did not perform UI
taps, scrolling or a new Simulator layout review. None of these native/type checks
certifies physical iOS27 SideStore/LiveContainer installation, local-network policy,
host behavior, VPN/hotspot, lock-screen scheduling or energy use.

No additional scoped runtime defect was identified. main/release are unchanged;
eight branches remain. The final own README/specification update is documentation
only, and the successful source/test/workflow bytes are retained. No app archive,
IPA, XCFramework build or physical-device execution occurred in this closure.


## Reconciliation completed: current UDP and statistics (2026-09-25)

The independently observed UDP peer-filter work is retained only in its corrected,
verified owner `34cc49f01bbbcb4cc1ed9b7e050640f7cae14c72`. That owner is an
actual second parent of `af5525667db079c241462bad635d19748c16a721`, not a
README-only dependency. All fifteen UDP dependency files and the ordered three-patch
prefix match it. The original three statistics patches, five production Swift files,
project, app metadata, measurement units and visibility-scoped sampling are unchanged.
Statistics does not gain a dependency on server-control, persistence, Background
or app-icon. Source-IP filtering is not reimplemented in this feature.

The inherited receive path now needs source addresses and getpeername at its I/O
boundary. Tests/Statistics/udp_probe.c supplies those values through its existing
socket doubles while still executing the actual production forwarders and retaining
all successful-prefix, failed-I/O and external-side byte-count assertions. Each real
native statistics mode also executes the eight inherited peer/queued-continuation
cases. This preserves the repaired receive behavior and the original accounting
contract together, rather than treating separate successful branch tests as enough.

The merge's inspected run 36017573747 failed its strict formatter gate,
not an observed production counter failure. The latter's saved formatter output
identified exactly one missing continuation-indent space in udp_probe.c. Commit
`804770ab94f53c4e2149e24fb9db77cfdf56cfc4` adds that one ASCII space only.
It does not disable the gate, weaken assertions, change timeouts, suppress warnings
or modify a product file. The complete workflow was then executed again.

Tested commit: `804770ab94f53c4e2149e24fb9db77cfdf56cfc4`.
Tested tree: `7f2cf559a7bb074d088a72c87fb9c8e3966123ea`.
Run `36023663389` succeeded in all four jobs: current-UDP Linux/Xcode27 prerequisites,
then Linux/Xcode27 statistics. The old failed runs remain failed historical evidence.

| Current verification | Observed result |
| --- | --- |
| UDP prerequisite | Each host passed 58 required compatibility scenarios and eight new peer/queue cases, with old-code controls, address/cancellation sanitizer checks and exact patch reversal. |
| Statistics native modes | Linux buffered and splice each passed 20 scenario executions; Darwin buffered passed 20. Actual compiled object symbols distinguished modes. |
| Peer filtering with counters | Eight real peer/queued-continuation scenarios passed in each of the three native modes; legitimate queued traffic continues after rejected packets. |
| Counter and I/O boundaries | Eight writers/800000 updates, partial writes, failed receives/sends, cancellation, header exclusion and retry checks passed; ASan/UBSan probes and Darwin counter TSan passed. |
| Model and test-driver behavior | 10000 generated model samples, six pipe-framing cases and three stale-success/failure-driver cases passed. These are not device trial counts. |
| Actual iOS 27 SDK | The affected C/header syntax checks and all five production Swift ARM64 type checks passed with no diagnostic output; Swift warnings were errors. |

The statistics macOS job recorded Xcode 27.0 `27A266a`, iPhoneOS SDK 27.0,
Apple Swift 6.4 (`swiftlang-6.4.0.34.1`) and macOS 27.0 `26A428`. The minimum
remains iOS 17.2. No Simulator, physical device, app archive, IPA or XCFramework
was built in this run. The word archive in source.zip logs means a Git source
archive, not an iPhone application archive.

Inspected current artifacts and SHA-256:
- Statistics Linux `10819365758`: `6d4b9beae3fb64a37764c1cca9636dc2679696add05482078f69d030363bc6bb`.
- Statistics macOS `10819255865`: `0b2d8d7224d697819e3d6413dcdd39a202bcabbd96d9c92a27f4537038424d75`.
- UDP prerequisite Linux `10819580126`: `22174958197a4eb5245c6a14256ef939f9dcb14077adbb2411ac67796bd25c9d`.
- UDP prerequisite macOS `10819150548`: `ffaf5724e0478d1d5dcf113b5947d224808e98873fddcfd5ec8c0b9d104667aa`.

Both 73-file statistics source archives reconstruct the tested Git tree; both
52-file prerequisite archives reconstruct the current UDP owner's tree. The failed
and successful statistics product files are byte-identical. All fifteen inherited
paths match their exact owner, including its completed README under the mapped path.
This completion changes only the root README and its identical feature specification.
The test/production/workflow bytes are those of the successful run above.

No newly reproduced mandatory-check failure remains. The known fixed-port/multiple-
unknown association limitation still requires the documented port-zero operating
choice; it was not removed by peer filtering. Same-IP first-port races, complete
protocol/security certification and all deployment topologies are not claimed solved.
The historical Server-tab layout observation has not been retested with real UI
interaction. Physical iOS27 SideStore/LiveContainer installation, host policy,
permissions, VPN/hotspot, lock-screen behavior and energy use remain unverified.
These limits must not be relabelled as passed tests. No runtime overhead is added by
the formatting/documentation completion. main/release remain unchanged and exactly
eight branches are retained. The existing release IPA is not updated by this closure.

## Final six-feature composition closure (2026-09-25)

The current prerequisite is completed UDP
`66e7196ef5faccc43d9b154cab21a94e4466a77e`. Merge/test commit
`0f58e4ddcf3d56a961b075c22ac446e9611c84a2` includes it as an actual second
parent; tested tree `ce46e3420ffd46c847a7ec527c784f2a95dd9585`.
All fifteen mapped UDP paths match the owner exactly. This includes the two
corrected UDP test files, its full completed documentation and unchanged workflow.
The prerequisite checkout and audit constant agree. Statistics production code,
all six native patches, own test assertions, original UI sampling and units remain
unchanged. The inherited test-port reservation does not change the app's UDP policy.

The preceding run `36057681338` failed the Linux UDP test server's startup before
one required profile; macOS UDP passed and statistics jobs were skipped. Its exit254
and empty server log did not identify the original OS errno. The owner independently
reproduced and corrected an IPv6-loopback versus dual-stack-wildcard port-reservation
mismatch, retaining the exact-old-code control. No test retry, skip, extra timeout
or production workaround was added. That failed run remains failed evidence.

Run `36059988736` passed all four jobs on its first attempt: current-UDP Linux and
Xcode27 prerequisites followed by Linux and Xcode27 statistics. Each prerequisite
passed58 mandatory scenarios, eight peer/queue cases and seven driver methods,
with retained negative controls, sanitizers and reverse checks. Statistics passed
20 network executions per native mode (Linux buffered/splice, Darwin buffered),
eight real peer/queued-continuation cases in each mode, 800000-update/eight-writer
counter stress, partial/error/retry I/O probes under ASan/UBSan, Darwin counter TSan,
10000 generated model samples, six pipe-reader cases and three stale-driver cases.
Actual compiled symbols distinguish buffered and splice. Synthetic byte additions
are not measured petabytes of network traffic or independent device trials.

All nine affected C/header files and five production Swift files passed the actual
iPhoneOS27 syntax/type checks with empty diagnostic logs. Recorded toolchain:
Xcode27.0 `27A266a`, iPhoneOS27.0, Apple Swift6.4, macOS27.0 `26A428`.
No app link/archive, IPA, XCFramework, Simulator or physical-device run occurred.

Downloaded ZIPs passed integrity checks. Both 73-file statistics source archives
reconstruct the tested tree; both 52-file prerequisite archives reconstruct the
completed UDP owner's tree, including modes. The mapped dependency hashes agree.
- Statistics Linux `10834316581`: `c093d8223efbb82f9fd8443c3dffeac929e1b64e9785dcfb6372483b4a6fb32c`.
- Statistics macOS `10834262403`: `d98271ddc6798ae0d98685f923079f605d498eabfa58d0fc659d8afc070bfc4e`.
- UDP Linux `10833882488`: `e9daf292459f3c34cd9311ba46eccd0c3e6442e825a9cd2c88a8d3fc416873e6`.
- UDP macOS `10834395950`: `8ef5372eb2816bb0eba02e8b92070ff545bd141dfef498ab44552fd28754cd18`.

This completion updates only README and its identical specification after the
successful run, making the current prerequisite explicit while retaining historical
results. No newly reproduced mandatory-check failure remains. Accepted fixed-port/
unknown-client limitations retain the UDP Listen Port=0 guidance. The historical
Server-tab layout observation and physical iOS27 SideStore/LiveContainer install,
permissions, UI, VPN/hotspot, lock-screen and energy behavior are not newly verified.
The iOS17.2 minimum remains unchanged. No server-control/persistence/Background/icon
dependency is added; main, release/integrated, branch count and existing IPA remain
unchanged. Source and SDK success do not certify all physical deployment conditions.
