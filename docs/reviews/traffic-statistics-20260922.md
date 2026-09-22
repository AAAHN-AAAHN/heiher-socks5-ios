# Traffic statistics: focused final review, 2026-09-22

## Scope and preservation boundaries

Reviewed start: `d34e49478d7e061b8824e9f431b40998db25f8b2`.
Main baseline: `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
Frozen UDP dependency: `ae466dab1a394af0c83f3dc36e51755f25f91910`.
Release to leave unchanged: `b59e3f1b61ae342a944d96f0da24b1908c2b3eac`.

The owner retained the existing successful-external-socket I/O scope and requested
review only of statistics-owned changes. The starting full diff against main has
24 paths: 14 statistics-owned paths and ten verbatim dependency paths. No UDP code,
test, audit workflow, README, limitation, or operating recommendation is rewritten.
The Xcode project is a mixed integration file: its statistics source registration
is examined separately from the inherited local-network/single-scene metadata.
The audit's inventory.json lists the exact final diff and dependency hashes.

## Findings and decisions

### Runtime accounting: retained

The actual C patches were applied to their locked repositories and examined within
full caller/callee context. TCP accounts successful side-B reads/writes before
loop yield/exit, including a read followed by a failed client write. Null transfer
callbacks keep the legacy API behavior with the same implementation. UDP accounts
only successful external send-prefix entries and counts external receives before
client delivery. The system wrapper's batch-return delay remains part of the
published contract. A missing partial-success syscall timestamp is not interpreted
as a reason to replace the I/O layer or add new traffic classes.

No runtime defect requiring a change to these nine C/header files or two Swift
statistics files was identified within this scope. The three statistics patch
files remain exactly those from the reviewed start (net 97 C/header lines), as do
all five app Swift sources, their Xcode target, five total patches, common Build
files and committed framework. This is not a universal absence-of-defects proof.
Known unmodified Server/UDP behavior and operating-system constraints stay separate.

### Verification defect: mislabeled Linux path could mask missing coverage

The shared build script used empty CFLAGS for a run named buffered. The pinned
HevTaskSystem configs.mk defaults ENABLE_IO_SPLICE_SYSCALL to 1 and appends that
define separately. The first run's name is therefore not evidence of a buffered
server. New native audit invocations set the actual Make variable to 0 or 1 and
check the I/O object's undefined symbols, with clean rebuilds. This corrects the
statistics review's evidence rather than editing main's shared build files.

The same historical distinction applies to older independent probes: their compile
flags may genuinely select a different helper path even when the server build did
not. No historical pass count is retroactively presented as new verified coverage.

### Test robustness: bounded startup and failure cleanup

The old live test host's first stdout.readline() had no deadline before cleanup was
registered. If the test child never reported readiness, a nominal five-second
later query timeout did not help. The regression harness now bounds that first
read, closes the child when startup fails, validates the complete stats row, and
sets a receive timeout on its asymmetric TCP endpoint. Optimized Python assertion
removal is rejected. These are test-only changes, not server timeouts or new app
work. The native host file is retained; the enclosing driver adds process deadlines.

### Documentation: complete and clarify the actual contract

The old feature specification was substantially correct but did not fully explain
system DNS delegation versus relayed DNS, payload-internal HTTP/TLS/QUIC overhead,
UDP batch reporting time, finite UInt64/Double behavior, and the exact inherited
UDP files or standalone audit restrictions. Root README and feature specification
are now identical, with a per-file inventory, exact patch/function ownership,
accounting semantics, data exclusions, architecture/efficiency reasons, native
and Swift tests, limitations and reproduction commands. No excluded DNS byte count
is added and no resolver is changed. The image/UI definition stays unchanged.

## Current reproducible verification

Use the workflow at this commit or `python3 Tests/Statistics/audit.py` in a clean
checkout. The actual tested commit is recorded in tested-commit.txt; only matching
SUCCESS.txt and logs constitute a completed run. The audit performs:

1. Exact baseline/source/dependency checks and preservation of runtime files.
2. All nine statistics C/header formatter checks and reversible patch application.
3. Real native statistics scenarios twice per confirmed I/O mode: Linux buffered,
   Linux splice, macOS buffered. Ten scenarios per run include asymmetric TCP,
   IPv4/IPv6 UDP, one-way UDP, header exclusion, concurrency, idle and restart.
4. Real counters under eight concurrent writers (800,000 updates), with public
   getter reads; also production-counter TSan on macOS.
5. TCP actual-source probes: partial write, EAGAIN, EOF, EPIPE, ECONNRESET, disabled
   accounting and (buffered helper) callback-before-cancellation / legacy calls.
6. UDP actual-forwarder probes: zero/failed/partial/full send results, poison in the
   unsent suffix, failed external receives, bind failure, and external In surviving
   partial or failed client delivery. These do not re-review peer normalization.
7. Production Swift model checks with 10,000 generated finite samples, large UInt64
   deltas, zero/backward finite intervals, idle, re-entry and decimal formatting.
8. iOS ARM64 C/header syntax and actual Swift source type checking with the patched
   public header; project plist lint. No archive, linking or distribution build.

Sanitizers instrument the included production translation units, not every support
library or the entire iOS process. The tests do not measure phone-call recovery,
hotspot/VPN routing, iPhone battery consumption, UI transitions or maximum throughput.
No 'zero overhead' or 'absolute optimal implementation' claim is inferred from them.

## Final criteria

| Requested criterion | Disposition |
| --- | --- |
| Minimal, concise, resource-efficient runtime | Preserve existing paths, two fixed counters and display-only sampling; no new runtime code. |
| Standard style / natural integration | Keep upstream GNU C conventions and verified formatter, existing four-space Swift and native APIs. Test probes are kept separate from application resources. |
| Residual errors and omissions | No scoped runtime correction identified; correct test coverage/timeout weaknesses and explicitly document finite/scheduling/dependency limits. |
| Core purpose achieved without expansion | Maintain single-count external I/O and process lifetime; no packet/OS-wire or system-DNS accounting expansion. |
| Complete implementation specification | Full independent-path inventory, rationale, semantics, resource tradeoffs, test meaning and inherited UDP boundary. |

Only feature/traffic-statistics may move. Main, UDP, other feature branches and
release remain out of scope. No IPA or framework build is authorized by this review.
A final completion report must distinguish actual matching CI results from this
reproducible test specification and must recheck the remote branch tips.
