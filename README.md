# Integrated SOCKS5 application

## Purpose and scope

The release combines UDP compatibility, payload statistics, server control, settings persistence, background services and the approved application icon. Its purpose is to compose the exact owned implementations without introducing duplicate controllers, a second settings writer or an alternate native engine.

Feature documents describe each module's behavior and tests. This guide describes their interaction and the release's product-validation boundary. Current-parent documentation references are separate from the frozen functional composition, so explanatory work does not replace a tested implementation or silently create a new IPA.

## Functional behavior

### Four-tab application

The tabs are Statistics, Server, Background and Settings. One SettingsStore owns durable configuration. One ServerController owns native server execution. One BackgroundKeepAlive owns independent audio and location intent. Changing the selected tab does not recreate those service owners.

Server Start records running intent and requests an explicit validated start; Stop records stopped intent and applies live shutdown. The root observes the settings snapshot and supplies configuration and requested state to the server. It separately applies the two Background choices. A save failure remains visible and must not block live Stop or Off, although durable intent can remain different until writing succeeds.

The root compares each Background intent with its controller value before applying it, so changing a tab or server field does not manufacture a new audio recovery request. A successful import can change running intent, Background choices and selected tab together; the server controller validates and serializes any replacement, while audio and location keep their own independent gates. The eleven server-configuration controls and Start remain disabled during the owned invocation, even though an import can request a replacement through the root. Stop has its own enabled condition: it remains available while either the controller owns an invocation or the current settings snapshot requests running, including while shutdown is in progress. Disabling configuration editing does not disable Stop.

Statistics observes actual destination-side payload I/O through the native counters. Stop/Start preserves process totals. Visible active sampling updates Total and normalized control-peer IP tables without becoming the owner of server lifetime or durable configuration. Background audio/location can remain enabled while the server is stopped; server requests do not implicitly change those choices.

### Native and resource behavior

The release applies the four UDP patches, three statistics patches and the server startup/stop patch exactly once in their declared order. It retains complete datagrams, strict peer/header/frame handling, the 1,500-byte base with 500-byte growth steps, 300-second demand retention and 60-second cleanup checks. Counter lifetime and IP attribution are independent of temporary buffer lifetime.

The fixed UDP port default and multiple-unknown-peer limitation are deliberately retained. No automatic dynamic-port fallback or new client protocol is introduced. Ordinary payload accounting excludes framing, peeks and uncompleted work. Background keeps its single 0.5-second health/retry policy and original infinitely looping silent WAV. The icon uses its static catalog; it has no runtime state machine.

## Implementation and ownership

`AppRoot` owns the three StateObjects and binds the four tabs to the selected-tab setting. JSON is the sole durable settings owner in release; the standalone Background AppStorage path is not duplicated in the integrated root. `ServerSettings` and `ServerController` do not depend on the settings store. Background does not read JSON or call the native server. Statistics and icon resources do not introduce reverse dependencies into those services.

`Build/features.json` declares native inputs and patch order. `docs/feature-membership.json` preserves the functional file mappings and exact composition exceptions. `docs/documentation.json` owns current-parent document copies and the permitted documentation-validation changes. Each declared feature revision and the shared main remain in actual Git ancestry; content maps do not substitute for that relationship.

The native order is `hev-udp-port-zero.patch`, `hev-udp-sockaddr.patch`, `hev-udp-peer-filter.patch`, `hev-udp-dynamic-buffer.patch`, `hev-stats-task-io.patch`, `hev-stats-core.patch`, `hev-stats-server.patch` and `hev-server-startup-stop.patch`. The shared unpatched XCFramework remains a source-controlled baseline. Product builds link the freshly generated feature framework in a disposable product-source copy instead of modifying the tracked baseline in place.

The port-zero, public statistics wrapper and startup/stop patches target the server repository; address/peer/buffer and core statistics patches target `src/core`; the I/O hook targets `third-part/hev-task-system`. Core statistics owns the aggregate and IP registry, while the server wrapper exposes its rows to Swift. Repository-root ownership and list order are separate requirements: a correct filename at the wrong patch root is not a valid composition.

The network fixture inherited unchanged from Statistics accounts for a peer that has already closed a malformed stream: the client's half-close can return ENOTCONN or ECONNRESET, but the test still requires no forwarded payload and actual EOF/reset. That narrow test boundary does not excuse arbitrary socket failures or alter runtime protocol behavior.

The actual UI test target combines the integrated behavior test, the Background audio test and the full-payload statistics test. Temporary test code is not compiled into the application target. A class-name distinction avoids test symbol collision without changing the underlying assertions.

## Design rationale and resource cost

Composition through one root makes ownership visible and prevents service lifetime from following tab visibility. Keeping persistence, server intent, background recovery and measurement separate avoids duplicated sources of truth. Exact feature mappings allow the release to reuse implementation rather than maintain parallel copies with different behavior.

The release introduces no additional runtime management layer for integration. It still inherits the real costs of its features: datagram sizing and adaptive storage, process-lived IP entries, packet-path atomic updates, visible snapshot/sort work, asynchronous server/AudioSession operations and audio/location scheduling. Buffer release need not immediately reduce RSS, and a fixed health interval is not zero-cost. No universal CPU/RAM minimum or physical battery improvement is asserted.

Source and artifact checks are build-time work. They verify that the product links the declared feature engine and carries correct resources, not that every operating-system or network condition is supported.

## Verification contract

The combined native dispatcher exercises the declared eight-patch engine, not a collection of unrelated feature badges. The statistics executable UDP prerequisite must equal its declared current UDP parent, and release requires the same parent revisions for executable verification and inherited prose. The complete statistics test tree, including the shared malformed-stream half-close handling, is retained by exact file content, mode and staged index. Its original workflow files are retained verbatim in `Build/inherited-workflows/`; these reference copies are not registered as additional GitHub workflows and do not launch duplicate feature jobs. Linux uses buffered and splice paths where applicable; Apple exercises buffered Darwin behavior. Tests require exact successful TCP/UDP accounting, full payload integrity, control-peer attribution, independent communication timeout and safe adaptive-buffer reclamation.

The accounting matrix covers partial I/O, failure and cancellation with enabled, null and existing-entry callback paths. The parent stream-boundary fixture executes on both the statistics seven-patch engine and the release eight-patch engine. A source-inheritance regression runs in the exact statistics-owner worktree so missing test files, stale prerequisite references and an omitted composed execution cannot pass merely because runtime patches are unchanged. Datagram and stream fixtures cover truncation, headers, addresses, queue rejection, short frames and partial sends. Registry/concurrency and Swift sampling tests verify Total/IP boundaries and visibility/cancellation. Actual timed retention must preserve cumulative counters after expanded capacity is reclaimed.

Server and settings tests combine files, value models, the controller and actual native execution. They cover early Stop, configuration replacement, authentication, occupied ports, explicit retry, delayed completion and stale import rejection. Background's source-specific policy tests run in their appropriate exact-owner scope, with byte identity and separate integrated controller/async/host/UI tests connecting them to release.

The package checks require exact generated-framework/source identity, successful source/native/SDK prerequisites and the complete archive-to-IPA payload correspondence. Unix file types and permissions, directories, CRCs, duplicate names, icon catalog/fallbacks, original WAV, actual ARM64 target and executable/dSYM UUID must agree. Source locks, compiled products and signed installations are distinct objects.

The seeded Simulator cases cover original/remapped identity, tabs and durable Start/Stop with actual TCP responses. The three UI cases verify independent audio, server/setting behavior and known large IPv4/IPv6 volumes in the actual Total/IP tables across Stop/Start and orientation. Runtime-warning and cleanup checks remain required. Scrolling and hittability establish access, not simultaneous unoccluded display of every row.

## Operation and limitations

Use a full-history clean checkout. The release commands are `bash Build/build.sh`, then on an Apple host `bash Build/check_swift_sdk.sh`, `python3 Build/verify_release.py`, `python3 Build/simulator_review.py`, `python3 Build/ui_review.py` and `python3 Build/record_evidence.py`. The workflow selects the applicable platform stages; an Apple-only skip on Linux is not an executed check.

For a manual device-product build, the Apple path defaults `BUILD_IPA` to `1`; it can be set explicitly as in the release workflow. Setting `BUILD_IPA=0` skips archive generation. The following product/Simulator checks require that generated product and their source/native prerequisites; they do not build a missing archive implicitly. The delivered product is unsigned input for a signing or import process, not a device installation. Documentation edits neither alter that product nor replace its separately recorded source and hash.

Documentation verification uses `python3 Build/check_documentation.py` and the document-specific regression fixture. Add `--live-parents` to require the declared document parents to match the current remote branch tips; the default check verifies the pinned snapshot reproducibly. It preserves the frozen application, test oracles, build/workflow configuration, defaults and resources. A document-only commit is not a new runtime test or product build. Existing unsigned IPA bytes and their separately recorded source identity remain unchanged by this work.

The configured minimum is iOS 17.2 and the primary physical deployment target is iOS 27. SideStore standalone signing/install/run and LiveContainer guest/shared-host execution require separate records. An unsigned IPA, changed Simulator identifier or SDK compile does not prove either physical route. Permission/file-protection states, external provider transfers, calls/Siri/Bluetooth, VPN/hotspot, suspension, long locked-device operation and device resource measurements remain separate deployment tests.

The fixed-port unknown-peer restriction, independent atomic snapshots, finite counters/display precision and process-lifetime registry are explicit contracts. Persistent On is intent, not guaranteed execution or permission. Finite passing tests do not prove the absence of every possible input, allocator, scheduler or host failure.

## Related documents

Read the [UDP guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/udp-compat/docs/features/udp-compatibility.md), [statistics guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/traffic-statistics/docs/features/traffic-statistics.md), [server guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/server-control/docs/features/server-control.md), [settings guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/settings-persistence/docs/features/settings-persistence.md), [background guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/background/docs/features/background.md) and [icon guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/app-icon/docs/features/app-icon.md). Their exact current parent documents are also included in this checkout. The [shared build guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) describes execution evidence and the [documentation contract](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/documentation.md) defines prose inheritance and code preservation.
