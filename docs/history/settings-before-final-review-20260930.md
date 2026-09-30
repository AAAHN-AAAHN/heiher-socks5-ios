# Persistent settings — completed current-main alignment

## Current verification — 2026-09-26

This branch inherits completed server-control
`be4bdd14d46b6bcd35dfad0c4923edda771c6ac6` and main
`75335d201cb1e541bb153e9899badbc11ccf1973` as actual Git ancestors. Both the
composition and membership metadata name the new baseline. Run **36226873958**,
attempt1, executed `ffbeed20b18cb5f9b04c34ac1d10b534bcd06d40`, tree
`f5c96462f0cf289482612fcc097672dd41fd2bd1`. Linux and Xcode27 both passed.

The resumed review independently checked both original artifact digests/CRCs,
source comments,89-file bytes/modes/manifests and Git tree. The result completion
changes only this README and its identical docs/features/settings-persistence.md
and adds the exact preceding README at
`docs/history/settings-before-project-alignment-20260926.md`. All87 other files
remain the tested bytes/modes. The existing server/store and pre-split histories
are unchanged. Earlier results and known limits are not relabeled as this run.

## Target and responsibility

The intended environment is physical iOS27 on an iPhone, separately using SideStore
standalone or LiveContainer guest execution. Signing, container/identity, file
protection, provider access and shared host process state differ. Configured minimum
iOS17.2 is not proof of execution on every supported OS. Native files/host execution,
SDK compilation, Simulator, IPA and physical installation are separate evidence.
The exact four governing principles remain in docs/top-level-principles.md.

The dependency is one-way main -> server-control -> persistence. All26 mapped
server-owned source/test/document inputs are byte-identical to the completed parent.
ServerSettings, ServerController and ContentView do not read JSON or own storage.
One root-owned SettingsStore supplies bindings and intent to one ServerController;
there is no parallel engine or UserDefaults store. Runtime counters/errors are not
portable settings. This branch stores Background preferences but does not contain
or execute Background, UDP/statistics patches or custom icon functionality.

The standalone screen has Server/Settings tabs. Other stored tab values are shown
as Server without silently rewriting the portable value merely to render it.
Integrated use retains the full four-tab enum. Project/plist, server defaults,
schema, app/source/submodule pins, native patch and committed baseline framework
are unchanged from4b57a3b8. The generic product must rebuild the inherited native
patch; the committed unpatched framework does not supply the prepare symbol.

## Preserved file and model contract

Schema1 AppSettings contains all11 ServerSettings options, serverRunning, the two
Background switches and selectedTab. Defaults remain stopped, both Background
switches false and portable selectedTab statistics. Unknown JSON fields are not a
forward-schema migration promise; unsupported version or invalid required types are
rejected by the existing decoder. Import requires an executable server configuration.
A stopped local draft may be saved without becoming executable.

The sole file is Application Support/Socks5/settings.json. JSON is pretty-printed
with sorted keys, limited to65536 bytes. Reads request at most65537 bytes before
decoding; encoded output is bounded too. Parent directories are created as required.
Writes are atomic; iOS requests completeFileProtectionUntilFirstUserAuthentication.
This is not a guarantee of power-loss durability, secure deletion or credentials
being encrypted separately. JSON/export contains authentication plaintext.

Load distinguishes explicit no-such-file from access/unknown/corrupt-file failures.
Only a genuine first launch migrates the two legacy Background keys; those keys are
removed only after a successful new file write, including a later successful retry.
An inaccessible existing file is not treated as absent and does not restore legacy
On over unknown data. Load errors remain visible and preserve the source file.
Startup reads and bounded local writes remain synchronous; no latency guarantee is
made for all storage failures. No polling/debounce/background writer is introduced.

A set request first supersedes pending file imports, even for unchanged Stop. Equal
settings cause no write unless an earlier explicit save is pending. A write failure
retains savePending and a visible error but still applies the live choice: storage
failure cannot prevent Stop/Off. Repeating the same choice can explicitly retry the
pending write without changing options or waiting for a timer. Until a successful
retry, disk may retain older Start/On intent. A clean unchanged choice after a load
error is not an instruction to overwrite an inaccessible existing file.

UTF-8-sensitive ServerSettings equality preserves byte-distinct credentials and raw
drafts without Unicode normalization or serialization for every comparison. No
persistent second representation, per-packet record or service-check disk write is
added. Existing small atomic writes and model comparisons have nonzero cost.

## Import/export ordering and asynchronous boundaries

ImportData decodes and validates the entire file and server options, writes it,
then publishes the new live value. A failed import cannot partially update the file
or live services. ImportFile coordinates on a detached worker, uses the coordinator's
accessor URL and balances acquired security scope with defer. Cancellation and the
monotonic import revision are checked before applying the result. Stop, an edit or
a newer import prevents a slow earlier result from restoring old intent.

An OS/provider operation already blocked inside coordination cannot be forcibly
cancelled by discarding its result. Synchronous init/writes and the unbounded wall
clock of a blocked provider are documented limits. Import/export UI reports errors;
export uses current in-memory settings, which may differ from disk after a failed
save. Users should keep exported credentials private and import trusted files.
Saved Start/On is intent when the app executes, not automatic relaunch or permission
to run while suspended. The store never calls Hev; the root applies the intent through
the existing controller, retaining explicit Start retry and Stop precedence.

## Current-main audit alignment

The inherited common validator checks all tracked native inputs and index before
patching and after reversal, including Makefiles/scripts. Python optimization is
rejected before assertions. The identical46-case exact-old/current fixture is added
without removing server/persistence tests or boundary conditions. Both base_commit
and the separate membership base/source references now identify the same actual
ancestors, rather than relying only on a string in one file.

The existing26 native/SDK input-and-header cases and six success-marker controls
remain. SDK requires native SUCCESS, the same HEAD and matching hashes of hev-main.h
and module.modulemap. Source/index checkpoints remain at entry and completion.
The optional generic packaging path uses an exact-HEAD disposable product copy with
the patched framework instead of changing tracked files, while preserving all
persistence-specific steps. BUILD_IPA=0 in this dedicated workflow means that optional
packaging path was not executed here. These are provenance checkpoints, not an
atomic adversarial filesystem snapshot; untracked inputs, external tools and changes
restored between comparisons are not certified. Extra cost is audit-time work only.

## Inspected execution results

Each host passed all209 current store assertions:39 model/file,116 validation,
15 controlled import/migration,33 persistence and6 access-boundary assertions.
Exact-old controls retain13 import,4 pending-save and1 access failures as expected
negative controls, not failures in the current implementation.

Actual JSON/store/Swift-controller/patched-Hev integration produced16 passing records
and4 old/current delayed records. These include byte-distinct and255-byte credentials,
real process relaunch, invalid import preserving live/disk state, failed saves still
stopping Hev, explicit same-Stop pending retry and restored Stop. All inherited server
model/native suites were rerun on this composition, not borrowed from the parent:
7 scenarios,84 current assertions,512 parity cases,14 native records including40
active Stop/restarts,12 active-client cases and the existing delay/cancellation probes.

The46 common cases,26 input/header cases and six marker controls passed. Baseline,
composition,26 exact owner mappings,formatter and native reverse checks passed;
input/final source/index logs are empty. Xcode27.0 27A266a/iPhoneOS27.0 typechecked
all8 production Swift files at ARM64/iOS17.2 with warnings-as-errors and an empty
diagnostic log. Native header commit/digests match. Compiler/macOS versions absent
from the saved toolchain file are not inferred from another run. Linux did not run
Apple-only stages. Counts include repeats, doubles and expected old failures, not
independent physical trials or iOS provider/protection policy tests.

| Original artifact | SHA-256 |
| --- | --- |
| Linux10900828524 | bcf081b73928dc38821cac364e596c8c0a6ba0fe06d2a92e72fd463fd0678c1f |
| macOS10900613397 | d9f22d7b0fef7a46b01af1f72d90500b6581956cacd10962e64af63fdd306205 |

## Reproduction and remaining work boundaries

Use a complete clean Git checkout. Run BUILD_IPA=0 bash Build/build.sh, then on
Xcode27 bash Build/check_swift_sdk.sh and python3 Build/record_evidence.py.
Historical controls/ancestors require actual Git objects. A source ZIP, offline
integrity verifier or previous pass is not a new native/Apple run. The release must
inherit the exact completed server and persistence owners and verify its combination.

No new Simulator, iPhone archive or IPA was created in this dedicated run. Physical
SideStore/LiveContainer installation or guest/shared-process operation, actual
Files/iCloud/security-scope UI, permission/file-protection timing, crash/power-loss
durability, VPN/hotspot, lock/suspension, long-duration execution and energy remain
unperformed. No new host workaround or runtime policy was introduced to conceal
these boundaries.
