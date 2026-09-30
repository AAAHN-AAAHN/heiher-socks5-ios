# Release submission recheck — 2026-09-30

## Scope and unchanged baseline

This additional submission review starts at release
`7eb2c7ec1427291a0f2ed1e6a79219dc7c4de240`, tree
`f0e9068433e7af7725ebc9c664bd903c947359ff`. The preceding final review and
run36705838060 remain historical evidence for their own executed source. A fresh
full release workflow is required for the new review checkpoint; it must not be
reported complete until both original artifacts and their source/product results
have been inspected.

No production, test, workflow, package-helper, resource, project, dependency or
configuration change is proposed by this checkpoint. All twelve production Swift
files and eight native patches are retained. The 177 exact owner mappings and
main/six-feature/previous-release ancestry remain binding. This is intentionally
a documentation-only checkpoint: adding more runtime or test machinery without a
reproduced defect would not improve the established implementation.

The user's decision to retain fixed UDP port/multiple unknown-peer behavior remains
binding. No fallback, port-default change, client change or experimental patch is
included. The configured minimum is iOS17.2; the primary intended deployments are
physical iOS27 SideStore standalone and LiveContainer guest. They are separate from
host tests, SDK checks, archive/unsigned IPA and Simulator evidence.

## Review matrix

| Area | Source review and required execution evidence |
| --- | --- |
| Composition and root | One SettingsStore/ServerController/BackgroundKeepAlive; four existing tabs; JSON as sole durable owner; byte-exact owner, root and platform mappings; genuine ancestry and clean tracked source/index. |
| Server and persistence | Byte-exact validation/credentials/YAML; serialized current/desired/attempted server intents; Stop on save failure; atomic whole-file persistence; bounded reads; stale import/cancellation protection; no-op write avoidance and explicit retry. Existing model, delayed-completion, file/native and UI tests remain required. |
| UDP and accounting | Eight ordered patches; complete datagrams; header/peer rejection; partial TCP framing; successful destination read/write accounting across later failure; correct Total/IP attribution; 1500/500/300s/60s memory policy and independent idle timeout. Existing sanitizer, optimized, socket and actual timed tests remain required. |
| Statistics view | Process-lived native buckets; no packet-time registry lock; aggregate/IP samples and pre-rounding sums; one visible/active sampling task; cancellation when hidden. Existing real sampler, native concurrency and full-payload UI tests remain required. |
| Background | Existing exclusive session/preparation transitions, Off priority, weak/stale callback rejection, retained intent and one 0.5s deadline; independent coarse location without coordinate history. Exact owner policy tests and separate integrated controller/host/UI tests remain distinct. |
| Icon and packaging | Approved original image/WAV and project membership; exact generated-framework handoff; full IPA payload bytes, Unix types/modes, directories, duplicate/CRC checks; actual ARM64 target, dSYM UUID and native definitions. Original negative controls remain mandatory. |
| Resource cost | No added application work; preserve bounded/reused payload allocation, packet-path atomics and visible sampling. Existing process-lived IP memory, sorting/snapshot work, sizing syscalls and audio/location activity are acknowledged costs, not measured physical minima. |

Every tracked path will be included in the content/mode inventory; source-language
syntax and project membership checks supplement manual runtime/patch review. Reading
or hashing a file is not a substitute for executing its behavior. Historical reports,
platform binaries and test fixtures are classified separately from app source; their
presence does not imply every archived historical scenario was re-executed.

## Completion criteria and limits

Use the existing unchanged workflow for Linux buffered/splice and Apple buffered,
all source/owner/input/package gates, real twelve-file iPhoneOS SDK check, actual
ARM64 archive/IPA, ten seeded Simulator cases and three integrated UI cases. Preserve
all assertions, warnings-as-errors, sanitizer/formatter settings, original deadlines,
expected old-code failures and cleanup checks. Record any failure honestly; no old
badge, source-only review or local replay substitutes for the combined workflow.

Independently inspect original artifact digests/CRCs, Git history, source comments,
all file bytes/modes, product identity and saved execution results. Verify the final
published documents after any docs-only closure and distinguish the tested source
from its later documentation child. Main, all feature heads and prior products/tags
must remain unchanged. A new archive of the same build10 runtime is not a new
functional version and must not overwrite the earlier IPA.

Physical SideStore signing/install/run, LiveContainer shared-host execution, actual
location/file permissions/providers, calls/Siri/Bluetooth, long lock/background
survival, power loss and device CPU/RAM/energy/throughput remain unperformed unless
actual corresponding evidence is obtained. Existing fixed-port UDP, independent
atomic snapshot, finite counter/display and process-lifetime registry limits remain.
The final assessment must describe executed coverage and any unresolved observation;
finite tests cannot establish an unconditional absence of all possible defects.
