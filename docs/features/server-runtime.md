# SOCKS5 for iOS: server execution management

`feature/server-runtime` owns server configuration and execution, independently of
permanent settings storage. Its only feature dependency is the immutable `main`.
`feature/config-persistence` adds durable options and file management on this branch.
For the full app use `release/integrated`.

## Responsibility and exclusions

The branch owns `ServerSettings`, validation and Hev YAML generation,
`ServerController`, the reusable Server form, and the native startup-cancellation
patch. Its complete standalone app holds form values and Start/Stop intent in memory;
relaunch restores defaults and remains stopped. It neither writes JSON nor imports,
exports or migrates a configuration file. It includes no Audio/Location keep-alive,
statistics or custom icon.

`ServerController.apply(configuration, running:retry:)` accepts only server input and
execution intent. It has no dependency on AppSettings, SettingsStore, tabs, background
settings, UserDefaults or a storage path. The old state machine is preserved: only
one blocking engine invocation at a time; changed running settings stop the previous
call before starting the replacement; ordinary updates do not repeatedly launch a
failed configuration. Explicit Start or a completed Stop/Start can retry.
Status describes the invocation, not proof that a particular network interface is
listening. The native engine still determines interface/address availability.

The form receives a configuration Binding and execution callbacks from its root.
In this branch they update memory; in the persistence composition they update the
stored model. This reuses the same fields and validation without copying a second
server form or making the controller depend on disk storage. The root owns controller
lifetime; changing tabs in a composition does not destroy the engine owner.

## Preserved configuration contract

All eleven fields and their defaults are unchanged: workers 4; listen address `::`;
TCP and UDP port 1080; optional UDP address/interface empty; IPv4 bind `0.0.0.0`;
IPv6 bind `::`; empty credentials; IPv6-only false. Workers are 1-64, TCP port 1-65535,
UDP port 0-65535. The seven text fields accept at most 255 UTF-8 bytes, matching the
native buffers. Control/newline input is rejected, both credentials must be supplied
or both empty, and quotes are escaped in YAML. The value remains Codable for consumers;
Codable support itself does not read/write a file.

Configuration errors are `ServerConfigurationError`; persistence errors are not
part of this module. The same error messages and YAML content are preserved. Invalid
drafts can be edited in the form but cannot execute. No new auto-retry policy,
readiness polling, socket interception or engine implementation is introduced.

`Patches/hev-server-startup-stop.patch` remains byte-identical to the settings audit:
mark SYNC_ABRT before returning from a pending Stop so waiting workers can terminate.
Its one- and four-worker native cancellation regression tests belong here.

## Build, tests and environment

Run `bash Build/build.sh --checks-only` for source ownership, Swift runtime tests,
actual pinned native lifecycle/TCP/YAML tests, and iOS 27 SDK type checking on macOS.
The normal workflow checks this branch on Linux and Xcode 27 without producing an IPA.
The release workflow builds the full IPA instead. Shared build helpers now understand
`server-runtime` and `config-persistence` as separate declared features; this does not
modify main's committed engine, binary framework or source pins.

| Item | Scope |
| --- | --- |
| Minimum deployment target | iOS 17.2, unchanged; not every OS between 17.2 and 27 has been tested. |
| Intended environment | Physical iOS 27.0, SideStore independent installation or LiveContainer guest execution. |
| Installed identity | Existing `hev.Socks5` input; installer/host may remap identity. No hard-coded account suffix or app-group/host change. |
| Local checks | The migrated seven controller scenarios passed without importing persistence code. |
| iOS validation | Recorded below only after CI evidence is downloaded. |
| Device limitations | No actual SideStore/LiveContainer installation, protected-device startup, VPN/hotspot/lock-screen or energy certification. |

## Extraction and ownership evidence

Source implementation was extracted from former `feature/settings` commit
`16689f780f3e0e0c9344397273528697f197c9e5`; main is
`d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`. The original settings history is preserved
by the dependent branch's merge parent. Only the controller input signature and
configuration-error type name change; the runtime state machine and YAML rules do
not. `Build/verify_split.py` compares their reconstructed bodies with that source.
The storage-independent form is reused byte-for-byte by dependent compositions.

This is a dependency separation, not a performance optimization. It adds no timer,
thread, network work, telemetry or second settings store. Actual energy and memory
changes are unmeasured. Existing regression results remain historical; they do not
substitute for a new combined build.

README maintenance: this file and `docs/features/server-runtime.md` remain identical.
Record target/minimum/actually-tested OS separately, commit/run, installer/host version
when known, executed/failed/not-run scope, reasons, costs and remaining limitations.
