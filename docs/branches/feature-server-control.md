# Server configuration and serialized lifecycle control

## Purpose and scope

This feature gives the application explicit, validated server configuration and predictable Start/Stop behavior. A single controller owns the blocking native engine independently of the visible tab. Configuration, lifecycle control and persistence remain separate responsibilities so the same server implementation can be used by a standalone feature or a settings-enabled release.

The feature consists of `ServerSettings`, `ServerController`, the existing configuration editor and the native startup/stop patch. It does not add a storage layer, background service, traffic sampler or a second server instance.

## Functional behavior

### Configuration

The configuration exposes workers, TCP listen address/port, UDP listen address/port, outgoing IPv4/IPv6 bind addresses, bind interface, username/password and IPv6-only listening. Values are edited as strings where appropriate so a partially entered value can remain visible without being treated as a valid running configuration.

Defaults are four workers, TCP address `::` and port `1080`, an empty UDP listen address and UDP port `1080`, outgoing bind addresses `0.0.0.0` and `::`, empty bind interface and credentials, and IPv6-only disabled. The UDP default is intentionally retained; unknown-peer requests are not automatically assigned a different configured policy.

Validation accepts one through 64 workers, TCP ports one through 65,535 and UDP ports zero through 65,535. The seven address, interface and authentication strings must be YAML-printable single-line text, contain no control characters and fit within 255 UTF-8 bytes. Worker and port strings instead pass integer conversion and their numeric ranges. Authentication requires both fields or neither. YAML strings are single-quoted with embedded apostrophes doubled. Equality compares UTF-8 byte sequences so canonically equivalent but byte-distinct credentials and drafts are not silently treated as identical native input.

The editor has ten text fields and one IPv6-only toggle. All eleven controls and Start are disabled while `server.isRunning` is true; Stop is enabled by the root while an invocation or requested-running intent remains. Configuration replacement during an active invocation is a controller capability used by programmatic updates and, in a settings-enabled composition, import; the editor itself is not editable during that invocation.

The Swift validation is not an address resolver or a bind/readiness probe. Address syntax, local interface availability, socket permissions and port occupation can still cause native setup to fail after the value passes Swift validation. The blank authentication defaults mean the generated configuration does not request username/password authentication; a masked password field is display protection, not a new transport-encryption layer.

### Start, replacement and Stop

Start expresses a desired configuration. If the engine already owns that same configuration, duplicate requests do not create another invocation. If the desired configuration differs, the controller requests shutdown once and waits for the current invocation to return before considering a replacement.

Stop clears the desired running configuration, overrides a pending replacement and allows the owned native invocation to finish. Repeated Stop does not start new work. An explicit Start can retry a failed configuration or an exited engine. An unchanged failed intent is not retried indefinitely by view updates.

`Running` means the controller owns an active native invocation. It is not a promise that the socket has completed binding or is already reachable. Validation errors and native exit status remain visible. Network-readiness tests use a socket response rather than treating the status label as a readiness signal.

## Implementation and ownership

`ServerSettings` is a Codable, Equatable value model that owns validation and YAML generation but no file, settings-store or background dependency. The editor binds to this value and receives explicit start/stop actions. This keeps presentation, durable settings and native lifecycle independently testable.

`ServerController` is MainActor-owned. `current` identifies the running invocation, `desired` the latest requested configuration, `stopping` prevents duplicate shutdown requests and `attempted` prevents repeated automatic execution of the same failed intent. A null desired configuration is the Stop state.

`apply(_:running:retry:)` coalesces intent, `startDesired()` validates and starts idle work, and `finished(_:)` releases ownership before considering a requested replacement. An invalid replacement first stops the owned invocation; after it returns, validation can leave the controller idle with the new error rather than continuing to run the obsolete configuration. Clearing running intent also clears the attempted value so a later explicit Start is a fresh decision.

The controller validates before invoking the engine. At the idle boundary, after any previous native call has returned, it calls `hev_socks5_server_prepare()`, records the current configuration and starts the blocking native function on the existing utility queue. The completion is delivered back to MainActor. Restart is allowed only when shutdown was requested and a desired configuration still exists. The owned invocation keeps its controller alive until completion rather than leaving a callback targeting a deallocated owner.

`hev-server-startup-stop.patch` provides the native lifecycle handshake. It initializes shared session class tables before creating workers, then preserves early cancellation before worker execution and the pre-yield stop checks, while permitting the next explicitly prepared idle invocation. Inline credential allocation or credential-file read failure aborts startup before workers run instead of falling back to an unauthenticated listener. The controller does not simulate native completion or overlap an old release with a new startup. Source and native regression tests verify this boundary independently.

The standalone root owns its configuration and requested-running state without persisting them. The settings-enabled root owns one SettingsStore and passes the same model and running intent to this controller. Neither the model nor controller calls the persistence store. Changing tabs does not create a replacement server owner.

## Design rationale and resource cost

One controller and one owned native invocation prevent duplicate listening sockets and overlapping engine state. Retaining only current, desired, attempted and stopping state is sufficient to express coalescing, latest-intent priority and explicit retry without a separate queue of every UI request.

Validation before execution avoids sending malformed parameters into the native parser. Byte-sensitive equality matters because the native engine receives UTF-8 bytes, not a normalized user-interface string. Single-purpose YAML generation keeps configuration escaping in one place.

The design adds no polling timer, periodic restart, packet log or per-packet allocation. Worker cost is determined by the existing configured native engine. Stopping a blocking operation is cooperative: a stalled platform or native operation cannot safely be declared complete merely to allow another invocation. A successful host test is not a physical startup-latency or minimum-RAM measurement.

## Verification contract

The controller suites use the actual controller body with controlled engine returns to test repeated Start, same/different settings, Stop before entry, replacement, delayed MainActor completion, validation failure and explicit retry. State-transition matrices compare the last requested intent with the actual running/idle state and verify owner lifetime. Configuration parity tests exercise the actual Swift YAML and native parser, including quoted and byte-distinct UTF-8 credentials.

Real native tests cover occupied ports, authentication, workers one/four/64, repeated identical requests, explicit retry, invalid replacement settings, active clients during Stop and reconfiguration, and early cancellation. Tests verify that a failed bind does not become an automatic retry loop when the port later becomes available. The worker Stop probe requires the exact upstream worker plus its single guard; a composition may instead supply its feature owner’s reviewed pre-guard digest, with all other edits still rejected.

`Build/check_ownership.py` preserves the functional separation and exact native patch/source boundaries. The document contract separately verifies current parent prose and the frozen non-document tree. The actual SDK test compiles the production interfaces, while Simulator tests exercise the settings controls, Start/Stop, orientation, actual IPv4/IPv6 SOCKS replies and listener release. Source review, model execution and actual socket readiness remain distinct evidence.

## Operation and limitations

Use the dedicated Server-control workflow or the source/native audit route selected by its manifest. Start requires valid configuration. A failed or externally exited server remains an explicit retry decision; editing a setting or selecting Start can request another valid attempt. Stop is available while a request or owned invocation remains active, not only when a readiness probe would succeed.

This feature alone does not save settings. Persistence and restoration are supplied by the settings-persistence feature. In release, saved intent and current service state are different: storage failure must not prevent live Stop, but it can leave a different durable value until saving succeeds.

The configured minimum is iOS 17.2. Physical iOS 27 SideStore standalone and LiveContainer guest operation remain separate deployment layers. Host/SDK/Simulator checks do not certify real permission transitions, host process interactions, prolonged background execution or device resource use. The fixed UDP multiple-unknown-peer restriction is retained, not corrected by lifecycle serialization.

## Related documents

The [shared baseline](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/main-baseline.md) defines native inputs. The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) distinguishes source, native and physical execution. `Build/features.json` declares the server patch, and `docs/documentation.json` identifies the inherited current parent documents.
