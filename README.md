# Server execution control — current main

## Completed project alignment — 2026-09-26

This independent branch inherits main75335d201cb1e541bb153e9899badbc11ccf1973 as
an actual ancestor. Both Build/features.json and the separate membership document
name that same baseline. Run36225969482 attempt1 executed
3ba1eb40efd25a0a833b7b3b3ed6c393ddcd8e2e, tree
2e2c96728d88731406cc8e0c0fc2e51d53ad3f4c; Linux and Xcode27 both passed.
The final documentation changes only this mirrored README/specification and adds
an exact copy of the preceding README at
`docs/history/server-control-before-project-alignment-20260926.md`. All other69
files remain the tested bytes/modes; no runtime is changed after verification.
Earlier source/run identities, failures and full contracts are retained in that
history and the existing earlier audit history, not relabeled as this result.

## Target, ownership and established behavior

The intended target is a physical iOS27 iPhone, installed independently through
SideStore or run as a LiveContainer guest. Signing, container/identity, permissions,
process-global engine/signal state and host arbitration differ. Native host tests
and SDK typechecking are not installation, guest-loader or physical background
proof. Configured minimum iOS17.2 is not certification of every intervening OS.
The exact four governing principles remain in docs/top-level-principles.md.

The dependency is one way: main -> server-control -> settings-persistence.
ServerSettings, ServerController and ContentView never read AppSettings, SettingsStore,
UserDefaults or JSON. This branch has no UDP/statistics/Background/icon dependency.
One root-owned MainActor controller owns the blocking invocation independently of
view visibility. The standalone root begins stopped and keeps options in memory;
a downstream root may supply durable settings without creating a second engine.

The existing eleven options and defaults remain: workers4, TCP address::/port1080,
empty UDP address/port1080, IPv4 bind0.0.0.0, IPv6 bind::, empty interface and both
credentials, IPv6-only false. Validation permits workers1-64, TCP1-65535, UDP0-65535;
seven text fields must be single-line, control-free and at most255 UTF-8 bytes.
Authentication is both empty or both present; YAML single-quote escaping is retained.
Invalid drafts may exist while stopped but never start an invalid configuration.
The ten string fields use byte-sensitive UTF-8 equality and the Boolean normal
equality. Canonically equivalent strings with different credential bytes remain
different. No normalization, duplicate storage, hash cache or JSON comparison is added.

Current/desired/attempted values serialize calls. Configuration changes or Stop
request quit once. A new invocation begins only after the prior call returns and
its actor completion is processed. Latest Stop cancels queued replacement. Repeated
apply does not automatically retry invalid/exited work; explicit Start, changed
options or completed Stop/Start may retry. Running is invocation state, not proof
of listen readiness. Unexpected native exit remains visible; worker completion
retains the controller. Independent concurrent engines in one process are unsupported.

The unchanged single native patch sets SYNC_ABRT on early pre-start Stop, checks
worker run before and after I/O yield, and exposes the idle prepare boundary that
clears only obsolete SYNC_STOP from a prior invocation. Prepare occurs after
validation and before dispatch; a later Stop remains authoritative. Legacy C callers
retain behavior. No polling, added native API, timer, runtime queue, new permission,
logging, host change or automatic retry policy is introduced in this alignment.

App/server/submodule pins and the committed16-file unpatched framework remain main's
exact bytes. Products must rebuild the existing patch for the prepare symbol before
linking. Project/plist, app/controller/defaults and resources are unchanged from
52251e12. Native signal/loader and LiveContainer host interactions are not certified
by tests in an independent host process. Cost remains the existing comparisons,
state and worker dispatch; no CPU, latency or energy improvement is measured.

## Audit changes, exact scope and cost

Main's validator now checks all tracked native inputs, including Makefiles/scripts
and the index, before patch application and after exact reversal. It no longer
checks only C/H files or only worktree differences. Python optimization is rejected
before assertion-based checks. The identical common46-case regression suite uses
real isolated Git fixtures and exact-old/current implementations.

The server build preserves its26 native/header entry cases and six old-success
controls, and adds the common suite. The existing native SUCCESS and same-HEAD
SHA-256 identities for hev-main.h/module.modulemap remain mandatory before SDK work.
Missing, stale or modified headers are rejected. Root worktree/index checks occur
at entry and final boundaries. The optional generic product path now installs the
rebuilt framework only into a disposable exact-HEAD copy and clears only its owned
previous package directory/archive. It does not overwrite the tracked baseline.

The first alignment b8ab6c1e passed run36225295956, but its separate membership
metadata still referred to old main. Both metadata references were then corrected
without changing runtime/tests and the complete source was retested in36225969482.
That first pass is not substituted for the corrected metadata's final execution.
Historical fixture source SHAs are deliberately retained; they are negative-control
identities, not stale production dependencies.

The checks-only workflow uses BUILD_IPA=0. Thus this new run did not execute the
optional standalone packaging path. Main's analogous unpatched packaging passed in
its own run; this branch's changed script path was reviewed, not falsely described
as a new server IPA. Audit cost is bounded Git/hash/fixture work and evidence storage,
not new production objects or wakeups. These are checkpoint comparisons, not an
adversarial atomic snapshot of untracked input, toolchains or changes restored
between comparisons. Use clean, separate, complete checkouts.

## Inspected current results

Both hosts passed7 server scenarios,84 current revalidation assertions,512 original
configuration/validation/YAML parity cases and22 expected old equality failures.
Actual Swift controller plus patched Hev produced14 records, including byte-distinct
and255-byte credentials and40 active Stop/restarts. Twelve active-client cases,
eight current delayed schedules with exact-old controls,40 original pre-start and
100 legacy/prepared cancellations, worker wait controls, TCP echo/parser, formatter,
source composition/ownership and exact native reversal all passed.

All46 common cases,26 native/header entry cases and six marker controls passed on
both hosts. Input/final worktree/index logs are empty. Five production Swift files
passed ARM64/iOS17.2 warnings-as-errors typechecking with an empty diagnostic log.
The actual native headers match their same-revision recorded digests. The saved
Apple toolchain records Xcode27.0 27A266a and iPhoneOS27.0; compiler/macOS build values
absent from that file are not inferred from another run. Linux did not run Apple
checks. Counts include repeats and expected old failures, not device trials.

| Original final artifact | SHA-256 |
| --- | --- |
| Linux10900532603 | 43f83f159d057a483a06bb099da7fa2e069cb09ac3e9fd37009e898434eae6fb |
| macOS10901051463 | 6c9d17c078384b8afabf6b46e2e917fc450e01330b4aba61ce55abafebbf5688 |

Both original ZIP digests/CRCs, genuine source comments, all71 paths/bytes/modes,
complete source manifests and tree match the final tested commit. No failed attempt
or rerun was needed for either source run. The two earlier alignment artifacts are
retained separately. A later documentation-only HEAD is not a second test run.

## Reproduction and explicit limits

```sh
BUILD_IPA=0 bash Build/build.sh
# On Xcode27, after native success at the same HEAD:
bash Build/check_swift_sdk.sh
python3 Build/record_evidence.py
```

Use full Git history for exact controls and ancestor checks; a snapshot alone cannot
provide it. Downstream settings must inherit this completed owner and exact mapped
source/test/document inputs, and release must revalidate the combined composition.
Physical SideStore signing/install, LiveContainer loading/shared-process behavior,
actual permission UI, VPN/hotspot, calls/Bluetooth, lock/suspend/termination, prolonged
execution, crash/power-loss and energy are unperformed. Saved Start is intent, not
auto-relaunch or an override of OS scheduling. No ordinary archive/IPA or Simulator
execution was performed by this dedicated no-IPA verification.
