# Persistent settings and JSON file management

## Current final review — 2026-09-26

This branch owns durable configuration and file import/export, not a second server
controller. The review starts at `f7713811c9668c5bb9000b1f9ec32523e5c7bc67`.
No new production defect was reproduced in the reviewed store/model/root/native
boundaries. The changes bind audit inputs and compiled SDK headers to the recorded
revision and inherit the completed server owner `52251e1229cd7b91d15320f93e57fde7ce1142da`.
New run `36202559261` at `28a639148d9fa72c430449c7457862fe8ddc5d12` passed
Linux and Xcode27 on attempt 1; tested tree `61d4eda9ffb6269d0874670e1ab7975776879653`.
Earlier and parent successes were not substituted. This final documentation update
changes only the README/specification pair; the other 83 files remain identical
to the tested 85-file source, including executable modes.

The entire preceding specification is preserved without byte changes in
`docs/history/settings-persistence-before-final-audit-20260926.md`. The server's
previous full specification is inherited in its own dated history file. Original
split history, failures, fixes and evidence remain reachable; old status statements
are not descriptions of the current source. This README and
`docs/features/settings-persistence.md` are identical.

## Target environment, ownership and dependency

The primary target is a physical iOS 27 iPhone, either SideStore standalone or a
LiveContainer guest. These differ in signing, data-container identity, file-provider
permissions and host/guest process state. Configured minimum iOS remains 17.2 and
Bundle ID remains hev.Socks5. A native host test, Foundation test or iPhoneOS SDK
compile does not establish either physical installation path. No installer version,
physical file-provider UI, host mapping or background execution is certified here.

The common main baseline remains `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
Dependency is one-way: main -> server-control -> settings-persistence. The completed
server is an actual merge parent/ancestor, not only copied code or a README label.
All 25 declared server-owned paths, their original bytes/modes and commit/hash
mappings match that owner, including the new input/header verifier and history.
Build/check_ownership.py checks the pinned ancestor and exact mapped contents.
No server implementation is edited independently in the child. The composition's
build script adds the existing store/native tests to the same audit boundaries.

ServerSettings owns the eleven options, validation and YAML; ServerController owns
serialized Start/Stop/reconfiguration. They never reference the store. AppSettings
owns the JSON schema, SettingsStore owns file state, SettingsView owns native file
picker/export UI, and AppRoot owns one store and one server controller plus bindings.
Neither the store nor editor invokes Hev. There are no dependencies on UDP,
statistics, Background or app-icon features. Storing Background preferences does
not implement or start those services in this standalone branch.

The four project principles remain the contract: preserve existing behavior with
minimal simple efficient changes; distinguish the real SideStore/LiveContainer
environments; fully document reasons, scope, costs and limits; and separate source,
mocks, native/SDK/CI, packages, installation and physical execution evidence.

## Schema, defaults and storage contract

JSON schema version 1 retains the nested server object, serverRunning intent,
background.continuousLocation, background.silentAudio and selectedTab. The tab enum
retains statistics/server/background/settings. The standalone UI contains Server
and Settings; unavailable saved tab identifiers display Server without rewriting
the stored value. It preserves interoperability with an integrated root.
Counters, coordinates, errors and transient runtime status are not persisted.

Server defaults remain workers 4, :: listener, TCP1080, empty UDP address, UDP1080,
IPv4 bind0.0.0.0, IPv6 bind::, empty interface/credentials and IPv6-only false.
Server-running and both Background defaults are false. No operating recommendation
from another feature silently changes defaults or user values. Raw UTF-8 server
option equality also governs AppSettings equality, so canonically equivalent but
byte-distinct credentials remain distinct for saving and reconfiguration.

The sole settings file is Application Support/Socks5/settings.json. Encoding and
decoding enforce a 65536-byte maximum. Reads request at most 65537 bytes to detect
oversize; temporary handles close. Writes create the parent directory and use
atomic Data replacement, with completeFileProtectionUntilFirstUserAuthentication
on iOS. This is not a guarantee of power-loss durability or cross-process locking.
The full small document is rewritten only on a changed value or an explicit retry
of a pending failed save; there is no periodic save timer or statistics-triggered I/O.

Launch reads the file directly. Only fileReadNoSuchFile/fileNoSuchFile triggers
first-launch migration. Permission/read/decode/version errors leave safe defaults,
report the error and preserve the original file and old keys. An inaccessible file
is not inferred absent from fileExists. Loading drafts does not promise executable
validity: ServerController still validates before starting the native engine.

Legacy migration reads the two existing Background UserDefaults keys only after
confirmed file absence. Keys are removed only after a successful atomic write,
including a later explicit retry. A failed first save remains pending. Once a valid
JSON file is present it takes precedence over legacy preferences.

## Save, Stop and import ordering

Every explicit setter invalidates older imports, including an unchanged Stop.
The setter computes a complete next value, attempts storage, then applies the value
in memory even on storage failure. Thus Stop/Off cannot be blocked by disk failure.
The failed save reports an error and sets one pending-save flag. Repeating the same
choice retries only while that flag is set; successful persistence clears it.
An already durable identical setter does not rewrite the file.

A disk failure can leave an older saved Start/On until a later explicit save succeeds;
it is not honest to display durable success just because live Stop was applied.
No automatic retry loop or new Save button changes this settled behavior.

importData decodes the entire bounded document, rejects unsupported schema and
validates executable server options before writing. Only after successful write does
it replace live state. A rejected/failed import does not partly apply a new server
or clear existing preferences. Exports contain the configured password in plaintext;
keep them private and import only trusted settings. No Keychain or second file format
is introduced by this audit.

importFile checks cancellation, takes a revision token, and coordinates the security-
scoped read on a detached worker. It reads the coordinator-provided URL, balances
successful scoped access with release, and propagates coordination/read errors.
On return it checks cancellation and the latest revision before importData. Slow
providers must not overwrite a later edit, Stop or newer import. This cancels late
application of results; it cannot forcibly interrupt an OS/provider call already
blocked synchronously. No extra provider thread, polling or timeout is added.

The root applies persisted server intent through the inherited controller and
supplies explicit Start retry. Running remains native invocation state, not a
listen-ready guarantee. Saved intent is not an automatic app relaunch mechanism.
The original editor, FileDocument/fileImporter/fileExporter and messages are preserved.

## Audit findings and minimal corrections

Both native build and SDK entry points formerly allowed working/index differences
while archiving HEAD. They now reject each difference before expensive work and
recheck their applicable final boundary. An index-only staged change is rejected
even when the working file was restored. In BUILD_IPA=0 the tracked input stays
identical; optional packaging's existing generated-framework phase is not mistaken
for committed baseline bytes.

The native build records its commit and hashes of the exact copied hev-main.h and
module.modulemap. SDK entry requires native SUCCESS, the same HEAD and matching
header hashes before Apple tools. Stale output, missing identity/native success or
modified headers fail instead of silently typechecking against unrelated declarations.
Even a documentation-only new revision needs fresh native output before standalone
SDK entry. Native and SDK success markers remain phase-specific, not interchangeable.

The inherited input_integrity_check.py executes the actual old/current entry bodies
in real isolated Git fixtures. Twenty-six cases cover clean/unstaged/staged/index-only
input, stale/missing header identity, changed header/module and missing native success.
The old build body for this composition is separately identified from the server-only
body. Existing six failure-marker controls are preserved. Fixtures stop intentionally
at a downstream failing boundary and are not substituted for actual Hev/Apple runs.
Diagnostics are retained and only applicable success markers are invalidated.

These are provenance checkpoints, not an atomic filesystem snapshot or protection
against malicious rewriting of files plus their attestations. Arbitrary untracked
inputs and external toolchains are outside these checks. Use separate clean full Git
checkouts; do not overlap audits in one workspace. No app runtime, schema, patch,
permission, source pin, baseline framework or signing setting changes in this audit.
Added work is test/tooling CPU and small evidence files, not a new runtime service.
No measured energy, throughput or latency improvement is claimed.

## Verification commands and retained coverage

```sh
BUILD_IPA=0 bash Build/build.sh
# Actual Xcode 27, after native success at the identical commit:
bash Build/check_swift_sdk.sh
python3 Build/record_evidence.py
```

The normal Linux/Xcode27 workflow retains all server tests and repeats them against
this composition. It retains the 209 store assertions (39+116+15+33+6), exact old
import/store/access negative controls, actual JSON/store/controller/Hev tests with
16 records, four old/current delayed-persistence records, file permission boundaries,
source ownership and formatter/reversal checks. Real macOS coordination and Linux
provider type doubles are distinct. Local 209 current-store assertions and both
branches' 26 audit-input cases passed; old full native/SDK badges are not new results.

The inherited server checks include seven scenarios,84 assertions,512 exact model/
YAML parity cases,22 expected old-equality failures; native authentication and active
Stop/restart, active-client and delayed-completion controls, pre-start cancellation,
exact worker body controls and TCP/parser checks. Eight production Swift files are
typechecked against the actual iPhoneOS27 SDK at ARM64/iOS17.2 with warnings-as-errors
and the verified native headers. This is not Simulator/UI, archive or IPA evidence.

Inspect complete job/process exits, source SHA/tree and modes, ZIP digest/CRC, all
manifests and original logs. Final documentation-only changes must leave all executed
non-document inputs identical. Repetitions, synthetic inputs and expected old failures
are not independent physical-device trials or current implementation failures.

## Explicitly unperformed or unchanged

Physical SideStore provisioning/install, LiveContainer guest/container mapping and
host arbitration, native Files/iCloud UI, protected-data timing, power loss/crash
durability, real network permission/VPN/hotspot, lock/suspension/termination and
energy/long-duration tests remain unperformed for this revision. A reinstallation
under a different identity/container need not retain settings. No physical installer
version, full UI/accessibility/keyboard/device matrix or all-provider behavior is
certified. Neither this branch nor server-control supplies Background keep-alive.
Main, unrelated features, release/integrated, the eight-branch count and existing
build7 IPA are unchanged; no refreshed integrated package is claimed.

Primary contracts, not execution evidence:
- https://developer.apple.com/documentation/foundation/nsfilecoordinator/coordinate(readingitemat:options:error:byaccessor:)
- https://developer.apple.com/documentation/swift/task/cancel()
- https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/


## Completed final-review evidence — 2026-09-26

Both jobs in run36202559261 completed on their first attempt. The final candidate
is the actual merge of f7713811 and server52251e12. Remote ancestry and all25 source/
hash/mode mappings match the finalized server, not an earlier owner snapshot.
The server branch has its own successful run36201868398; this persistence run
independently repeats its inherited tests against the current composition.

Each host passed the209 current settings assertions,16 real JSON/store/controller/
Hev records and4 old/current delayed-persistence records. Tests include byte-exact
credential changes,255-byte credentials, actual process relaunch restoring Start,
invalid imports preserving live/disk state, failed writes still stopping Hev, repeated
same Stop committing a pending save, and a new process respecting the saved Stop.
Old imports still fail13 designated postconditions; the previous store fails4 pending-
save and1 inaccessible-file condition as expected. These are negative controls,
not new defects or failing conditions in the current implementation. Filesystem
permission checks are not iOS file-protection or physical file-provider UI tests.

All inherited server suites passed:7 scenarios,84 current assertions,512 parity
cases,22 expected old-model failures,14 native-controller records,40 active Stop/
restarts,12 active-client cases,8 current delayed schedules plus8 original controls,
40 pre-start and100 legacy/prepared cancellations, worker controls and TCP/parser
fixtures. All26 new source/header cases and6 original marker controls passed on
each host. Formatting, native patch reversal, source pins, composition and ownership
checks passed. Counts include repetitions and controlled events, not device trials.

Native and SDK source/index diff logs are empty. Both compiled-header digests and
their commit match the actual SDK input. Xcode27.0 `27A266a` / iPhoneOS SDK27.0
successfully typechecked8 production Swift files at ARM64/iOS17.2 with warnings-as-
errors and a zero-byte diagnostic log. The saved toolchain file does not independently
record Swift compiler version or macOS build; neither is inferred from another run.
Linux skips the Apple-only step. No Simulator/UI test, iPhone archive or IPA was
produced. No limits, postconditions or error paths were weakened to obtain success.
There was no failed workflow attempt in either new final-review run.

| Original artifact | SHA-256 |
| --- | --- |
| Linux10893115547 | 8422dbf84547d24606e2f51cd25071d93278a65a00feb5d6c7a10b2f8fe59398 |
| macOS10892248649 | f02bc15698fba14ed49b0f419241c9bf146ef2f89dfcc1e45488130a92316533 |

Both original ZIPs passed digest/CRC checks. Genuine source comments identify the
tested commit; all85 files, executable modes, full85-entry manifests and reconstructed
trees match. Header attestations and phase-specific success were inspected. Final
README and own specification are identical; their post-test update changes no other
file. Six existing paths changed and three were added relative to the audit input;
the other76 starting files remain unchanged. All app code, schema/defaults, native
patch, root/editor/project/plist, framework and source pins are preserved.

The complete audit patch applies and reverses to the exact85-file final and82-file
original trees. The companion verifier repeats file/tree/hash/header/patch identities,
not native or Apple execution. Local clone was unavailable due to container DNS;
source reconstruction used original connector archives and verified Git objects,
not an invented full clone. Local fixture/setup limits and completed logs remain
separate from remote evidence. The two canonical feature heads are complete within
these executed boundaries; main, unrelated features, release, branch count and old
build7 are unchanged. Physical SideStore/LiveContainer and all unperformed limits
above remain explicit, not replaced by these successful native/SDK results.
