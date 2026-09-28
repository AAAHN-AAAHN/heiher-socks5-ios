# Statistics strict audit — 2026-09-28

## Scope and candidate status

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
in the inspected code and finite tests so far. This is not proof of every possible
system, adversarial input or infinite history. Registry memory grows with distinct
IPs and is not silently bounded/evicted; changing that would alter the requested
process-lifetime per-IP contract. Extremely high cardinality can still consume
memory/CPU. Numeric input to the app comes from UInt64 counters and monotonic uptime;
the audit does not redefine arbitrary invalid standalone Double arguments as valid
traffic measurements. Long strings and extreme accessibility sizes can truncate at
the scale floor. Unrelated host code in LiveContainer is not coordinated by this
registry or sampler. No new IPA or release integration is requested.

## Execution status

Local extracted-source buffered native tests and both new drivers passed. The
sample-body test passed debug/optimized and rejected the exact previous per-row
publication control as intended. Expanded native contracts passed normal/ASan/UBSan.
These local runs are supplemental and do not pretend to be a full historical Git
checkout or Apple execution. Fresh candidate CI native/SDK/Simulator results must
be recorded before closing the audit. No new real SideStore/LiveContainer run,
physical network/locked-device test or comparative energy/throughput claim is made.

Primary API background, not project execution evidence:
https://developer.apple.com/documentation/swiftui/state
https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap04.html
