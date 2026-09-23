# Duplicate server/persistence extraction comparison

## Scope and decisions (2026-09-24)

The comparison reads actual committed files, not branch names or earlier summaries.
Canonical server: `68599f96331f3f45e3fa271db02e6ede0fc35d73`.
Canonical persistence: `633c04905ed7ca4acd7272fb040c8d1c66cb38e3`.
Alternate server: `0ab3c33a667cd7fabf6b0683d98c619d2bff169c`.
Alternate persistence: `506156e6a83dcc4d40ce675136d269c1b02fd49d`.
Existing released product: `6ad54bdca195f8ff97db6ac40d3374888c52e314`.

Both alternative branches are coherent, separately checked extractions from the
same audited former Settings implementation; they are not merely empty duplicate
refs. The evidence supports duplicate work, not the internal cause of a ChatGPT
platform failure. No person or process is identified as the cause from commit
metadata alone. Nothing is deleted until the comparison is complete, all compared
histories are reachable, and validation succeeds.

## Product-code comparison

| Area | Actual difference and decision |
| --- | --- |
| Server model and YAML | Same definitions, defaults, validation and generated YAML. The alternative omits one documentation comment. Preserve the canonical model. |
| ServerController | Same state machine; only the argument/local name `settings` versus `configuration` changes. No additional cancellation, restart or error fix exists to import. |
| AppSettings, SettingsStore, SettingsView | Byte-identical between the two persistence branches, including schema v1, revision/cancellation protection, migration cleanup and file handling. No alternate storage improvement is missing. |
| Native startup/stop patch | Exact same bytes, as are the actual lifecycle regression and parser fixtures. Neither fork adds a distinct engine correction. |
| Server UI adapter | Alternate uses desiredRunning + setRunning and invokes server.apply inside the editor. Canonical uses explicit start/stop callbacks supplied by the root. Both are storage-independent; keep the already validated canonical root/action boundary rather than changing runtime behavior to shorten one root. |
| Save-error presentation | Alternate displays the persistence error below the server form in its root. Canonical passes an optional error string to the form. The error exists in both; no data-loss fix is demonstrated by moving its label. Do not alter layout without a requirement or device evidence. |
| Project version | Alternate stores 1.1.0/build 6 in the project. Canonical release supplies these values at archive time. The existing IPA already has 1.1.0/build 6; no supported-OS or installation improvement follows. |

At identical paths, 35 of the union's 66 server files match; 43 of 77 persistence
files match. Counts include README, build/test renames and metadata; they do not
measure different runtime features. Renames are explicitly inspected. Production
settings files are identical even though much of the tree-level diff is textual.

## Useful advantages absorbed

1. Reuse the alternative's native matrix dispatcher in the canonical release,
   translating only the two owner/feature names and adding explicit invocation
   checks. It calls the retained UDP/statistics real test routines on the combined
   patched core instead of copying test logic. This includes six mandatory UDP
   profiles, fixed-unknown limitations as observations, actual sockaddr probes,
   statistics network/counter/partial-I/O cases, sanitizer checks and Darwin counter
   TSan, where supported. Independent branch source gates are not redefined or
   claimed rerun; composition ownership is enforced separately.
2. Select buffered/splice through the actual Makefile option, and verify the compiled
   symbols through the existing statistics audit. The previous small release loop
   assigned labels with CFLAGS; labels alone do not prove the actual mode. Historical
   small-loop results are retained, not retroactively upgraded to this matrix.
3. Run the existing original-store negative control on each integrated release verification
   with persistence. Its 13 expected failed postconditions are expected evidence of
   the old defect; the current 15 postconditions must still all pass.
4. Supplement the existing source ownership checks with the alternative's explicit
   single-scene, allowed background modes, no-BGTask, deployment, identity and
   entitlement declarations. These are source checks, not granted iOS permissions.
5. Capture the patched public C header for iOS 27 type checks without building an
   IPA. This avoids type-checking statistics against the immutable unpatched baseline
   header. Product framework/source pins remain unchanged.

Keep the canonical 512-case old/new YAML/defaults/error parity oracle; it is absent
from the alternative's server test runner. Keep precise owner-file hashes, commit
ancestry and the existing release package/Simulator checks. Do not replace the whole
build system, rename every feature again, or combine both UI adapters.

The native dispatcher in the alternative's historical CI only ran server/persistence
compositions. Its UDP/statistics branches were not exercised by those two feature
runs. The broader combined paths must be executed in the new release checks before
reporting them as validated. Extra time/memory is CI-only; no runtime timer, queue,
state variable, socket, host patch, permission or settings-file format is added.

## Evidence inspected before reconciliation

Alternate server run `35845422082` and persistence run `35846238133` both report
success. Downloaded macOS artifacts `10743036959` and `10743457767` were verified:

- server ZIP SHA-256: `7dbf8a7c3d650dc75d2e9d0e2111e040e407edd64d391a8abe6c2763eee2a53e`
- persistence ZIP SHA-256: `29b553db4d5258756c076733a90fe68bcbf046ab6dedf94c20696a5735c72f02`

All 55/66 committed-source hashes and their reconstructed Git trees match the
respective actual commits. Their original success logs/type checks remain historical
facts about those sources, not new iPhone tests. In this comparison, Linux Swift
reran both server controllers and both persistence suites. Canonical model parity
also passed; the unchanged original-store negative control reproduced its 13 failed
postconditions. No iOS device or simulator was executed during this local comparison.

## Reconciliation contract

Retain feature/server-control and feature/settings-persistence, along with main,
app-icon, background, traffic-statistics, udp-compat and release/integrated: eight
remote branches. Remove only the exact reviewed feature/server-runtime,
feature/config-persistence and superseded feature/settings refs after validation.
Preserve the alternate config history as a merge parent of the canonical release;
its server parent and the old settings history therefore remain reachable as well.
Use an atomic deletion with per-ref exact leases, never a force reset of a feature.
No new audit branch is created. All six canonical feature heads and main stay fixed.
Only release build/test orchestration and its documentation are enhanced; standalone
feature CI and production source are not rewritten.

`Build/verify_duplicate_comparison.py` reproduces the product comparison and checks
that every file under Socks5, Socks5.xcodeproj, Patches and the committed framework
is byte- and mode-identical to the existing release. README, test/build orchestration
and cleanup bookkeeping are the only changes. The current reconciliation marker
selects BUILD_IPA=0: no new app archive or IPA. The prior 1.1.0/build 6 IPA remains
its original artifact from run 35845223338, not an artifact rebuilt from this commit.
Its SHA-256 is `83a270ebd8770ced8e09e383c832e28a3f89f8ea2fc34ba8ceb8d7ff9be58012`.

The prior run's product build/Simulator jobs succeeded but its cleanup job failed
safely on unexpected refs. Do not relabel that whole prior workflow as success.
New validation, deletion and final remote ref results are recorded only after those
operations finish. Physical iOS 27 SideStore/LiveContainer install, permissions,
interruptions, VPN/hotspot/lock timing, native file-provider UI and energy remain
unverified. No SDK or native-host success replaces those tests.
