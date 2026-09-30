# Traffic statistics — completed current-main alignment

## Current verification — 2026-09-26

This branch inherits completed UDP `9909aa5f5f41ec87bb3edd976923b2d668e00f08`
and main `75335d201cb1e541bb153e9899badbc11ccf1973` as actual Git ancestors.
Run **36226383235**, attempt 1, executed statistics source
`b4b840d8e8594f9cbc1a08bb69f1c8c5c01210a6`, tree
`940d9193c0e031a93f5e9f31c331efc60d63ed1f`. All four jobs passed: Linux/macOS
UDP prerequisites and Linux/macOS statistics, including the actual Simulator UI.
The prerequisites checked out the completed UDP owner, not the statistics trigger.

The resumed review independently checked the original artifact digests, ZIP CRCs,
source comments, all82 statistics paths/bytes/modes and Git tree, and both57-file
UDP prerequisite archives. This result update changes only this identical README/
docs/features/traffic-statistics.md pair and adds the exact preceding specification
at docs/history/statistics-before-project-alignment-20260926.md. All80 other files
remain the tested bytes/modes. Earlier complete histories and failed attempts remain
unchanged; they are not new execution evidence.

## Target and one-way composition

The primary target is physical iOS27 on an iPhone: SideStore standalone and
LiveContainer guest are different signing, container, permission and shared-process
boundaries. Configured minimum iOS17.2 is not a claim of execution on every version.
Native host, SDK, Simulator, archive/IPA and physical installation are distinct
proof levels. The four original instructions are in docs/top-level-principles.md.

Composition is main -> UDP -> statistics. The17 mapped UDP paths, exact prerequisite
ref and patch prefix agree with the completed owner. This branch does not include
Background, JSON storage, the separate ServerController or custom icon. Standalone
AppRoot starts on Server and offers Statistics/Server tabs. Source/app/submodule pins
and the16-file committed unpatched XCFramework are main's exact bytes. Product
rebuilds apply the three UDP and three statistics patches once. No production Swift,
project/plist, patch, default, resource or framework byte changes in this alignment.

## Preserved native accounting contract

Counters measure successful external-side socket payload I/O. Out is data written
toward external destinations; In is data read from those destinations. TCP accounting
is at side B of the actual splice/buffered path, not at both forwarding ends. Partial
successful I/O is retained before a later error/cancellation, without double counting.
UDP writes count only the successful send prefix; received data is retained even
when the subsequent client forwarding fails. Address/header handling and peer/queue
filtering retain the exact UDP implementation. No protocol policy is rewritten here.

Two atomic UInt64 counters live for the process and are not reset by ordinary server
Stop/Start or screen changes. Queries do not modify totals. A paired read is not an
atomic snapshot of both counters; wraparound and reporting after batch completion
remain finite-counter/timing limitations. This is not radio/billing usage, packet
headers, retransmissions, remote acknowledgement or guaranteed application receipt.
The system resolver's internal DNS traffic is outside this external socket boundary.
No Fake-IP assumption, packet monitor, per-client history or reset/export API is added.

The existing per-success atomic operations have a cost. There is no per-packet
logging, persistent telemetry, heap history, dedicated sampler thread or new network
activity. No zero-overhead, battery or throughput improvement is asserted.

## Swift sampling and UI

Subtract UInt64 counters before conversion to Double. A first sample, nonincreasing
time or decreased counter publishes zero rate and establishes the next baseline.
Sampling uses monotonic systemUptime. The UI adds converted direction totals rather
than overflowing UInt64 addition. Decimal KB/MB/GB and Kbps/Mbps/Gbps retain the
existing two-decimal format and finite Double precision limits.

Sampling runs immediately and once per second only when Statistics is visible and
the scene active. The task is cancelled on exit/inactivity and checked after sleep.
It does not control server lifetime, reset native counters, write settings or keep
the app alive. Native counters may continue outside visible sampling. The screen
and original Server controls/root remain unchanged.

## Audit alignment and retained protections

The exact current-main common build/check code now validates all tracked native
inputs and their index before patch application and after reversal, not only C/H
files or worktree differences. It rejects Python optimization and packages through
a disposable exact-HEAD product copy instead of mutating the committed framework.
The identical46-case exact-old/current input fixture runs in this dedicated audit.

Statistics scope permits only the new main ref and the exact updated UDP prefix
plus the unchanged statistics patch suffix. Runtime freezes,17 owner-file byte
checks and source pins remain. The former old shared-Build freeze is replaced by
comparison to the new main, not by acceptance of arbitrary build modifications.
Existing source/index, cwd, obsolete success/product marker and dual-stack wildcard
port-reservation repairs retain all26 boundary cases. Existing three audit-driver
and six pipe-reader tests remain. These fixtures stop at controlled tool boundaries;
they do not manufacture native/Apple passes. Swift optimized tests are not Python -O.

Input checks are explicit checkpoints, not an adversarial atomic snapshot of
untracked files, external tools or modifications restored between checks. Port
reservation matches the real server's dual-stack wildcard scope, but closing a
reservation before server bind does not eliminate every external port race. Use
clean isolated complete checkouts; historical controls require actual Git objects.

## Actual results for this composition

Linux buffered/splice and macOS buffered each passed20 network executions (10
scenarios repeated twice), eight peer/queue cases,8 writers/800000 counter updates,
real TCP/UDP boundary probes and ASan/UBSan checks. Object symbols identify the actual
I/O mode. macOS also passed TSan on the real counter. The10000-sample Swift model,
six pipe cases,three existing driver cases,26 input cases and46 common cases passed.
C/header9 and production Swift5 typechecks passed at ARM64/iOS17.2 with warnings-as-
errors; diagnostic logs and entry/final source/index logs are empty. Formatter18,
source composition, patches and exact reverse checks passed. Counts include repeats
and controlled probes, not independent physical trials or whole-program sanitizers.

The actual iPhone16 Simulator/iOS27.0 24A434 test passed: one XCTest,0 failures,
0 skips,55.484 seconds of case execution. Portrait/landscape scrolling, native SOCKS
greetings for Start/Stop and tab navigation were checked. Cleanup is []. This does
not cover every live displayed statistic, field, keyboard, Dynamic Type or iPad.
The recorded host is Xcode27.0 27A266a/iPhoneOS27.0, Swift6.4, macOS27.0 26A428.
AppIntents/debugger diagnostics remain in raw logs; not every diagnostic is absent.

| Original artifact | SHA-256 |
| --- | --- |
| UDP Linux10901052120 | 876f96220f5ea130074b4633dca4919388a1606be2f762691ed602f4a3ae1561 |
| UDP macOS10900977134 | 9d6892df8ddcaa3eaad03718fcfc518122984de0e620f288f41c632e32577161 |
| Statistics Linux10900438365 | a50813be1e7771270424e9f245bac37a87da226bbb5df9fd41b3a9e8e40e90d3 |
| Statistics macOS10900503710 | 21f8a58407e15620f8eafa799dc22f4d4aef65de46fa54fe283bd7af3c06e3e2 |

## Commands and retained limits

Run python3 Tests/Statistics/audit.py and, on Xcode27, python3 Tests/Statistics/ui_audit.py.
The workflow first runs the exact completed UDP prerequisite. It creates no iPhone
archive, new XCFramework or IPA. Its Simulator product is separate from a device app.

UDP Listen Port0 remains the recommendation for multiple unknown-client associations;
fixed-port independent-closure restrictions and prior failed observations remain in
the UDP specification. Defaults and saved values are not silently rewritten. Prior
release required-UDP and Background timing failures retain their own unresolved
causes; this separate success does not retroactively resolve them.

Physical SideStore installation, LiveContainer guest/host operation, actual IPv4/IPv6,
VPN/hotspot/Moonlight, lock/suspension, prolonged execution and energy/throughput tests
remain unperformed for this source. The final release must inherit these exact owner
inputs and run its combined product checks rather than borrowing standalone badges.
