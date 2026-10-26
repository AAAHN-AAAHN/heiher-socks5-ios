# Native ICMP Echo relay

## Purpose and scope

This feature adds a reusable native ICMP Echo engine to the HEV core and exposes a local C ingress through the HEV SOCKS5 server. It accepts an already received standard Echo message, its source and destination addresses, and a caller-owned return context. A local client uses the same engine through a small Echo8 convenience function.

The native sources remain the locked upstream server and core, with the UDP compatibility owner's prerequisite patches followed by the two ICMP patches. The independent tunnel checkout remains at its upstream implementation. SOCKS5 CONNECT and UDP ASSOCIATE retain their existing protocol. This feature introduces no SOCKS command or custom client wire format.

A local API is an explicit integration boundary. Ordinary remote `ping` traffic must first reach an ingress adapter through an appropriate routed or captured IP path; connecting a conventional SOCKS client does not deliver ICMP to this API. This owner implements the native Echo service and the local client API. A remote network ingress, TUN packet adapter, IP-header reconstruction, Ethernet bridging and advertisement forwarding are outside this owner's scope.

## Functional behavior

### Request and reply contract

The public API is declared in `src/hev-socks5-icmp.h` and included by `src/hev-main.h` after native patches are applied. `hev_socks5_server_icmp_generation()` returns zero until worker 0 has registered its listening socket and ICMP wake descriptor and completed native bind configuration. A client is created for one nonzero ready generation and cannot migrate to a later server run.

`hev_socks5_server_icmp_submit()` takes an ICMP Echo message, including the eight-byte Echo header and any payload, without an IP header. IPv4 type 8/code 0 and IPv6 type 128/code 0 are accepted. Input IPv4 checksums are validated; an IPv6 input with an original source also validates its pseudo-header checksum. Numeric unicast destinations, IPv4-mapped IPv6 normalization and scoped IPv6 link-local destinations are supported. Unspecified or multicast addresses and malformed Echo messages fail explicitly. The maximum message lengths are 65,515 bytes for IPv4 and 65,535 bytes for IPv6; the network, OS and path MTU may impose a smaller usable size.

`hev_socks5_server_icmp_ping()` constructs an Echo8 message using the same core generator and submits it through that ingress. The configured bind address and interface apply to the native socket, or the OS selects a local source. The optional original source argument identifies the logical return destination and does not request outgoing IP-source spoofing. The local convenience path supplies no original remote source.

Identifier and sequence values are replaced on the network leg so simultaneous clients can use identical original values without sharing reply ownership. An accepted reply must match the current socket identifier, active sequence, actual peer, message length and payload. The result restores the original identifier, sequence and return address, with the corresponding IPv4 or IPv6 checksum. Payload bytes remain unchanged. An expired, foreign, malformed, truncated or unmatched packet produces no successful reply callback.

Return zero means the input was copied into the bounded native queue. A negative errno means immediate rejection and no callback. Accepted requests emit `HEV_SOCKS5_ICMP_SENT` only when the OS accepted the entire Echo message. They subsequently emit `HEV_SOCKS5_ICMP_REPLY` for a matching received Echo Reply or `HEV_SOCKS5_ICMP_ERROR` for a terminal failure. A send failure emits ERROR without SENT. A positive partial send is counted as an actual transfer but terminates with `EIO`. Timeouts are explicit from 1 through 60,000 milliseconds and start at successful transmission. ICMP errors other than Echo Reply are consumed without extending the protocol; a request without a valid reply ultimately times out.

### Cancellation, lifecycle and I/O observation

Callbacks run serially on native worker 0, and result storage is borrowed only for the callback duration. Callbacks must return promptly and must not destroy a client or stop/join the server. Each callback includes the caller's request identifier; the callback context belongs to its client. A caller can keep additional request state keyed by that identifier.

Cancel invalidates requests accepted before the call, including queued submissions. Once cancellation returns, those submissions cannot begin a later send. Client free also waits for an active callback and prevents subsequent use of its context. The caller must serialize free against its own other handle accesses. Server stop disables new admission immediately, wakes worker 0 and drains queued and active state before the native server call returns. Restart publishes a new generation, so stale clients fail with `ENOTCONN`.

`hev_socks5_server_icmp_set_io_observer()` installs an optional callback while the native service is stopped. It runs synchronously on the same native worker immediately after positive socket I/O, before reply validation or cancellation filtering. The observer receives the actual peer, byte count and direction. Reads count bytes actually copied into the application buffer, clamped to capacity if an OS reports a larger truncated length. Writes count the positive byte count accepted by the OS, including a hypothetical partial write. Zero-transfer failures, internal C calls, queue movement and wake-pipe signaling add no network bytes. The observer must return promptly and must not reenter the ICMP API. The server wrapper preserves the syscall's `errno` across observation.

The callback is optional and creates no dependency on the Statistics feature. The Statistics owner can attach its ordinary socket-I/O adapter. No own-IP request or reply bytes are invented for the in-process client; local-IP traffic is counted only when it actually crosses the application's socket boundary.

## Implementation and ownership

The [feature manifest](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/Build/features.json) records the exact source commits and ordered prerequisite patches. It extends `feature/udp-compat`; the parent remains the owner of its seven native patches and transport regression tests.

[hev-icmp-core.patch](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/Patches/hev-icmp-core.patch) owns the native message validation, Echo8 generation, identifier mapping, socket I/O, reply restoration and bounded pending engine. It adds a private core header through the upstream include convention.

[hev-icmp-server.patch](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/Patches/hev-icmp-server.patch) owns the public local C API, client generations, admission and callback lifetime, worker-0 integration, configured native binding and the optional I/O observer. It exports the public header in the native Apple framework build. The public header is separate so the Statistics owner's header additions do not require alternate versions of this patch.

[Tests/ICMP](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/Tests/ICMP/native.c) owns executable native behavior and lifecycle checks. The independent [ICMP audit workflow](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/.github/workflows/verify-icmp.yml) runs the owner audit. Shared baseline build scripts, source locks, checked-in baseline framework and upstream application files retain their parent's bytes.

## Design rationale and resource cost

One worker owns all ICMP socket operations and reply state. A lazily opened datagram ICMP socket serves each address family, so thousands of targets do not require thousands of sockets, TCP sessions or independent native tasks. There is one ICMP coroutine with a 64 KiB stack and one nonblocking wake pipe. At most two ICMP descriptors are open. A coalesced pipe wake lets producers submit from another thread without polling an idle service.

Native admission is limited to 1,024 live client handles, 4,096 pending requests and 16 MiB of retained Echo messages, including queued and active submissions. Reaching either pending limit returns `EAGAIN` without allocation or partial admission. Each message is copied once. Per-request metadata and allocator overhead are additional bounded costs. The direct sequence lookup table uses 65,536 pointers, allocated on the first send, and one 65,535-byte receive buffer is reused. An active socket requests a 128 KiB send buffer and 256 KiB receive buffer; the actual OS allocation policy remains platform dependent.

Each worker cycle admits at most 256 queued submissions and consumes at most 64 received messages per family before yielding. A direct sequence table avoids scanning every pending request for each reply. Deadline and cancellation scans remain bounded by the pending-request limit. Identifier space rotates only after outstanding requests have drained, avoiding reuse of an active mapping. Identifier fields are finite; they cannot provide a cryptographic identity or an unbounded replay guarantee.

The engine, server lifecycle adapter and optional statistics observer have separate responsibilities. The API and helper functions stay small because a dedicated worker and a fixed pair of socket paths replace per-target session objects or multiple parallel implementations.

## Verification contract

Run `python3 Tests/ICMP/audit.py` from a clean committed owner checkout with clang-format 18, a native C compiler and functional IPv4/IPv6 loopback. The audit verifies the committed source archive and full source pins, exact patch application and reversal, upstream C formatting, documentation and composition contracts, native ICMP behavior, and inherited TCP/UDP traffic. On the Apple runner it also compiles all changed native sources against the actual iOS 27 SDK. No IPA is packaged by this independent audit.

The actual native tests cover all 65,536 generated IPv4 sequence checksums, the IPv6 Echo8 format, real IPv4 and IPv6 loopback, large Echo messages, multiple clients with identical original identifiers, restored payload and checksums, an already received IPv6 request with a separate logical return source, immediate invalid-input rejection, cancellation before transmission, callback quiescence, count and byte admission bounds, stop/restart and stale-generation rejection.

A separate Linux linker-wrapper mode injects socket-creation and send errors, a positive partial write, a missing reply, a foreign identifier and receive truncation. It checks terminal events, actual-byte observation, shared socket count and descriptor release. These deterministic socket-pair tests are identified as simulated I/O and do not substitute for the real ICMP gate. `python3 Tests/ICMP/run.py PATH_TO_PREPARED_NATIVE_SOURCE --faults-only` is a diagnostic Linux command, not an acceptance result for native ICMP availability.

The CI Linux runner explicitly permits its test group to open datagram ICMP sockets before running the strict real gate. A permission failure, missing IPv6 loopback, native timeout or any assertion failure fails that gate. The workflow records the actual runner policy and Apple toolchain in its output. `SUCCESS.txt` is written only after all applicable audit checks and source restoration pass. Functional source identity and parent document provenance are frozen in the branch's documentation contract.

## Operation and limitations

The operating system must allow `SOCK_DGRAM` ICMP/ICMPv6. Linux permission depends on the runner or host's ping-group policy. Apple socket behavior is exercised on the native Apple CI host and the actual iOS SDK is a compilation gate; neither proves installation permissions or suspension behavior on a physical iOS device, SideStore or LiveContainer. Those environments require device validation before making device-runtime claims.

An idle native server opens no ICMP sockets until a request needs its address family. Permission, bind, interface, resource and send failures are returned through the native API. There is no raw-socket privilege escalation or silent simulated reply in production. Existing server bind-address, interface and mark settings govern outbound sockets. The relay emits a new OS-managed IP packet and preserves the Echo payload and logical reply identity; original IP headers, TTL, fragmentation layout and network path are not replayed by this API.

A higher-level local client should wait for a nonzero generation, allocate a client, submit bounded batches and handle capacity errors without a busy retry loop. On an Off action it should close its own submission admission, cancel, and free the handle when concurrent callers no longer retain it. No GUI-running flag replaces native readiness. This owner supplies no timer, audio background service, application settings, UI, traffic store or automatic remote routing configuration.

## Related documents

The [governing principles](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/docs/top-level-principles.md) define the project-wide correctness, efficiency and ownership rules. The [preserved UDP parent guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/docs/branches/feature-udp-compat.md) describes the inherited transport behavior. The [native source lock](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/Build/upstream.json) distinguishes original upstream gitlinks from the explicitly selected shared core. The [upstream application README](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/feature/icmp-relay/docs/upstream/README.md) and license remain preserved.
