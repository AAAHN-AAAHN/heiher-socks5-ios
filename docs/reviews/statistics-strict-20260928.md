# Statistics strict audit — 2026-09-28

## Scope and completed status

Review baseline: `ad2c3e00956b825ce3cdcd59e1a5b4f13fad6139` on the actual branch
`feature/traffic-statistics` (there is no separate `feature/statistics` ref).
The requested environment remains physical iOS27/iPadOS27, separately considering
SideStore standalone installation and LiveContainer guest execution. Minimum OS17.2,
Apple SDK compilation, native tests, Simulator and physical devices are not
interchangeable evidence. Background9d87d7cf and all other refs remain unchanged.

Review covers all statistics native patches, the control-peer registry/snapshot API,
raw byte/rate models, unit rounding, the table, its lifecycle task and audit gates.
The original task-io and UDP ownership boundaries are unchanged. Existing complete
results belong to631c8524/run36419879916 and are not borrowed for this candidate.

## Finding and minimal improvement

The prior sample method mutates the SwiftUI-held `clients` value once per returned
native row. This is unnecessary state publication and can repeat dictionary copying
when value storage is shared. It is not an observed native-byte miscount or proof
that SwiftUI renders once per row. The new method builds a local value snapshot,
uses the existing per-IP sampler, then assigns `clients` exactly once. Production
change: one local variable, the same loop writing that variable, one final assignment,
and two explanatory comment lines. No model type, native operation, allocator,
timer, cache, lock, public API, UI layout or additional persistent state is added.

The exact size query/copy, prefix bound, common monotonic timestamp and all per-IP
rates remain unchanged. Copy-on-write leaves earlier value snapshots intact.
Total and client counters are still independent native reads, not an atomic global
transaction; one SwiftUI publication does not eliminate that documented live skew.
The existing original-sample guard is retained by reversing only these explicit
edits and comparing every remaining byte with the original validated method.

## Additional tests and what they do not prove

`sampling_contract.py` embeds the exact production sample method in a test holder.
Only external C calls, monotonic clock and state storage are substituted. It uses
the unchanged production formatter/model and a caller-owned64byte address buffer.
For512 clients over64 intervals it checks98,516 conditions per compiler mode:
registration between query/copy, bounded incomplete snapshots, stable ID ordering,
unknown visibility, first and subsequent rates, counter resets, old-value retention,
quiescent aggregate equality and tab reentry. Each sample publishes client state
once. The exact pre-audit view blob190950bc fails the publication-count condition
with513 setters; it is not claimed to have failed the numerical calculations.
Setter counts in this fixture are not SwiftUI render counts or device benchmarks.

`registry_contract.py` reuses all existing actual-collector assertions and the same
peer/allocation test substitutes. It additionally registers2,048 distinct keys,
exercising hash collisions beyond256 buckets, same normalized peers on different
socket identifiers, all10 selected buffer capacities with untouched-tail canaries,
registration between required-size query and copy, counter-wrap conservation,
and allocation failure while an existing key remains usable. The registry and
server copy API are actual linked production code. Normal and ASan/UBSan variants
run on Linux/macOS; TSan additionally runs on macOS. The latter scopes cover the
included collector, not all native code. Process-lifetime allocations intentionally
remain reachable and leak checking is not used to claim arbitrary-memory bounds.

Both new drivers are invoked by the unchanged parent audit sequence: registry tests
for each native buffered/splice mode, sample-body tests after the existing Swift
models. New tests do not replace prior failure/negative controls, sanitizer scopes,
UI predicates/timeouts, source pin/ownership or clean-worktree/index checks.

## Preserved invariants and review decisions

- Successful destination-side payload I/O is still the only accounting boundary;
  partial success is preserved and client-side delivery failure cannot erase reads.
- Relay context comes from the normalized SOCKS control peer once per relay, not
  packet destinations or a claimed UDP endpoint. IPv4/mapped forms combine; IPv6
  scope is retained. Shared observed IP is not physical device identity.
- Process-lived registry entries and immutable list links survive Stop/Start;
  registration/list capture uses a mutex, byte updates use relaxed atomics. No
  entry is freed while a relay or snapshot may reference it.
- Unattributed fallback does not stop the relay. Buffer count can grow between
  calls; only old fitting rows are copied and a later visible sample gets new rows.
- UInt64 deltas precede conversion; Sum precedes display rounding. SI units through
  PB/Pbps, numeric half-up three-decimal rounding,50% minimum text scale and fixed
  decimal point are preserved. Rounding does not feed back into stored counters.
- Total is always first, IPs remain in registration order, and table labels remain
  In/Out/Sum and Speed/Transferred. Sampling stays at1second only when visible and
  active; native accounting remains independent. Background's0.5second is separate.

No additional reproducible native accounting or state-lifetime defect was identified
in the inspected code and finite tests. This is not proof of every possible
system, adversarial input or infinite history. Registry memory grows with distinct
IPs and is not silently bounded/evicted; changing that would alter the requested
process-lifetime per-IP contract. Extremely high cardinality can still consume
memory/CPU. Numeric input to the app comes from UInt64 counters and monotonic uptime;
the audit does not redefine arbitrary invalid standalone Double arguments as valid
traffic measurements. Long strings and extreme accessibility sizes can truncate at
the scale floor. Unrelated host code in LiveContainer is not coordinated by this
registry or sampler. No new IPA or release integration is requested.

## Completed execution evidence

Tested commit: `bdcb3fbb8cac9ac88ba8c47108977592ecd46a8b`.
Tested tree: `2ea2ff8b213598a0e1222062fa251d9e7f24265c` (91 paths).
Run36425863911, attempt1, completed all four jobs successfully. The final closing
commit changes README, the identical feature specification and this report only;
all other88 paths remain byte/mode-identical to the tested source. This documentation
commit is not counted as another execution.

| Layer | Actual result and scope |
| --- | --- |
| Exact-method sampling | Both compiler modes pass98,516 checks. Original view gives513 setters and fails the intended publication-count control. No claim of513 actual SwiftUI renders or a native miscount. |
| Additional native registry | Linux buffered/splice and macOS buffered pass2,048 extra keys, aliases, ten capacity/canary cases, registration race, wrap conservation and allocation failure. Normal/ASan/UBSan pass; macOS TSan passes for the instrumented collector. |
| Retained tests | Original network/partial-I/O/peer/concurrency and models, including10001 original and20002 TB/PB Decimal references, pass without weaker expectations. Source pin/owner/format/reverse-patch,46 common input cases,26 statistics cases,3 driver and6 reader checks pass. |
| Apple SDK | Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4 swiftlang-6.4.0.34.1, macOS27.0 26A428. Patched C/headers and five production Swift files typecheck for ARM64/iOS17.2 with warnings-as-errors; compiler logs are empty. |
| Actual Simulator | iPhone16, iOS27.0 build24A434, original uninstrumented XCTest1pass/0fail/0skip in88.733seconds. Initial Total, table layout, real IPv4/IPv6 UDP payloads, registered IP order, portrait/landscape and original Server controls pass. runtimeWarnings=[]; cleanup=[]. |
| Local replay | Exact extracted native source passes buffered/splice tests and added normal/ASan/UBSan registry contracts. Models and sample-body fixture pass debug/optimized on Linux/Swift6.2.1. A fresh CI-source extraction repeats sample tests with only the exact old blob supplied for its control; no fake commit history. |
| Physical/products | No iPhone archive/IPA, release integration, physical SideStore/LiveContainer execution, real-device large-cardinality layout, long lock-screen operation or power/throughput comparison. |

Original ZIP hashes/CRCs were verified. Statistics Linux, macOS native and UI source
archives have identical91file bytes/modes and the tested commit comment; a separate
Git-tree reconstruction matches the tree above. Both57file UDP archives retain
owner9909aa5f. Original screenshots were inspected without editing their pixels.
The UI uses two small local network clients; it does not substitute for the512-client
state fixture or measure large-list rendering. The runtime improvement is6added and
2removed lines in one production file, including comments/indentation.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux10971144098 | 643443f36533961d6b27fcf930b9b952cdecda6a0d48bc6eed6ca49016e5e3bf |
| Statistics macOS10971980948 | ce48113eb9582fa92caa578e01dec3fe65a75d984838b60e9c6c2bbd0dd42a48 |
| UDP Linux10970558868 | d566e77d19a46bcee7389976a18c30e516f620cca0e5f794851c0616e54408af |
| UDP macOS10971074297 | f154c20df49d466a0fe1458ef538ae32d192179366add1aa6d21b82e3140288b |

No current CI retry, relaxed assertion, larger timeout, host switch or production
instrumentation was required. Earlier UI/test failures remain recorded in the
preceding README sections, not reclassified by this success. Native memory growth,
nontransactional live counters, finite test coverage,50percent scaling limits and
separate physical target requirements above remain. No additional reproducible
native-accounting or state-lifetime defect was found within this audit's scope.

Primary API background, not project execution evidence:
https://developer.apple.com/documentation/swiftui/state
https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap04.html
