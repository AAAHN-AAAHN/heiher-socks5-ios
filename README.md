# Integrated SOCKS5 for iOS

`release/integrated` composes the current, pinned feature revisions listed in
`docs/feature-membership.json`. This release incorporates the finalized UDP,
statistics, Background, server execution control, persistent settings and app icon.
It does not include the discontinued BGContinuedProcessingTask experiment.

## Eight-branch structure

```
main
  feature/app-icon
  feature/udp-compat
    feature/traffic-statistics
  feature/background
  feature/server-control
    feature/settings-persistence
release/integrated
```

The server layer owns options/validation/YAML, start/stop/reconfiguration and its
native startup-cancel patch. The persistence layer owns JSON schema/storage,
restoration, migration, file import/export and settings UI. It inherits the server
layer without modifying its code. AppRoot is the thin composition boundary; it
routes settings to existing controllers and does not absorb their internals.
History is preserved with explicit merge parents; main and the four other feature
heads are unchanged. No generic lifecycle framework or duplicate server is added.

## Included current behavior

- UDP: exact final port-zero and sockaddr patches, with original operating limits.
- Statistics: exact final counters, sampling/view code and corrected regressions.
- Background: exact final 13 session/four lifecycle signal registry, immediate
  new-event recovery, one-second playback health/retry timer, repeated-error and
  re-entry protection, weak callback identity, Off precedence and location startup
  fixes. Audio remains above Location. Original zero-sample WAV is unchanged.
- Persistent settings: exact final stale/canceled import guard, deferred migration
  cleanup, lossless schema v1/options/tab/intent and bounded atomic storage.
- Server control: extracted validated configuration and unchanged serialized
  engine lifecycle, including native stop-before-start correction.
- Icon: exact final opaque icon asset and metadata.

All six native patches are applied exactly once. No BGTaskScheduler, NetworkExtension,
new permissions, host bundle spoofing or LiveContainer patch is introduced.
The new branch split changes ownership and input boundaries, not the proxy protocol.

## Versions and installation

Target environment: iOS 27.0 physical iPhone via SideStore OR LiveContainer. Minimum
OS stays 17.2; this is not certification of all intervening versions. Release
version is 1.1.0 (build 6), with unchanged `hev.Socks5` Bundle ID and JSON location.
The IPA is an unsigned input to the user's existing signing/import workflow, not
an assertion that iOS runs unsigned apps. This production app does not require the
BGTask Lab-specific Use LiveContainer Bundle ID workaround. Existing installed
container/identity preservation is necessary to retain automatic local restoration;
export JSON before replacing an installation when data preservation is uncertain.

The intended toolchain is Xcode 27 / iPhoneOS SDK 27. Actual toolchain and executed
results are recorded in the CI artifact, not inferred from the configured runner.
SDK build, native host tests, Simulator execution, SideStore installation and
LiveContainer execution are distinct evidence levels. No physical-device signature,
phone interruption, Bluetooth, hotspot/VPN switching, lock-screen or battery test
is claimed unless explicitly recorded. iOS priority/suspension can still stop
callbacks or reject audio activation; retry policy does not override the OS.

## Validation and source provenance

Build/build.sh preserves exact upstream source pins and uses the six declared
patches. Regression groups include server control/model parity, actual native
stop-before-start, settings/import validation, Background state/callback lifetime,
real Combine delivery, WAV decoding, native UDP and buffered/splice statistics
(where supported). Build/check_ownership.py compares inherited feature bytes to
actual pinned Git objects, including extracted server files and audited persistence.
`docs/feature-membership.json` includes owner commits and checksums.

Only the new server-input boundary and app-root binding were adapted. Schema,
credentials, defaults, persisted keys, Background and native I/O algorithms are
unchanged. The server screen is the same editor wrapped in a ScrollView; its
bindings and action closures no longer depend directly on SettingsStore.

Both new feature commits have separate successful Linux/macOS workflows. The
release workflow builds this integrated composition on Linux and Xcode 27. A Simulator check loads each
saved tab, launches the production app, and exercises saved Start and TCP echo.
Results and screenshots will be recorded after actual execution. This paragraph
describes the test plan, not an advance success claim.

Known limits: fixed UDP port with concurrent unknown-client associations retains
the documented limitation; use UDP port 0 for that scenario. Save failure permits
live Stop/Off but can leave older disk intent; imports/exports include plaintext
passwords. UI, provider and background device behavior cannot be certified by host
unit tests. No claimed energy improvement accompanies this structural split.

Keep README and docs/features/integrated.md identical. Update target/tested versions,
exact source/build/run IDs, failed and unexecuted checks, installation scope and
remaining limitations whenever the code or evidence changes. Feature documents
retain their original audited versions; historical evidence is not relabeled.

## Duplicate extraction reconciliation

The alternative server-runtime/config-persistence branches were compared with the
canonical server-control/settings-persistence pair. The execution state machine,
server validator, storage and native cancellation patch contain no additional
runtime fix; retain the canonical product code. Absorb the alternative's broader
native CI matrix, compiled I/O-mode proof, negative import control and configuration
boundary checks while preserving canonical parity/ownership tests.

[Detailed comparison, decisions, source refs and limits](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/release/integrated/docs/reviews/duplicate-branch-comparison.md).
All product files remain exact bytes from release `6ad54bdc`. A commit marked
`[reconcile-duplicates]` runs checks only, skips app/IPA and Simulator creation, and
then removes only the three reviewed obsolete refs with exact leases after checks
pass. The older 1.1.0/build 6 IPA remains tied to run `35845223338`, whose product jobs
succeeded but branch cleanup failed; it is not relabeled as a newly built artifact.
Target iOS 27 + SideStore/LiveContainer and physical-test limitations above remain.
Completed validation and the final remote branch count are recorded after execution.
