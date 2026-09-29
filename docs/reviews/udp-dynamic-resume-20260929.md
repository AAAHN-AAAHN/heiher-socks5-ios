# Adaptive UDP buffer completion review — 2026-09-29

## Final result

Run36535518245, attempt1, passed the complete required Linux and Xcode27 jobs at
`1c5b37d5a6901d455ddecf604b55ad60b91a35cb`, tree
`cb394fdad0e088c5b8b8d9ee32553fcd04967b4a`. Both original artifacts and all67
source paths/modes were checked; independent Git tree reconstruction agrees.
Production is unchanged from04f570c0. The closure modifies only this review and the
mirrored README/specification; the other64 paths remain exactly tested. No new
execution is attributed to the documentation-only closure. The records below retain
intermediate failures and their corrections rather than replacing them with success.

## Resume checkpoint and preserved implementation

The actual resume baseline is UDP04f570c09cf87ddbc99bb4ae638872096f757a60,
not the older9909aa5f owner. Its65-file tree790f421fadcea90b1a2fffa97ad2883b932b6521
already implements the agreed1500/500/300s/60s contiguous-buffer policy as the
fourth core patch. This review retains that production patch, all three original
patches, public interfaces, source pins, app/framework/project/plist, defaults and
workflow. The other seven branch refs and release8577bb1f/build9 remain separate.

The initial run36528932381 passed Linux and failed the macOS forced-short-query
I/O assertion. Original artifact11016170461 has SHA256
4f981585345676cf0939553faeb905049217fd839f18205219171cfa35c7c0cc;
Linux11015424239 has SHA256
7688b08833ceadfa011e0a17fa334ecafbdcf33a6e715aed695779a72457cc2d.
Both downloaded ZIPs passed CRC/digest checks and their65 source files/modes
reconstruct the initial tree. The other same-source run36528924538 also failed. Its macOS artifact11015374337
was subsequently downloaded and inspected: the same forced-short-query assertion
failed at line142. Its SHA256 is
4dcc4361bdd295665ae2fa246e8bc5773bcc9dc51a47859665853cb29f0f333c;
source65-file tree and CRC also match. The duplicate run's origin is not inferred.

## Diagnosed test-input readiness error

Diagnostic-only commitabc4d89c added return/errno/flag output before the original
assertion. Its run36532739499 failed the unchanged formatter18 gate before reaching
that diagnostic. Artifact11017267043/SHA256
6cb9b08fa08ebdcd40bfdd9b9808ccd46a9a4703205907c6206dcc203a4c21c1
preserves the formatter failure. Commit5d45aadb used the exact emitted formatting.

Run36533024131 then reached the actual macOS I/O assertion and recorded
`truncation result=-1 errno=35 flags=0 family=2`. This is EAGAIN before data was
readable, not a successful receive lacking MSG_TRUNC. Original artifact11017831652
has SHA256fc94bb9bb82df28283b02980e636ffc279a69aed0d393a9d59f73b85445fb6fb.
A nonblocking sender's return does not require immediate receive readiness.

The repair is test-only: poll for readable input within a fixed two-second fixture
deadline and collect the available completed prefix before awaiting the next queued
message. All original byte/length/capacity/empty-queue/MSG_TRUNC checks remain,
including no history for forced truncation and the unconsumed datagram after an
allocation failure. Terminal production results are not retried as success. The
original driver timeouts and format/warning/assertion gates are unchanged. Temporary
diagnostic printing is removed. No extra wait, poll or retry is added to the app.

## Additional real-time retention verification

Tests/udp_buffer_live_hold.c supplements, rather than replaces, the controlled-clock
192000-demand oracle and existing real60s cleanup/separate70s timeout fixture.
It sends real48001-byte UDP data, then30001bytes120seconds later; the unchanged
production sizing/receive/history functions consume them. The actual Hev timer and
production cleanup/yield functions must reclaim48500 ->30500 ->1500 after the
respective real300second holds, without traffic after the second demand. No clock,
allocator, interval, production body or expiry is substituted in this fixture.

The producer and consumer are test tasks in an isolated native process. They are
not new production tasks or a physical iPhone deployment. The test uses its own
600s communication timeout so it can observe two holds; application defaults remain
unchanged. Its additional process deadline is490s; the original timer's90s deadline
is retained. Assertions allow bounded host scheduling slack and do not establish
hard real-time reclamation. The shared35minute workflow is unchanged.

## Supplemental execution checkpoint, now superseded

The revised I/O fixture passed local Linux ASan/UBSan and optimized strict-aliasing
execution. Exact-source policy, peer/address/large-network and earlier timer local
replays are supplemental; this archive-based workspace lacks complete historical
Git objects. The complete-history Linux/macOS CI and original-source correspondence that were
then pending are completed in the final record below.
Physical SideStore standalone, LiveContainer guest, background survival, energy,
maximum throughput, Simulator and new IPA/release integration are not claimed.


## Further Apple fixture corrections

At94090c70, run36534142789 passed both actual receive fixture modes on macOS.
It then failed compiling the sender fixture: a counter named `gets` collided with
Apple's stdio declaration, and two substituted socket-option functions lacked
forward declarations because sys/socket.h preceded macro substitution. The original
artifact11017108401 is retained, SHA256
4970daad4fe376ef2ef67a8a7fa31ecb745620ee5799453eb4e8ba93329e9b99.
Commit17d4747e renamed only the counter to get_calls. Its run36534934132 still failed
the three implicit-function errors; artifact11016864676/SHA256
659c4e794bec1c6ce3a0a80410249471753a0aa560926fda90491563566a9520
is retained. Commit1c5b37d5 added only the two compatible forward declarations.
All scripted results, retry/prefix assertions and warnings-as-errors stayed intact.
These are test-build/readiness corrections, not invented production repairs.

## Inspected final execution

Both hosts passed58 original mandatory profile executions, eight peer/queue cases,
existing address/canary/optimized tests,46 common source/marker cases and10 driver
tests. The original three-patch negative control still delivered1490 of2048bytes.
Current large-network records contain426 cases per host covering both families,
numeric DOMAIN, both relay directions, known/unknown peers, mixed small/large/empty
queues, UDP-over-TCP through65000byte payloads, malformed partial frames and workers1/4.
Some records represent grouped concurrent exchanges; these are not independent
physical-device trials or an exhaustive protocol certification.

Actual policy/helper tests pass in ASan/UBSan and optimized modes:192000 demand updates
and10738 sweeps against a full-history reference,500B rounding beyond65536, overflow,
allocation/shrink failure and ownership, small-demand zero clock/allocator work and
maintenance/communication/Stop separation. Actual socket fixtures pass IPv4/IPv6
length/empty/mixed queue, forced truncation and completed-prefix allocation failure.
Actual Apple sender compilation/execution passes lazy sendspace growth, successful
prefix preservation and bounded settings rejection/clamp/repeated-EMSGSIZE cases.
Sanitizer coverage is the included actual source and specified fixtures, not every
instruction of a whole production iPhone process or all possible coroutine histories.

| Actual elapsed observation | Linux | macOS |
| --- | ---: | ---: |
| Original idle cleanup |60.038222s|60.009056s|
| Separate70s communication exit |70.001896s|70.003721s|
| Gap between real48001/30001byte input |120.060335s|120.001666s|
| Capacity48500 to30500 after first input |300.228695s|300.018513s|
| Capacity30500 to1500 after first input |420.318498s|420.030160s|

No input follows the second demand in the latter test. Real clock, interval constants,
actual datagram receipt, allocator and Hev timer are retained. The new test's own600s
communication timeout and producer task are fixture-only. Scheduling slack and blocked
I/O can delay reclamation; no strict real-time promise is derived from these observations.

The actual Apple toolchain is Xcode27.0 27A266a, iPhoneOS27.0, Apple Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428. Patched C/session and the two unchanged Swift
files passed the existing ARM64/iOS17.2 SDK checks. Their diagnostic files are empty.
Formatter18, pins, ancestor/composition, clean worktree/index and exact reverse gates
pass. This UDP workflow does not run a Simulator, create an iPhone archive/IPA or
perform physical SideStore/LiveContainer execution. A successful Linux SDK-skipped
step is not counted as Apple execution.

## Resource observations and limits

Small-payload benchmark: three interleaved old/new trials per size,12000 loopback
roundtrips/window16/workers1, equal payload contents and message counts. The server
child CPU includes startup/Stop; client/echo CPU is outside the number. Medians in
microseconds per relayed datagram are:

| Host/payload | Old three patches | Dynamic | Change |
| --- | ---: | ---: | ---: |
| Linux/64 |12.951|13.079|+0.98%|
| Linux/1200 |13.811|15.493|+12.18%|
| macOS/64 |11.455|10.679|-6.78%|
| macOS/1200 |12.282|10.608|-13.63%|

The raw observations show variation; none establishes a device-wide speedup or a
bounded overhead. The extra query and Linux bulk-receive tradeoff remain explicit.
Post-exec RSS median differences are8KiB/4KiB on Linux and16KiB/16KiB on macOS for
64/1200bytes. These are native snapshots, not peaks or iOS physical footprints.
The raw wait4 high-water values may retain pre-exec parent pages and are not used
as application footprint. No benchmark performance threshold was removed to pass.

A supplemental Linux comparison used a disposable exact old three-patch source with
only UDP_BUF_SIZE changed to65536, so both comparison variants relay large input in
full. This is a constructed sufficient-buffer control, not the old shipped code.
Three interleaved3000-roundtrip/window4 trials per variant gave median CPU5.161us
versus4.690us for2048byte payloads (-9.1%) and11.756us versus13.155us for48001bytes
(+11.9%). Test peers had sufficient socket buffers; production policy was unchanged.
These local observations neither replace CI nor certify power/maximum throughput.

A separate exact-helper replay executes1000000 large-demand timestamp updates with
one initial allocation,49252 unchanged owned replacement/history bytes, unchanged
cleanup phase and zero owned bytes after cleanup in ASan and optimized modes. Its
controlled clock isolates allocation policy, not clock-call timing on iOS. Repeated
traffic does not append records. Original base slots and descriptors are additional.

Three deliberate source-copy mutations (500B step to1000,300s hold to299,60s cleanup
to61) each fail the original policy assertions. No mutation enters production. A
supplemental -Wextra/-Werror syntax probe was also retained: the exact current source
reports six signed loop comparisons and the old three-patch source reports seven.
All six current sites are preserved old loops. That stricter exploratory command
failed; it is not labeled a clean pass, and the existing required -Wall/-Werror gate
was not weakened. This review did not add unrelated loop reformatting to hide it.

## Original artifacts, source identity and remaining boundaries

| Artifact | SHA-256 |
| --- | --- |
| Final Linux11018901052 |2bb559389f0ab1c0b957374201490382bd5d2928fd1e8cbfc52d4ad1b35510d4|
| Final macOS11018841278 |dfe718d6df052b2640f52d29a1ac7204fb488c840a96f3a6bd0038044b467f27|

Both digests match actual bytes and GitHub metadata, and all ZIP CRCs pass. Each
source archive comment identifies1c5b37d5, all67 file bytes/modes agree and Git tree
reconstruction matchescb394fda. Native archives match243 regular files and30 symlinks
including executable modes. The production C remains blob7c9a16e398873ce4bc4a5f2eb5f68f9261c750a7,
SHA2568d1c54239db15a068ae13c394ca5b71f0109add0d2ea6e26ca1884696e901bf7;
the fourth patch SHA256 is72303ae2d482a7fd8eb87c34219a9247956f508281438411fbcb21538342bd56.
The final closure changes three documentation paths only;64 tested paths are unchanged.

The pre-dynamic9909aa5f owner has57 files. Its original README is preserved exactly
in docs/history/udp-before-dynamic-buffer-20260929.md. All original three patches,
app/project/plist/assets, workflow, baseline framework, shared build/check scripts,
upstream pins, public C headers and four top-level principles remain unchanged.
Only the UDP owner advances; statistics and release still require deliberate
incorporation with their own adapted counter patches and combined verification.

Known fixed-port unknown-peer multi-association independent-close failures remain
observation-only on both hosts/workers1/4. Protocol limits, fragmentation policy,
large socket high-water lifetime, allocator RSS behavior and process scheduling/
suspension remain documented boundaries, not repaired or disproved by this run.
No physical signing/install, SideStore/LiveContainer loading, long background,
energy or device throughput result is claimed. The implemented branch is complete
within its specified code/native/SDK verification scope, not universally certified.
