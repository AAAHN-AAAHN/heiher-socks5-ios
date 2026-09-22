# SOCKS5 for iOS - integrated release

This repository retains Heiher's lightweight native SOCKS5 engine and adds five
explicitly owned features for the repository owner's iPhone hotspot/VPN use.
`release/integrated` is the complete application. `main` is the latest verified app + unpatched server combination,
not a byte-identical upstream mirror or the release branch. Read the limitations before exposing a proxy
or relying on iOS background execution. This is an unsigned sideload build.

## Repository layout and feature branches

| Branch | Complete responsibility | Feature prerequisite |
| --- | --- | --- |
| `main` | Latest verified app + unpatched server combination | None |
| `feature/udp-compat` | Both Darwin UDP compatibility repairs | Combined main |
| `feature/traffic-statistics` | TCP/UDP byte measurement, C API, Statistics screen | UDP compatibility |
| `feature/background` | Continuous location, silent audio and recovery, persistent switches | Combined main |
| `feature/settings` | Whole-model JSON, interchange, saved execution/tab state, lifecycle fixes | Combined main |
| `feature/app-icon` | Existing icon asset and catalog | Combined main |
| `release/integrated` | All five features, shared application composition and every feature README | All features |

The feature branches are working applications with their own tests and manifests,
not folders of unapplied patches. Statistics depends on UDP compatibility because
known Darwin failures would otherwise make its UDP measurement incomplete. This
explicit prerequisite is not a claim that every feature branch contains everything.
Background-only and settings-only checkouts do not claim the UDP fixes or statistics.

`docs/branches` contains verbatim copies of every feature branch's root README.
`docs/feature-membership.json` records feature tips and exact module/document hashes.
The final commit has feature tips as ancestors. Feature-specific source modules,
assets, tests and specifications are retained. The final root, target file lists,
permissions and build manifest intentionally compose the features rather than
attempting to run several competing app entry points.

## Implementation specifications

- [UDP compatibility](features/udp-compatibility.md)
- [Traffic statistics, engine and display](features/traffic-statistics.md)
- [Background location and audio](features/background.md)
- [JSON settings and server lifecycle](features/settings-lifecycle.md)
- [App icon](features/app-icon.md)
- [Build, testing, source pins and archival policy](build-and-validation.md)

The original upstream README is preserved at `docs/upstream/README.md` in feature
and release branches. Main documents the combined baseline separately.

## Runtime architecture

```text
Socks5App -> AppRoot
    Statistics/       sampled display; no per-packet Swift calls
    BackgroundKeepAlive/  native controller, view and root event modifier
    Settings/         value model, validation, one JSON store, Files UI
    Server/           desired/current engine invocation lifecycle
    ContentView       original server fields bound to SettingsStore

HevSocks5Server.xcframework (rebuilt from pinned source)
    hev-socks5-server -> hev-socks5-core -> hev-task-system
```

No second SOCKS implementation, injected system-wide hook, Python runtime, custom
socket transport, NetworkExtension VPN, WireGuard inbound server, or packet capture
service has been added. Current engine buffers, I/O, coroutines and routing remain.
Statistics uses successful I/O results instead of duplicating data flow. The root
owns long-lived state independently of the selected tab; the background view no
longer owns unrelated server/statistics/settings objects.

## Exact core patch inventory

| Patch | Repository-relative target | Purpose |
| --- | --- | --- |
| `hev-udp-port-zero.patch` | server `src/hev-socks5-session.c` | Defer invalid initial connect to unknown client port |
| `hev-udp-sockaddr.patch` | core `src/hev-socks5-udp.c` | Normalize AF_INET input and reset receive address capacity |
| `hev-stats-task-io.patch` | task-system I/O header/source | Optional external-side byte observation in existing loop |
| `hev-stats-core.patch` | core misc/TCP/UDP files | Atomic payload counters and wiring |
| `hev-stats-server.patch` | server public API | Expose counts to Swift |
| `hev-server-startup-stop.patch` | server `src/hev-socks5-proxy.c` | Release worker startup waiters on pending Stop |

The first five patches and both Swift statistics files are preserved from the
working unified-settings release. The sixth is a minimal lifecycle repair found
by a new actual native-engine probe during reorganization: Stop before Start with
multiple workers could leave worker threads waiting forever. Setting the existing
SYNC_ABRT bit before the early return fixes that path without another timer or
readiness API. The lifecycle feature documents reproduction and test scope.

## Screen behavior

Tab order is **Statistics, Server, Background, Settings**. The last selected tab is
saved. Statistics shows external-network In/Out rates and totals, plus combined
Total. Units are decimal KB/MB/GB and Kbps/Mbps/Gbps. Payload is counted once, not
both proxy hops. VPN/transport headers and retransmission overhead are not counted.
Out means socket acceptance, not delivery confirmation. Counters last for this
process and survive server restarts, but are not persistent settings.

Server retains all original eleven inputs and default values. Start/Stop intent is
saved. Opening the app reapplies a saved Start even when another tab is selected.
Existing settings.json remains version-compatible. The engine cannot relaunch the
app after termination. Invalid or failed server starts are shown, not retried in a
busy loop. Explicit Start or a changed configuration allows another attempt.

Background contains only Continuous location and Loop silent WAV. The location
manager requests coarse accuracy without polling, preserves state indicators and
discards coordinates. Audio uses the existing 50-ms all-zero PCM WAV, native looping
and mixing. One timer checks healthy playback every two seconds; failed recovery
retries every second without backoff while On. Delivered interruptions, media reset
and route events are handled. Stale callbacks cannot undo explicit Off. No timer
can execute while iOS has suspended or terminated the process.

Settings exports/imports one JSON file including all eleven server fields, desired
Start/Stop, both background choices and the last tab. Imports validate before
applying and may start/stop services immediately. Files reads are coordinated off
MainActor and bounded; writes are atomic and only occur on actual edits. Runtime
metrics never trigger saving. **Exported authentication passwords are plaintext.**
Keep backups private and import only trusted configuration. A storage error is
reported but never prevents an in-memory Stop/Off.

## Review findings and restrained changes

This cleanup is not a speculative performance rewrite. New fixes are limited to:

1. The actual Hev early-cancellation worker hang described above.
2. Remembering a failed server attempt so unrelated tab/foreground events cannot
   keep retrying the same failed configuration; explicit Start still works.
3. Rejecting Unicode YAML newline separators and enforcing a consistent snapshot
   size limit on encode/decode and bounded startup/import reads.
4. Extracting AppRoot and a reusable background view/event modifier so isolated
   feature branches have honest responsibilities rather than hidden dependencies.

Normal-path audio logic, continuous location, the silent asset, UDP repairs,
statistics counters/display and app icon retain the tested design. No new packet
buffer, dynamic history, network polling service or dependency is introduced.
Code brevity is not claimed as a measured CPU or battery improvement.

## Building, verification and artifacts

Use a git checkout and run `bash Build/build.sh` on macOS with Xcode and formatter
18 installed. The same script runs applicable native checks on Linux without
claiming to build iOS there. See the linked build specification for prerequisites.
Each feature is checked on Linux and macOS and archived for iPhone; integrated
verification follows the successful feature builds. Artifacts contain the unsigned
IPA, source ZIP, logs, source/patch identities, SHA256SUMS and dSYM files.

Native tests exercise real Hev sockets, exact data counts, known/unknown peer ports,
concurrent associations and workers, and a real stop-before-start deadline probe.
Swift tests exercise rate calculations, JSON file I/O and controller transitions.
Background and server-controller mocks do not emulate iOS calls or process kills.
The WAV is checked both as raw PCM and using Apple's decoder. Static composition
checks verify module identity, patch inventory, tabs, field bindings and Xcode IDs.

Functional test success is not proof that all future iOS scheduling states or all
possible network inputs are bug-free. No new iPhone energy/throughput benchmark was
performed. The minimal zero-port repair retains first-datagram peer selection, not
a new authentication boundary. Use a trusted hotspot/LAN and appropriate upstream
security; SOCKS5 is not itself encryption. Sideload signing remains the owner's step.

## Historical continuity

Old diagnostic, test, audit and build branch tips are preserved as archive tags
before their old branch names are removed. A history bundle and old-ref manifest
remain available. The earlier historical-main cleanup completed; later main updates use
expected-SHA protection against concurrent edits. The former deployed code remains
recoverable, not silently overwritten. See `docs/history-before-reorganization.txt`
and workflow artifacts for the exact archive map and completion evidence.
