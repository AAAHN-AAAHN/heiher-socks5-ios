# Adaptive UDP buffer completion review — 2026-09-29

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
reconstruct the initial tree. The other same-source run36528924538 also concludes
failure; its cause is not assigned solely from that aggregate status.

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

## Execution status

The revised I/O fixture passed local Linux ASan/UBSan and optimized strict-aliasing
execution. Exact-source policy, peer/address/large-network and earlier timer local
replays are supplemental; this archive-based workspace lacks complete historical
Git objects. New complete-history Linux and macOS CI, actual Apple SDK results,
original artifacts and source correspondence remain required before final closure.
Physical SideStore standalone, LiveContainer guest, background survival, energy,
maximum throughput, Simulator and new IPA/release integration are not claimed.
