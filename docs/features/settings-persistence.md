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

An explicit choice changes live memory immediately and schedules durability on one serial storage lane. The root sends a direct Stop or Off to its service before calling the store. One file operation may be active and at most one latest ordinary snapshot waits behind it; repeated choices coalesce with the active snapshot as well as an already durable value. There is no queue of every intermediate edit, retry timer or automatic failure loop.

The live value remains current when an ordinary save fails. In particular, a storage failure must not block a user's Stop or Off action. Pending-save state and an error distinguish accepted live intent from durable intent. Retry Save, a repeated explicit choice or an awaited `flush()` can retry failed durability. A process terminated before a successful save can restore the older durable file; immediate live application does not promise immediate crash or power-loss persistence.

Initial loading has explicit `loading`, `ready` and `failed` states. Until a saved snapshot is ready, the root must not apply default values as restored service intent. An explicit pre-load Off remains immediate; an explicit Start is retained and applied with the saved server configuration when loading succeeds. Early edits are merged into that configuration in their acceptance order, including overlapping whole-value and nested paths. Unedited saved fields remain intact. An early choice equal to the loaded file leaves no provisional duplicate save.

Only a genuinely absent settings file permits initialization from the two existing Background preference keys. An inaccessible or corrupt existing file is not treated as an empty first launch and is not silently overwritten. Preference keys are removed only after the first successful JSON write. This is the implementation's present absent-file import behavior, not a separate parallel persistence owner.

Those preference keys are `background.continuousLocation` and `background.silentAudio`. If reading an existing file fails, the store reports the error and retains explicit live edits without writing default settings over that file. Further setting actions or Retry Save attempt loading again; after a successful read they merge retained edits. A validated explicit import can replace the failed file. Corrupt, inaccessible and oversized existing bytes are preserved until such a successful replacement rather than being treated as a fresh installation.

### Import and export

Import asynchronously reads and decodes the entire bounded input, verifies the schema and size and validates the complete server configuration on the storage lane. It retains an exact backup of an existing destination, commits the new file and checks cancellation and the accepted-intent revision again before publishing live state. A rejected or failed commit restores the original bytes, including a prior corrupt or oversized file. Transaction cleanup failure remains visible; it is not reported as successful durability.

Server configuration validation applies even when the imported `serverRunning` is false. Consequently, a saved local draft may be loadable or exportable while import of that same draft is refused until its server fields are valid. Successful import replaces the whole snapshot, including requested services and selected tab; the root applies only the services linked into that composition.

Every accepted explicit setting action, including an unchanged Stop or On, advances the intent revision. A slow import may apply only if its captured revision remains current and the caller has not been cancelled. A newer edit, Stop or import therefore supersedes an older request even if its file has already been written and must be rolled back. One pending import replaces its predecessor; an active operating-system provider call is allowed to finish before the same lane starts another operation.

Export serializes a configuration snapshot. Credentials are plaintext fields in the exported JSON; export is not a password vault or a claim of end-to-end encrypted transfer. Import/export presentation and actual external-provider transfer are distinct verification boundaries.

The export snapshot comes from the current live `settings.value`, not by rereading `settings.json`. Encoding runs off MainActor, then `SettingsDocument` exposes that snapshot to the system file exporter with the default filename `Socks5-settings`. Export is unavailable during initial loading or another export preparation. After an ordinary save failure, an export can contain live changes that are not durable yet. Successful file-picker presentation alone does not prove that a provider saved that file.

## Implementation and ownership

`AppSettings` owns portable schema and encoding. `SettingsStore` is a MainActor ObservableObject with coherent value, error, readiness, pending-save and change metadata. `binding` converts a key path into a read/write binding through the same `set` method, so UI controls do not bypass acceptance and ordering rules. File reads, encoding, atomic replacement, import preparation and preference cleanup execute off MainActor on the serial storage lane. `whenLoaded()` and `flush()` suspend their caller rather than waiting synchronously.

The store explicitly isolates its `ObservableObject` conformance to MainActor. Its concrete Combine publisher and committed state are accessed on that actor; the conformance does not expose the publisher as a nonisolated witness or defer the isolation check to runtime.

`write` creates the application-support directory and atomically writes an encoded snapshot. On iOS it includes complete file protection until first user authentication. Completion advances durable bookkeeping without assigning live values, and starts only the latest waiting snapshot. Preference keys are removed on the same lane after a successful migration write. Neither statistics sampling nor audio health checks write settings.

`importFile` checks cancellation, captures an accepted revision and performs file-provider coordination on the same storage lane as local writes. Security-scoped access is balanced only when acquisition succeeds. The coordinated URL is read through the bounded file-read function, and coordination/read errors propagate. `importData` shares the same validation, commit, rollback and final publication path without provider access.

The active provider call may itself remain blocked; cancelling its consumer or rejecting its late result does not forcibly terminate an operating-system coordination call. New direct service intent and memory updates remain available, but durability on that lane waits for the call to return. No timeout reports fictitious provider termination.

All public state fields are assigned before one object-change notification. A synchronous subscriber can accept a newer edit without the outer publication overwriting it. `Change` identifies an accepted revision and its `user`, `load` or `imported` origin; it is transient metadata outside the JSON schema. The root's later observation is an echo of that change, not a new user command or a reason to replace its origin. Store and audio-service revision numbers belong to separate owners.

Three fixed stamps, `audioChange`, `locationChange` and `serverRunningChange`, reuse existing Change identities. Only an accepted overlapping setting path updates its service stamp; a committed load or import updates all three. A direct root action compares the relevant stamp before and after synchronous service publication. This preserves a newer same-service intent while allowing an unrelated nested edit to coexist with the original Off. No extra generation, counter or history is retained.

`SettingsView` owns transfer presentation, loading/saving status and explicit save retry. The standalone root owns the store and server controller once, observes Change and readiness, and applies server intent only from a ready snapshot. The integrated root additionally owns BackgroundKeepAlive and applies the independent Background choices. The server remains unaware of files, AppSettings and SettingsStore; Background remains unaware of JSON and the native server.

## Design rationale and resource cost

One small atomic JSON file keeps the configuration portable and the consistency boundary explicit. Whole-snapshot import avoids partially applying a malformed file. Revision checks express latest-user-intent priority without keeping a queue of old imports. Keeping live Stop independent of successful disk writes is a safety property, not an instruction to conceal persistence errors.

No-op suppression avoids repeated serialization and filesystem writes for identical values while preserving every accepted explicit intent identity. Bounded reads limit provider input memory; one serial queue, one active operation and one latest pending save bound ordinary write work. There is no packet-time storage, periodic save timer, synchronous main-actor file operation, redundant serialization cache or log of every setting change. Queue execution and provider coordination still consume resources; no physical latency or energy minimum is inferred from this structure.

The finite UInt64 revision never wraps or reuses an identity. Once no further revision can be allocated, the store enters a terminal failed state and rejects new operations, imports and saves. The root refuses new On/Start calls, while direct Off/Stop still reaches the service and is reflected in memory. Old load or write completion cannot clear the terminal failure or restore live On. These last safe Off values have no new revision and are not promised durable; recovery requires a new process. This boundary adds no generation-based continuation mode.

## Verification contract

The model/store suites exercise schema and byte limits, all fields and tabs, malformed/corrupt input, absent-file preference import, inaccessible-file preservation, atomic import ordering, no-op write suppression and explicit retry. Repeated mixed roundtrips compare complete snapshots. File identity, contents and modification metadata establish that unchanged selections do not cause another write.

Coordination tests use the actual store with controlled security-scope, coordinator, file-read and cancellation boundaries. They cover failure before access, acquired-access cleanup, missing coordination results and stale completion after edits or Stop. Historical synchronous-store negative controls retain their exact original test sources and expected failing assertions. These controlled outcomes are not physical cloud-provider trials.

`Tests/Settings/run_checks.py` also invokes `async_storage_check.py`. The actual current store executes blocked load/save/import schedules, same-save coalescing, ordered early edits, coherent synchronous reentry, distinct service-intent stamps, migration failure/retry and finite revision boundaries under both unoptimized and optimized Swift. Each behavioral negative control must compile and fail at its specified assertion; a compiler failure, timeout or unrelated runtime crash is not credited as a detected defect. Linux substitutes only UI/provider types; Apple uses the real Combine publisher.

The Linux publisher boundary retains Combine's nonisolated protocol getter and a non-Sendable publisher type, with subscription and notification confined to MainActor. Removing the store's isolated conformance must separately fail compilation at that exact witness requirement in both optimization modes. These two compiler controls are distinct from the compiled behavioral controls. The host does not model automatic publication by inherited or historical `@Published` owners; current-store reentry uses its own persistent publisher.

Real file/store/controller/Hev tests connect persisted configurations to actual native startup, authentication, cancellation and process restart. Their replies await the explicit durability boundary, after service application. The delayed-completion fixture holds delivery only after a native call has actually returned, allowing a newer real asynchronous import to commit before the older completion is delivered. Both original and current controllers execute with the actual store and native server. An import error must not cause partial service reconfiguration, and a failed ordinary save must not block live Stop.

Simulator tests verify controls, saved intent and tab/setting restoration through actual process relaunches, and separately probe IPv4/IPv6 SOCKS readiness and listener release. File-picker presentation/closing is checked independently from a successful end-to-end transfer through an external provider. SDK compilation, source ownership and the document/frozen-code contract remain separate checks.

Before terminating a process to test durability, the fixture observes the actual Settings loading/saving and Retry Save controls. If an invalid numeric draft leaves its keyboard covering the tab bar, it submits the existing visible Bind IPv4 text field with Return, verifies that every text and secure-field value is unchanged, and requires the real Settings tab to be hittable before tapping it. The Export existence check and save-state wait retain their five-second limits; Start/Stop and native listener deadlines are unchanged. The fixture does not inject a production dismissal control or change a setting to hide the keyboard.

## Operation and limitations

Use the settings-persistence branch for server configuration plus durable storage, or the integrated release for all six features. The feature workflow and `Build/features.json` identify its exact server dependency. Parent server documents are retained unchanged; the current document reference does not change the frozen executable dependency.

Save errors are visible. Before relying on persistence across reinstall, signing identity or container changes, confirm which container will be retained and preserve an explicit export when needed. Exported JSON includes credentials. An unsigned IPA or a remapped Simulator container does not establish real SideStore or LiveContainer data continuity.

The configured minimum is iOS 17.2 and the primary target is physical iOS 27. Physical first-unlock/file-protection states, external provider behavior, power-loss durability, signed installation and guest-host interaction require separate execution evidence. The configured fixed UDP port and its known multiple-unknown-peer limitation are preserved; loading settings does not introduce a dynamic-port fallback.

## Related documents

The [server-control guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/server-control/docs/features/server-control.md) defines validation and native lifecycle. The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) separates file, model, native and physical evidence. `docs/documentation.json` describes the current inherited document set and code-preservation boundary.
