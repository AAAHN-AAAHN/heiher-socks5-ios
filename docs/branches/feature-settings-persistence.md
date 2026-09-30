# Durable settings, restoration and JSON transfer

## Purpose and scope

This feature gives the application one explicit portable configuration and one durable owner. It preserves edited settings and service intent across process launches, supports JSON import/export and prevents slow file operations from overwriting a more recent user decision.

It inherits server control without making the server depend on storage. Settings are not runtime counters, transient errors or proof that a requested service is running. The integrated root connects durable intent to the existing server and background owners; the store itself does not run those services.

## Functional behavior

### Stored configuration

`AppSettings` contains schema identifier 1, the complete ServerSettings value, `serverRunning`, independent continuous-location and silent-audio choices, and the selected tab. Background choices and running intent default to false; the selected tab defaults to statistics. The server model supplies its own unchanged defaults and validation rules.

The JSON keys are `version`, `server`, `serverRunning`, `background` and `selectedTab`. The nested Background keys are `continuousLocation` and `silentAudio`; the tab values are `statistics`, `server`, `background` and `settings`. This common schema is preserved even in a branch that does not link all those features.

The standalone settings branch renders only Server and Settings. Its selection binding shows Settings only for a saved `settings` value and otherwise shows Server; it does not rewrite a saved `statistics` or `background` value merely to display Server. It preserves Background choices in JSON but owns no Background controller and does not execute those services. The integrated release supplies all four tabs and applies the same stored Background choices to its one controller.

The store reads `Application Support/Socks5/settings.json`. Valid persisted drafts can include server text that is not currently runnable; the server's own configuration validation still controls startup. Runtime counters, service errors and diagnostics are not encoded into this file.

JSON encoding is pretty-printed with sorted keys. Encoded and decoded data must not exceed 65,536 bytes and the decoded schema identifier must match the supported format. Reads request at most 65,537 bytes, making oversize detection possible without reading an unbounded provider file. Standard Codable decoding determines field/type validity; the feature does not claim a separate rejection rule for every unknown JSON key.

### Changes and failures

A changed value is saved as one atomic file replacement. Repeating an unchanged successfully saved value avoids another encode/write. A failed save remains visible and can be explicitly retried with the same selection. No retry timer or background writer loop is introduced.

The live value still changes when an ordinary save fails. In particular, a storage failure must not block a user's Stop or Off action. This can leave live intent different from durable intent until an explicit save succeeds; relaunch reads the durable file, not an unrecorded guarantee of the last UI action.

Only a genuinely absent settings file permits initialization from the two existing Background preference keys. An inaccessible or corrupt existing file is not treated as an empty first launch and is not silently overwritten. Preference keys are removed only after the first successful JSON write. This is the implementation's present absent-file import behavior, not a separate parallel persistence owner.

Those preference keys are `background.continuousLocation` and `background.silentAudio`. If loading an existing file fails, the store retains its initial default live value, with running and Background intent false, and reports a load error while leaving that file untouched. This preservation describes initialization: a subsequent successful explicit setting write or import can replace the file. It is not a promise that a corrupt file is permanently immutable.

### Import and export

Import decodes the entire input, verifies the schema and size and validates the complete server configuration before replacing durable or live settings. The new file is written before the live snapshot is published. Failure before that point leaves the prior file and live value in place.

Server configuration validation applies even when the imported `serverRunning` is false. Consequently, a saved local draft may be loadable or exportable while import of that same draft is refused until its server fields are valid. Successful import replaces the whole snapshot, including requested services and selected tab; the root applies only the services linked into that composition.

Every explicit setting action, including an unchanged Stop, advances the import revision. A slow file read may apply only if its captured revision is still current and the caller has not been cancelled. A newer edit, Stop or import therefore wins over an older pending read.

Export serializes a configuration snapshot. Credentials are plaintext fields in the exported JSON; export is not a password vault or a claim of end-to-end encrypted transfer. Import/export presentation and actual external-provider transfer are distinct verification boundaries.

The export snapshot comes from the current live `settings.value`, not by rereading `settings.json`. After an ordinary save failure, it can therefore contain changes that are not durable yet. `SettingsDocument` exposes JSON to the system file exporter with the default filename `Socks5-settings`; successful file-picker presentation alone does not prove that a provider saved that file.

## Implementation and ownership

`AppSettings` owns portable schema and encoding. `SettingsStore` is a MainActor ObservableObject with one value snapshot, one error message, a file URL, import revision, pending-save state and the optional absent-file preference source. `binding` converts a key path into a read/write binding through the same `set` method, so UI controls do not bypass save and ordering rules.

`write` creates the application-support directory, encodes one snapshot and uses atomic writing. On iOS it includes complete file protection until first user authentication. After success it clears pending-save state and completes preference-key cleanup. Neither statistics sampling nor audio health checks write settings.

`importFile` checks cancellation, captures a new revision and performs file-provider coordination in a detached task. Security-scoped access is balanced only when acquisition succeeds. The coordinated URL is read through the bounded file-read function, and coordination/read errors propagate. On returning to MainActor, cancellation and revision are checked before `importData` can publish the configuration.

The detached provider call may itself remain blocked; cancelling its consumer or rejecting its late result does not forcibly terminate an operating-system coordination call. This ownership distinction prevents stale application without falsely claiming control over a provider's internal progress.

`SettingsView` owns presentation and transfer UI. The standalone root owns the store and server controller once, observes the complete value and applies server intent. The integrated root additionally owns BackgroundKeepAlive and applies the independent Background choices. The server remains unaware of files, AppSettings and SettingsStore; Background remains unaware of JSON and the native server.

## Design rationale and resource cost

One small atomic JSON file keeps the configuration portable and the consistency boundary explicit. Whole-snapshot import avoids partially applying a malformed file. Revision checks express latest-user-intent priority without keeping a queue of old imports. Keeping live Stop independent of successful disk writes is a safety property, not an instruction to conceal persistence errors.

No-op suppression avoids repeated serialization and filesystem writes for identical values. Bounded reads limit input memory. The implementation adds no packet-time storage, periodic save timer, extra writer thread, redundant serialization cache or log of every setting change. Synchronous local encoding/writing still has a cost on MainActor, and provider coordination may wait for system or network work. No physical latency or energy minimum is inferred from these choices.

## Verification contract

The model/store suites exercise schema and byte limits, all fields and tabs, malformed/corrupt input, absent-file preference import, inaccessible-file preservation, atomic import ordering, no-op write suppression and explicit retry. Repeated mixed roundtrips compare complete snapshots. File identity, contents and modification metadata establish that unchanged selections do not cause another write.

Coordination tests use the actual store with controlled security-scope, coordinator, file-read and cancellation boundaries. They cover failure before access, acquired-access cleanup, missing coordination results and stale completion after edits or Stop. These controlled outcomes are not physical cloud-provider trials.

Real file/store/controller/Hev tests connect persisted configurations to actual native startup, authentication, cancellation and restart. Delayed completion tests distinguish an old engine or import result from the latest intent. An import error must not cause partial service reconfiguration, and a failed ordinary save must not block live Stop.

Simulator tests verify controls, saved intent and tab/setting restoration through actual process relaunches, and separately probe IPv4/IPv6 SOCKS readiness and listener release. File-picker presentation/closing is checked independently from a successful end-to-end transfer through an external provider. SDK compilation, source ownership and the document/frozen-code contract remain separate checks.

## Operation and limitations

Use the settings-persistence branch for server configuration plus durable storage, or the integrated release for all six features. The feature workflow and `Build/features.json` identify its exact server dependency. Parent server documents are retained unchanged; the current document reference does not change the frozen executable dependency.

Save errors are visible. Before relying on persistence across reinstall, signing identity or container changes, confirm which container will be retained and preserve an explicit export when needed. Exported JSON includes credentials. An unsigned IPA or a remapped Simulator container does not establish real SideStore or LiveContainer data continuity.

The configured minimum is iOS 17.2 and the primary target is physical iOS 27. Physical first-unlock/file-protection states, external provider behavior, power-loss durability, signed installation and guest-host interaction require separate execution evidence. The configured fixed UDP port and its known multiple-unknown-peer limitation are preserved; loading settings does not introduce a dynamic-port fallback.

## Related documents

The [server-control guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/server-control/docs/features/server-control.md) defines validation and native lifecycle. The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) separates file, model, native and physical evidence. `docs/documentation.json` describes the current inherited document set and code-preservation boundary.
