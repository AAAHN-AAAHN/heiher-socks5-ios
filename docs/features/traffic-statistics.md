# Traffic statistics — aggregate and client-IP payload accounting

## Target and unchanged baseline

The primary target is physical iOS27/iPadOS27 installed independently with SideStore
or executed as a LiveContainer guest. Signing, containers, permissions and shared
host process state differ; neither Xcode direct installation nor Simulator execution
substitutes for those targets. Configured minimum remains iOS17.2. SDK compilation,
Simulator, native tests, device archive/IPA and physical execution are distinct
verification levels. Original principles remain in docs/top-level-principles.md.

This feature extends `feature/traffic-statistics` at
`bb07d1795f010d624b1924cc06203af9aeb3c6a2`. Composition remains main75335d20 ->
UDP9909aa5f -> statistics. The completed Background9d87d7cf, other feature branches,
main, release8577bb1f and the previously supplied build9 IPA are not changed.
This standalone branch does not include Background, settings persistence, the
separate ServerController or the custom icon. No new IPA or release merge is part
of this feature implementation. The unchanged committed XCFramework is upstream
baseline input; products must rebuild and link the patched native library.

## Measurement contract

Existing aggregate In/Out remains authoritative and unchanged in meaning. In counts
successful payload reads from destination-side sockets; Out counts successful
payload writes to those sockets. Destination-side is a socket role, not a test for
public versus private destination addresses. TCP buffered/splice and UDP batch
boundaries are preserved, including partial successful I/O before error and external
receive bytes even when later forwarding to the client fails. System DNS resolver
traffic, SOCKS framing, IP/TCP/UDP headers, retransmissions, peer acknowledgements and
VPN/radio/billing usage remain outside the boundary. No packet inspection is added.

At the same existing accounting events, each amount also increments the bucket of
the SOCKS control connection's observed peer IP. Ports are ignored: TCP connections,
UDP associations and Hev UDP-over-TCP from one IP share a row. IPv4 and its mapped
IPv6 representation normalize to one IPv4 key; real IPv6 keeps its scope identifier.
An explicitly supplied UDP endpoint does not replace the requester's control-peer
identity. UDP peer discovery/filtering and forwarding policy are unchanged; fixed
UDP-port multi-association restrictions remain, and UDP Listen Port0 is still the
recommendation. No client protocol change, MAC/name discovery or device fingerprint
is introduced. NAT-hidden clients sharing one observed IP cannot be separated; a
changed IP is a different bucket. Same-IP reassignment merges usage by design.

Totals and IP buckets live for the process, not a connection. Stop/Start, closing
connections or hiding the screen does not erase usage. A new app process starts at
zero. No disk history, reset/export API, destination history or extra network request
is added. Failure to obtain/normalize the peer or allocate its bucket must not stop
relay: the aggregate and an explicit Unattributed bucket still receive the bytes.
Unattributed is hidden only while both its totals are zero.

## Native implementation and concurrency

The task-io statistics patch and its exact byte-count arithmetic are unchanged.
TCP uses the existing synchronous callback context. UDP carries the same context
through its two existing forwarding functions. A context is obtained once per relay
from the control socket, never per packet. No base object layout or native worker
scheduling policy changes. Original three UDP patches, native source pins, shared
build files, framework input, project/plist and permissions stay unchanged.

The core collector keeps a 256-bucket address hash registry and immutable process-
lifetime entries allocated by libc, not the task allocator. This deliberate lifetime
survives native worker/server teardown and avoids per-packet reference counting or
use-after-free during snapshots. Memory grows linearly with distinct observed IPs,
not packets or reconnects; entries are not silently evicted or reassigned. Allocation
failure sends that relay's usage to Unattributed. This is not an unlimited-memory
promise and hostile high-cardinality inputs remain a resource consideration.

A short mutex protects only lookup/registration and capturing a list head/count.
Byte updates use existing relaxed aggregate atomics plus relaxed per-IP atomics;
they do not take that mutex, allocate, stringify, query addresses, yield, call Swift
or log. Immutable links let readers enumerate a captured list without holding the
registry lock. Entries are never removed while relay code holds their pointer.

The additive public API `hev_socks5_server_client_stats(rows, capacity)` copies
caller-owned rows (id, numeric address, In, Out). It returns required capacity;
NULL queries the size. ID0 is Unattributed, IDs1..N are stable registry indices.
Only min(capacity, count) rows are written. If registration races the size query,
older rows still fit and newer rows appear at the next sample; no dangling native
pointer crosses into Swift. Existing aggregate API remains available unchanged.

Counter pairs and different rows are independently sampled, not transactional.
During concurrent traffic, aggregate and row sums can temporarily differ. At rest,
the sum including Unattributed must equal the aggregate (subject to UInt64 wrap).
Do not add global per-packet locking merely to force a visual live snapshot equality.

## Swift model and screen

The Total table appears first, followed by IP tables in native registration order.
Each entry has an identifying section title, bold In/Out/Sum column headings and
bold Speed/Transferred row labels. Two always-visible data rows use regular black
values on a white surface, with light-gray header/label separator lines. Sum combines
unrounded directions before numerical rounding to three decimal places; Total is
used only as the aggregate title, never as an internal column label. No expansion
tap is required. The existing
TrafficStatistics delta/format model is reused per native ID; no second formula or
native sampling thread is added. Counters are subtracted as UInt64 before Double
conversion. First samples, nonincreasing times or decreased counters establish a
zero-rate baseline. Decimal KB/MB/GB/TB/PB and Kbps/Mbps/Gbps/Tbps/Pbps use the
same 1,000-based scaling. Value cells may shrink to 50% of their normal text size.

One visible/active-tab task samples the aggregate and rows immediately and about
once per second using monotonic systemUptime. Leaving the tab or inactive scene
cancels the task; returning starts fresh speed baselines, not fresh native totals.
This is unrelated to Background's 0.5-second recovery timer, which is untouched.
Native counters continue while the server runs even when the view does not sample.
The list is stable by registration ID rather than jumping around with current speed.

Costs: one IP lookup/registry lookup per relay, extra per-direction atomic additions,
process-lifetime memory per distinct IP, and visible-tab snapshot/format work. There
is no zero-overhead claim or measured iPad energy/throughput improvement. Local UDP
fixture timing is an observation, not a physical-device or before/after benchmark.

## Validation and reproduction

Use a full clean Git checkout with historical objects:

```
python3 Tests/Statistics/audit.py
# On the recorded Xcode27 host:
python3 Tests/Statistics/ui_audit.py
```

The workflow preserves exact completed UDP prerequisites. Shared main/native-input,
index, source-pin, reverse-patch, marker and port-reservation guards remain. Only
four explicit statistics runtime paths may change from bb07d179: two Swift files
and the stats core/server patches; the task-io and UDP patches stay frozen.

The native audit retains original aggregate/partial-I/O tests and adds real dual-stack
TCP/UDP and UDP-over-TCP attribution, same-IP multiple connections, asymmetric TCP,
fd churn, Stop/Start, and 2000 small UDP exchanges. A direct actual-collector fixture
injects only peer lookup/allocation failures and tests mapped addresses, IPv6 scope,
unknown fallback, snapshot capacity/canaries, reentrant enumeration, concurrent
registration/writers/readers, stable IDs and quiescent equality. ASan/UBSan apply to
the included collector; macOS TSan additionally checks its actual concurrent paths.
Test-only injection is not a physical network event. Swift model tests cover per-IP
baselines/rates, unknown visibility, idle counters, overflow/time edges and tab reset.

The uninstrumented Simulator test retains original Server controls, real greetings
and orientation/scrolling/navigation gates. The current table test uses real IPv4/IPv6
UDP round trips and verifies both data rows without expansion. No production source
is replaced by test doubles. The source stays distinct from the disposable product.
Expandable and compact-UI execution records below are historical; the current table
revision has its own final result recorded in the last section.

### Completed implementation and validation — 2026-09-28

The tested source is `065855d41f61dba1c96e8b27e5ec44ad184e68e1`, Git tree
`4a72eb9d14c3f325cfeb22cc2bf7b61343ee0741`. Run `36382538730`, attempt 1,
completed all four jobs successfully: exact UDP prerequisites on Linux/macOS and
statistics on Linux/macOS, including the actual uninstrumented Simulator app.
The closing commit updates only README and this identical feature specification;
the other 85 of 87 tested paths retain their exact bytes and Git modes. It does not
claim a new execution of a documentation-only commit.

| Evidence layer | Actual result and scope |
| --- | --- |
| Prerequisite ownership | Both jobs checked out UDP9909aa5f, not the triggering statistics commit. Both original 57-file source archives match. Main ancestry, all 17 mapped owner files, original three UDP patches and source pins remain exact. |
| Existing aggregate accounting | Linux buffered/splice and macOS buffered pass the original network scenarios (20 executions per mode), eight peer/queue cases, 8 writers/800000 aggregate updates and partial-I/O/cancellation probes. Existing external read/write boundaries and the task-io patch are unchanged. |
| Real native IP attribution | Each mode passes dual-stack control-peer attribution, same-IP connections/associations, known/unknown UDP endpoints, asymmetric TCP/half-close, UDP-over-TCP, concurrent TCP/UDP, socket-number churn, and Stop/Start retention. Per-IP sums including Unattributed equal aggregate totals at rest. |
| Collector concurrency/failures | The actual collector fixture passes IPv4-mapped normalization, IPv6 scope, lookup/allocation failures, no hot-path lookup, snapshot capacity/canaries, callbacks outside the lock, concurrent registration/reads and eight writers. ASan/UBSan pass on the included collector and boundary probes; macOS also passes actual-collector and aggregate TSan. These are scoped sanitizer targets, not whole-program sanitizer certification. |
| Swift models | Existing 10000-sample aggregate model passes. The per-IP model passes debug/optimized: independent rates, first/idle samples, stable IDs, unknown visibility, counter/time edges and resetting view baselines without resetting native totals. |
| Guards and Apple SDK | Common 46-case and statistics 26-case input/marker checks, three audit-driver and six pipe-reader cases, format/reverse-patch, clean source/index and composition checks pass. Patched native C/headers and five production Swift files typecheck for ARM64/iOS17.2 against iPhoneOS27 with warnings-as-errors and empty diagnostic logs. |
| Simulator product and UI | The disposable product rebuilds and links the patched native library. iPhone16/iOS27.0 build24A434 runs one XCTest successfully, zero failures, 71.368 seconds case time. Both portrait/landscape exercise actual Start/Stop, SOCKS greetings, a real 64-byte UDP payload, client-row visibility/expansion and tab navigation. Original four screenshots inspected; cleanup is []. No production mocks or injected counter values are used in that app. |
| Archive/IPA and physical devices | No iPhone archive/IPA or release merge is produced. SideStore standalone and LiveContainer guest execution, physical-device/network behavior and before/after power/throughput/latency are unperformed. |

Original CI artifact ZIPs were SHA-256/CRC verified. Linux native, macOS native and
Simulator source ZIPs share the expected commit comment and all 87 files/modes;
independent Git-tree reconstruction matches the tested tree above. The two UDP
prerequisite source ZIPs independently match the owner ref and each other. The
closing documentation files are the only final-source differences.

A supplemental Linux/Swift6.2.1 replay independently rebuilt the exact patched native
source and reran buffered/splice network/accounting/collector tests plus ASan/UBSan,
and both Swift models in debug/optimized modes. Another local test ran 24 concurrent
TCP+UDP tasks using distinct IPv4 control peers127.0.0.2/127.0.0.3 to the same
server/destinations. Their directional totals were20544/20676 bytes, respectively;
the aggregate was41220 bytes per direction, also retained over Stop/Start. This is
local loopback verification, not a physical LAN or device test. It does not replace
the full-history CI provenance checks or Apple execution.

The 2000 sequential 64-byte UDP echo fixture per mode remains only a local timing
observation: this run's Linux buffered/splice medians were0.141/0.143ms and macOS
buffered0.166ms. It is not an old/new benchmark, maximum packet-rate test or evidence
of no overhead. IP-cardinality memory growth and independent live snapshots retain
the limitations described above. In UI, a single localhost client was exercised;
multiple actual device rows, every Dynamic Type/keyboard case and iPad layouts were
not physically tested. Screenshots do not certify every cell is visible at once.

Recorded Apple host: Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428. Compiler diagnostics are empty, but raw build
logs retain tool/framework diagnostics; not every warning category is claimed absent.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux10953452120 | 4e3bd8a38d124498902820333f358f33bafbacda572ebcaaa89e3057fa38a823 |
| Statistics macOS10953129549 | ed426a1edcdaa41cc17bc3ac95b3ca6bb1313d446fc99f61098d66f7d81226be |
| UDP Linux10953122325 | 9c235a1c7f9b4da9223a84aa2362fd4e632a87471c35253a3b95b2a585ef49c6 |
| UDP macOS10952633248 | a6712a2508a3041f954d62072f387c0bb4f210762c1dd85fcbf45ab64d59c9af |

### Retained UI failures and their correction

Earlier implementation runs did not pass all UI gates. Run36377790407 left the
landscape Form at0percent after application-level swipes. Its artifact10951348700
(SHA25658c031f7412f7e1eb66317d1a6cee60498b3255735a87af7298031ea7af6d420)
was retained by the preceding resume. Commit12a70a4 targeted the recorded CollectionView
instead; run36379621481 then scrolled to100percent past the retained expanded client
header. The raw accessibility snapshot still contained its Total Out0.13KB; the
header was above the visible cells. That attempt failed the client-button assertion
(82.596-second XCTest) and subsequently exceeded the existing900-second xcodebuild
process timeout. Original artifact10953370179 is preserved unchanged, SHA256
08605fba59db7df76b84f7153b84e79f23f56243e4443613c2774cfffef6770b; cleanup was [].
This evidence identifies a test scroll-position problem, not lost native counters.
The later result-completion timeout's internal cause is not established.

Commit065855d4 changes only the test gesture sequence: use a bounded return to the
existing top section, then short content drags to find the IP header without skipping
it. The test still requires both orientations, reachable client header, expansion,
actual payload, Server control behavior and original timeouts. No production layout,
accounting, sampling, native code, assertion removal or timeout increase was used to
manufacture a pass. The final fresh run passes all these gates. Earlier failures
remain failures and are not retrospectively relabeled successful.

The preceding aggregate-only specification and its successful36226383235 results
are preserved exactly in docs/history/statistics-before-client-ip-20260928.md.
Only feature/traffic-statistics advances. Background9d87d7cf and its0.5-second audio
recovery are unchanged, as are the other feature/main/release refs and old build9 IPA.
Physical SideStore, LiveContainer, real device IPv4/IPv6/VPN/hotspot/Moonlight, long
locked-iPad operation, power and before/after throughput/latency remain unperformed
for this new feature. The existing build9 IPA does not contain these changes. A
future release integration must inherit this feature and run its combined validation.

## Compact two-line presentation — 2026-09-28

This UI-only revision starts at3a740eba. Aggregate Total comes first, then registered
IP rows by stable native ID. A nonzero Unattributed row retains its ID0 ordering
before identified peers. The section header names the aggregate/IP; the two data
lines beneath it show In/Out speed and In/Out/Total accumulated bytes, respectively.
Both kinds of entry call one shared summary renderer; formatting and delta arithmetic
reuse the existing model. Values use monospaced digits and single-line labels with
limited text scaling to reduce truncation on narrow layouts. Extreme user font sizes
and arbitrarily large formatted values are not guaranteed to fit a small screen.
All explanations follow the data rather than separating aggregate and IP entries.

There is no native, model, accounting-boundary, sampling-task, source-pin, entitlement,
project or Background change. Normal Statistics sampling remains1second visible/active;
Background retains its independently validated0.5second interval. No additional timer,
persistent state, snapshot lock, player pool or packet inspection is introduced.

The UI test keeps Server Start/Stop, actual native greetings and portrait/landscape
requirements. It now generates actual UDP round trips through IPv4 and IPv6 control
peers, verifies Total then registration-ID order and both unexpanded data lines, and
captures original Simulator screenshots. Native counters are not injected. Captures
are taken after Stop, so zero displayed speeds are expected; retained nonzero totals
come from those completed socket transfers. XCTest attachments are exported by
xcresulttool and retain original pixels. No mockup is presented as a Simulator capture.

### Completed compact-UI verification

Tested commit `2c7c6d9ee79897e7a6014bbcb9b4983397d9237e`, tree
`d56a297a9c133e65297ce08ec95944cd5de490fa`, passed run `36386541673` on attempt 1.
All four jobs succeeded: the exact UDP prerequisites on Linux/macOS and statistics
on Linux/macOS, including the rebuilt uninstrumented Simulator app. The closing
commit changes only README and this identical specification; all other 85 of the
87 tested paths retain the same bytes and Git modes. A documentation-only commit
is not represented as a separately executed build.

The fresh native accounting/attribution, collector and boundary sanitizer, Swift
model and source/patch/ownership checks pass. Five production Swift files and the
patched native C/header inputs pass the iPhoneOS27 ARM64/iOS17.2 SDK checks with
warnings-as-errors; both SDK diagnostic logs are empty. The UI-only guard verifies
that native/model/project paths and the task/sample bodies remain unchanged.

On iPhone16 Simulator, iOS27.0 build24A434, the original Server/navigation gates and
new two-line/order assertions pass: one XCTest, zero failures, zero skips,
78.837 seconds case time. Both orientations relay a real 64-byte UDP round trip from
127.0.0.1 and then ::1. Both speed/usage lines must be reachable without expansion;
the portrait header positions confirm Total before the two registration-ordered IPs.
The raw summary reports runtimeWarnings=[], and cleanup=[]. This does not claim
that every tool/framework diagnostic category is absent.

Original exported portrait and landscape screenshots were inspected and retain their
pixels. Portrait shows Total and both IP entries together. Landscape is captured
after scrolling to the IP entries; it does not show all entries at once. Each client
has64bytes per direction after the first portrait cycle; the second orientation
adds another transfer without resetting counters. Values are formatted by the
unchanged decimal model, not injected for a screenshot. Speed is0 because the
server has been stopped before sampling. The original screenshot SHA-256 values are:

| Capture | SHA-256 |
| --- | --- |
| Portrait | 7e255d539402505f9b2b15bc58d12c9a7ef216f26361da2a758c123ab8853cbd |
| Landscape | 619861b52ddc8ed54e5e273b617f58524a0d45cb8bc1acbfd84ce546d471f624 |

All four original artifact digests and ZIP CRCs were verified. The statistics native
and UI source archives match the tested commit and87 paths; both prerequisite
archives contain the exact57-file UDP owner9909aa5f. Local Swift parse, Python AST,
whitespace and source preservation checks, plus debug/optimized per-IP model tests,
also pass; these local checks do not substitute for Apple execution.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux10954058773 | 8282575b34d49ea83b7a77607b48c8f4aeecf2d4d4030ad5bb098c8881389294 |
| Statistics macOS10955007837 | 6d3ee7ddcbdb4d8f050588f52a0723d065bf4724ad7d52f0fc26ced0cf0280ba |
| UDP Linux10955175423 | 9a8145f4614f2ebe7f3bee699a5ad9b95144b1ec9f9eb98781983584c41d6124 |
| UDP macOS10954163229 | 59d42b25b184390cda91e044971be5a0dcfce2a81558ebd7119a9a6a491f1816 |

No IPA or release merge is produced. Background9d87d7cf, its0.5second recovery and
all other branches remain unchanged. Physical SideStore/LiveContainer execution,
iPad layouts, extreme Dynamic Type, very long IPv6 strings, many-client scrolling,
actual LAN devices and comparative performance remain unperformed for this UI.
Earlier failed implementation UI runs remain the historical records above; this
presentation revision passed its first exact-source workflow without retries.


## Table presentation and three-decimal precision — 2026-09-28

Supersedes the compact two-line layout above, from803a1ef2; its previous execution
records remain historical, not proof of this table revision. The aggregate is always
a section titled Total, even before a client is registered. Registered IP sections
follow unchanged stable-ID order. A shared Grid renders blank/In/Out/Sum above
Speed and Transferred. Labels are bold, numbers regular black; the table uses a white
surface even in dark appearance so requested black values retain contrast. A light
0.82-gray one-point rule separates headings from data, and the label column from
values, matching the requested reference without drawing a heavy full-cell grid.
Existing Form scrolling is retained; no custom renderer, extra refresh task or
per-IP sampling loop is introduced. Narrow value cells retain bounded font scaling.

Speed Sum is receiveRate+sendRate before formatting, not addition of rounded strings.
Transferred Sum converts both UInt64 counters before adding, retaining overflow-safe
display behavior. One shared formatter numerically rounds the selected SI-unit value
to the nearest0.001 (half away from zero), then prints exactly three decimals using
a fixed decimal point. The selected unit thresholds are unchanged: a rounded value
may read1000.000KB immediately before the original MB threshold. Raw UInt64 counters,
Double rates, sampling times and deltas are NOT rounded or fed back from display;
that would silently lose low-volume traffic over repeated samples. Sum can differ
from adding the displayed directions by0.001 because it is independently rounded
from the unrounded values. No claim of three-decimal physical measurement accuracy
or exact decimal representation of arbitrary Double inputs is made.

Runtime changes are restricted to TrafficStatisticsView.swift and the computed
sumRate/formatter in TrafficStatistics.swift. Native patches, source pins, network
I/O/UDP policy, registry, aggregate and IP lifetime, sampling/task bodies, project,
permissions and every other branch stay unchanged. Statistics still samples at one
second while visible/active; Background9d87d7cf remains unchanged at0.5seconds.

The existing aggregate formatter expectations are updated to three decimals; the
per-IP model suite now checks Sum before rounding and10001 independent Decimal
rounding controls in both debug/optimized builds. UI tests retain real UDP data,
IPv4/IPv6 registration order, Stop/Start, both orientations and existing timeouts.
They additionally require an initial zero-valued Total before IP creation, aligned
In/Out/Sum columns, both rows without expansion and exact three-decimal amounts.

### Completed table-UI verification

The tested source is `9af714c6ae31ec28efc06bc3b50e28c0fc732345`, tree
`1955cc006f737cddea863c2d381c3766d3a8708c`. Run `36408272957`, attempt 1,
finished successfully in all four jobs: UDP prerequisites and statistics on both
Linux and macOS, including the rebuilt uninstrumented iOS Simulator product.
The closing commit changes only this README and its matching feature specification;
the other 85 of 87 paths retain the tested contents and Git modes. No new execution
is attributed to the documentation-only commit.

| Verification | Result and scope |
| --- | --- |
| Numerical model | The existing 10000-sample aggregate model passes. The per-IP suite passes in debug and optimized builds, including 10001 independent Decimal rounding controls, fourth-decimal ties, SI boundaries, raw-first Sum and preservation of unrounded counters/rate baselines. |
| Native regression | Existing Linux buffered/splice and macOS buffered accounting, partial-I/O and IP-attribution tests pass. Collector and boundary ASan/UBSan, macOS collector/counter TSan, source/index/patch/ownership and previous input/driver controls pass in their existing scopes. Native patches are unchanged by this UI revision. |
| Apple SDK | Five production Swift files and the patched native C/header inputs pass ARM64/iOS17.2 type checks with iPhoneOS27 and warnings-as-errors. Both compiler diagnostic logs are empty. |
| Actual Simulator | iPhone16, iOS27.0 build24A434: one XCTest passes, zero failures and zero skips, 111.793 seconds case time. Initial zero Total, table heading order, six three-decimal values per table, aligned columns, Total/IP registration order, both orientations and original Start/Stop/native UDP gates pass. |
| Runtime and cleanup | Exported result reports runtimeWarnings=[] and cleanup=[]. This is not a claim that every raw tool/framework diagnostic category is absent. |
| Preservation | All three statistics source archives agree on the 87 paths and tested commit. Independent reconstruction matches the tested Git tree. Both 57-file prerequisite archives agree on UDP9909aa5f. Task/sample bodies, raw delta calculation, IP registry/model ordering, native inputs and every other branch remain unchanged. |

The original portrait and landscape screenshots were exported from XCTest with
xcresulttool and inspected directly, without redrawing, counter injection or pixel
editing. Portrait shows Total, 127.0.0.1 and ::1 together; the IPs were registered
in that order by real loopback UDP round trips. It displays 0.128KB In/Out and
0.256KB Sum for Total, with 0.064/0.064/0.128KB for each IP. The landscape capture
is scrolled to the IP tables and does not show the top Total title simultaneously.
A second round trip per peer raises each IP to 0.128/0.128/0.256KB there. Speeds
are 0.000Kbps because the test stops the server before sampling. Nonzero Sum-speed
and rounding behavior are checked separately in the numeric model, not inferred
from a zero-speed screenshot. Captures cover normal font size and these actual
values, not arbitrary large numbers, long IPv6 addresses or every device layout.

| Original screenshot | SHA-256 |
| --- | --- |
| Portrait B260B102-581E-4889-963E-425FFAB5E3FC.png | 66e1f3420d6d188f7ae0c32abc3e5b9384332e9f1e73251b5c2aabeac37a3799 |
| Landscape 1AF225F3-9086-4A85-99B1-3AC3E8707B4B.png | 2a682b101377704573efa96bbbb9c30d87072148a0e96856f5f301a74d53f324 |

Original artifact ZIP digests and CRCs were checked. The resumed local review also
reran both aggregate and client models in Swift6.2.1 debug/optimized modes and
parsed the SwiftUI source. Git-mode normalization distinguishes ZIP permission
metadata from tracked Git modes; independently reconstructed current and baseline
trees match the actual commits. These checks do not substitute for Apple execution.
The table implementation was already committed before this resume; no duplicate
runtime patch, new workflow run, relaxed assertion or increased timeout was needed.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux10963636735 | 0aa1305112e3aa668c9a3f363ce71009aa29b920a206ce3cbe1ec1525d67f282 |
| Statistics macOS10964006405 | f8ba1705d2557d3b48dab45250773c2b886a59269c4b9e63361c382608b355f7 |
| UDP Linux10963461765 | cfbdc2d08814d214ff45c4599a2a8a47942aa4c30e65bf7ace5ec25226288778 |
| UDP macOS10963038090 | 9670e3f1b34da6e9d8c3f942eb28cb3bc427c113965ac1ddca3fffaf6160be13 |

Recorded Apple host: Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428. The minimum deployment setting remains17.2;
this is not an execution claim for every OS version. Physical iPad, SideStore
standalone, LiveContainer guest, extreme Dynamic Type and very long address/value
layouts remain unperformed. This scoped task creates no iPhone archive/IPA and
performs no release integration. Background9d87d7cf and its0.5second recovery,
other feature/main/release refs and the existing build9 IPA remain unchanged.

## TB/PB units and 50-percent minimum text size — 2026-09-28

This display-only revision starts at78610b59. Speed now scales through
Kbps/Mbps/Gbps/Tbps/Pbps; transferred amounts use KB/MB/GB/TB/PB. Every step is
1000-based, and the final unit remains PB/Pbps even above1000PB/Pbps. The common
formatter selects the unit from the unrounded amount using at most four bounded
steps. It then applies the existing numeric half-away-from-zero rounding and
exactly three printed decimals. Existing KB/MB/GB results below the new threshold
are unchanged, including display rounding to1000.000 just below a unit boundary.
Native UInt64 counters, raw rate deltas, raw-first In/Out/Sum and one-second visible
sampling are not rounded or modified. There is no accounting or Background change.

Examples:1000.000GB becomes1.000TB at1e12bytes,1000.000TB becomes1.000PB at1e15bytes.
362234.567GB is now362.235TB. A UInt64 maximum displays18446.744PB, and the combined
maximum of two counters displays36893.488PB. Speed follows the same SI steps after
the existing bytes-per-second to bits-per-second conversion. Units are not capacity
or throughput limits; no physical PB traffic or Pbps transfer is claimed.

The shared cell's minimumScaleFactor changes from0.7 to0.5. Text may remain at its
normal size or shrink as needed down to50percent; it is not fixed at half size.
Three-decimal values, header labels, Grid layout, gray rules, colors and ordering
are otherwise unchanged. The left-side Speed/Transferred labels retain their
existing sizing. Very large strings or extreme accessibility sizes may still be
truncated after the minimum scale is reached; this is not a universal fit guarantee.
The on-screen units explanation includes the two new levels.

Production changes are limited to TrafficStatistics.swift and the cell scale/footer
in TrafficStatisticsView.swift. No new timer, state, native patch, sampling task,
project/permission change or live-data fixture is added. Unit selection adds at most
two bounded iterations relative to selecting among three units; this is display
formatting, not per-packet work. No energy/throughput measurement is inferred.

Tested commit `631c8524c01d9b12cca9ca52527ec2a0279c0f1a`, tree
`2ba7818125a2ca1f1910b060c9c823247fbcfbc9`, passed run `36419879916` on
attempt 1. Both exact UDP prerequisites and Statistics Linux/macOS jobs succeeded.
The original native accounting, source/index/ownership and scoped sanitizer checks
remain intact. Both aggregate/client models pass debug/optimized, retaining10001
original Decimal controls and adding20002 TB/PB reference values checked for both
capacity and speed, new thresholds/ties, PB cap/UInt64 maxima and cross-unit Sum.
A supplemental local comparison verifies100000 inputs against the actual preceding
formatter below the TB threshold; a deliberate test copy missing PB is rejected.

Apple host: Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4 swiftlang-6.4.0.34.1,
macOS27.0 26A428. Native C/headers and five production Swift files pass ARM64/iOS17.2
SDK checks with warnings-as-errors and empty compiler logs. The original uninstrumented
iPhone16/iOS27.0 build24A434 XCTest passes in122.047seconds: one test, zero failures,
zero skips, runtimeWarnings=[] and cleanup=[]. This checks ordinary table behavior
and real small UDP totals, not synthetic PB-valued layout or a measured50% glyph size.
No UI predicate, test deadline or production sampling path was relaxed.

Original Statistics ZIP digests/CRCs and all87 source paths, Git modes and commit
comments were independently verified; the three native/UI source snapshots agree
and reconstruct the tested tree. Local Linux/Swift6.2.1 model execution and SwiftUI
syntax checks are supplemental, not substitutes for Apple SDK/Simulator execution.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux10968793414 | d3b7d333d56dfe3e93f5ff91ba32c54ab33803f71b555a847894485b6d34b2f1 |
| Statistics macOS10969675512 | 599a1deaa0970db4f0d3d3583ddf6dbd3322ada4ac2694939baace656292adfb |


The prior long-values capture run36416219714 used the preceding three-unit/70percent
layout and synthetic display values. It is historical layout evidence, not validation
of the new PB/50percent rendering. This revision does not claim new physical iPad,
SideStore or LiveContainer execution, arbitrary font/layout coverage, or a new IPA.
Background9d87d7cf, other feature/main/release refs and the existing build9 IPA remain
unchanged. The final documentation commit updates only this README and its identical
feature specification; the other85 of87 paths correspond to the tested source.


## Completed strict statistics audit — 2026-09-28

Baseline `ad2c3e00956b825ce3cdcd59e1a5b4f13fad6139` was reviewed across native
accounting, IP attribution, snapshots, numeric formatting, table layout and task
lifetime. The actual branch is feature/traffic-statistics. Detailed scope, design
choices and test boundaries are in `docs/reviews/statistics-strict-20260928.md`.

The only production change publishes the client model once per native snapshot:
build a local value with the existing per-IP sampler, then assign it to State.
This replaces unnecessary per-row State writes and can avoid repeated copying when
value storage is shared. No native miscount or per-row SwiftUI render was measured.
The original sample-body guard reverses only these explicit edits before checking
all remaining bytes. No new persistent property, cache, timer, queue, API, native
patch, layout, model formula or sampling interval is introduced.

Tested commit `bdcb3fbb8cac9ac88ba8c47108977592ecd46a8b`, tree
`2ea2ff8b213598a0e1222062fa251d9e7f24265c`, passed run `36425863911` on
attempt1. All four jobs succeeded: exact UDP prerequisites on Linux/macOS and
statistics on Linux/macOS, including the rebuilt uninstrumented Simulator product.
New exact-method tests pass98,516 conditions per compiler mode for512 clients and
64 intervals. The exact prior view fails the new one-publication condition with513
setters, not incorrect native totals. Expanded native tests add2,048 IP keys beyond
256 hash buckets, collisions, fd aliases, ten capacity/canary conditions, concurrent
registration/snapshot boundaries, unsigned wrap conservation and allocation fallback.
Normal/ASan/UBSan pass on both hosts; macOS TSan passes in its collector scope.

All existing native accounting, partial-I/O, peer, ownership, format, source/index,
Swift models and Decimal controls remain and pass. Five production Swift files and
native C/headers pass iPhoneOS27 ARM64/iOS17.2 checks with warnings-as-errors and
empty diagnostics. iPhone16/iOS27.0 build24A434 passes the original XCTest:1case,
0failures/0skips,88.733seconds; runtimeWarnings=[] and cleanup=[]. Original portrait
and landscape attachments were inspected. This small two-client UI test does not
measure a512-client SwiftUI frame rate or certify PB/maximum-font-size layout.

The four original artifact ZIPs were SHA-256/CRC verified, and the91-path statistics
sources agree in commit comment, bytes and Git file modes. Independent reconstruction
matches the tested tree. Local extracted-source buffered/splice replay and a fresh
exact-sample replay in both compiler modes are supplemental to the full-history CI.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux10971144098 | 643443f36533961d6b27fcf930b9b952cdecda6a0d48bc6eed6ca49016e5e3bf |
| Statistics macOS10971980948 | ce48113eb9582fa92caa578e01dec3fe65a75d984838b60e9c6c2bbd0dd42a48 |
| UDP Linux10970558868 | d566e77d19a46bcee7389976a18c30e516f620cca0e5f794851c0616e54408af |
| UDP macOS10971074297 | f154c20df49d466a0fe1458ef538ae32d192179366add1aa6d21b82e3140288b |

The closing commit changes this README, its identical feature specification and the
audit report only; the other88 of91 paths retain the tested source. No additional
native-accounting defect was reproduced in this review. Finite tests are not a
proof of every system or event history. IP-cardinality memory growth, independent
live snapshot reads and possible truncation at the50% scale floor remain documented
limits. No new IPA/release merge, physical SideStore/LiveContainer, long locked-iPad
or comparative power/throughput test is claimed. Other seven refs and build9 IPA,
including Background9d87d7cf and its0.5second recovery, remain unchanged.
