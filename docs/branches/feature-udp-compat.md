# UDP compatibility and adaptive datagram buffers

## Purpose and scope

This feature preserves complete SOCKS UDP messages, correct address reporting and peer isolation while retaining the native engine's compact association and task model. It also handles UDP-over-TCP framing without treating an incomplete byte stream as a completed datagram.

The branch adds native transport behavior to the shared baseline. It does not implement traffic counters, persistent settings, background services or a new SOCKS protocol. A datagram remains one message; larger payloads are not split into independent UDP messages. The configured fixed-port policy is retained, including its explicit multiple-unknown-peer limitation.

## Functional behavior

### Association setup and source identity

A client may request UDP ASSOCIATE without knowing its UDP source port. The server does not attempt to connect the relay socket to port zero. It binds the relay and reports its usable address and assigned port. With a known client endpoint, the existing connected-socket path remains available.

For an unknown endpoint, the first accepted datagram must match the TCP control peer's IP and pass the SOCKS header and address checks before its source port is learned. Subsequent datagrams must match the established endpoint. Queued packets are checked individually, including packets queued before the UDP socket became connected. Discarding a batch of foreign packets does not incorrectly signal that the entire socket queue is empty.

IPv4, IPv4-mapped IPv6, native IPv6 and address scope are normalized for the native APIs and SOCKS address representation. The address in a reply describes the actual remote sender. Address conversion preserves complete IPv6 storage and respects strict-aliasing requirements rather than reinterpreting incompatible structures in place.

### Complete message and frame handling

Standard UDP input validates minimum length, address form and length, reserved bytes, unsupported fragmentation and actual truncation flags. Nonzero RSV or FRAG input is discarded before peer learning. A malformed or truncated prefix is not forwarded as a normal complete payload. Empty payload datagrams remain messages and are distinct from an empty receive queue or TCP EOF.

UDP-over-TCP uses its own frame-length interpretation. The standard zero-RSV/FRAG rule is not applied to the frame's length field. Headers and bodies must be fully read before a message is reported complete. Successful messages preceding a later receive failure retain their completed count. A partially written stream frame is not reported as a successfully sent datagram, and a new frame is not appended as though the incomplete frame had succeeded.

### Adaptive buffer policy

Each managed receive slot starts with a 1,500-byte data region. Larger required capacities are rounded up in 500-byte steps. A requirement of 48,001 bytes obtains 48,500 bytes; 30,001 obtains 30,500. The required size includes any protocol header stored in the same receive region. Allocation does not impose a separate arbitrary 65,536-byte ceiling, but wire-format, arithmetic, allocator, socket and network-path limits still apply.

Each 500-byte demand bucket records one expiry time based on a 300-second holding interval. A demand refreshes its own bucket, not every smaller or larger capacity. Small messages therefore do not keep a large buffer alive indefinitely. Cleanup checks the recent demands at a 60-second cadence and returns unused expanded storage toward the largest still-needed bucket or the 1,500-byte base.

For example, a large demand followed two minutes later by a smaller expanded demand permits the first capacity to expire independently. Cleanup needs no subsequent application packet to run. It never moves storage still referenced by active I/O, and it does not treat maintenance activity as new client traffic that extends the communication timeout.

The constants are `UDP_BUF_SIZE`, `UDP_BUFFER_GROW_STEP`, `UDP_BUFFER_HOLD_SECONDS` and `UDP_BUFFER_CLEANUP_SECONDS`. An expanded slot of capacity C holds `(C - 1500) / 500` expiry entries, each a `uint64_t`, followed by its contiguous replacement data region in the same allocation. Resizing copies the relevant expiry entries, not stale packet content. The original base storage remains available and is reused when expanded storage is released.

## Implementation and ownership

The feature is expressed by `hev-udp-port-zero.patch`, `hev-udp-sockaddr.patch`, `hev-udp-peer-filter.patch` and `hev-udp-dynamic-buffer.patch`, applied at their manifest roots. The public message representation remains address, contiguous buffer and length. The existing association owns the sockets; its native task owns buffer lifetime and cleanup scheduling.

The port-zero patch applies to the server repository; the address, peer and dynamic-buffer patches apply to `src/core`. `UDPBuffers` owns the relay slots and the cleanup/idle deadlines, while each `UDPBuffer` describes one slot. Automatic growth belongs to this managed forwarder path. The public `hev_socks5_udp_recvmmsg()` entry retains caller-owned storage and does not resize an arbitrary caller buffer; capacity and truncation checks still prevent an undersized caller buffer from becoming a successful complete frame.

Receive sizing occurs before consuming a message. Darwin uses `SO_NREAD` and a one-byte non-consuming probe when a zero result could mean either an empty datagram or an empty queue. Linux uses `MSG_PEEK | MSG_TRUNC | MSG_DONTWAIT` with a zero-length receive buffer. Actual receive length, flags and capacity are checked again when the message is consumed. Different queued datagrams are sized individually rather than assuming that a batch has the first message's size. An expansion failure leaves the queued message unconsumed and ends the association instead of forwarding a truncated prefix or spinning indefinitely on that queue head.

Expansion allocates the required rounded space directly. Bucket metadata records capacity demand rather than a per-packet history. Allocation failures do not leave dangling buffer references. A failed shrink retains usable storage for a subsequent cleanup attempt. Association teardown releases its owned expanded storage independently of the holding interval.

The task's existing timer supports cleanup and communication timeout without a new production thread, Swift timer or global buffer registry. When no expanded capacity remains, unnecessary cleanup wakeups stop. The timeout applies to communication, not to the bookkeeping wakeup itself.

On Darwin, a valid large send rejected with EMSGSIZE may require a larger socket send-buffer allowance. Only that failure path queries `SO_SNDBUF` and requests a larger allowance when it is actually too small. The same unsent message index receives at most one adjustment-and-retry opportunity; after successful progress, a different unsent message in that batch can receive its own opportunity. Completed messages are never resubmitted by this retry path. Socket allowance is distinct from user-space payload retention and may persist for the socket's lifetime.

## Design rationale and resource cost

Contiguous messages preserve the engine's existing parsers, send interfaces and ownership model. Direct rounded growth avoids repeated reallocations through every intermediate size. Keeping recently useful space avoids allocating and freeing large buffers for each packet. Expiry per capacity bucket provides bounded metadata per supported capacity range without recording every message timestamp.

The implementation has real costs: next-datagram sizing calls, some loss of Linux receive-batching benefit, bucket metadata, expanded capacity and temporary old/new storage during a shrink. The existing base storage can coexist with an expanded region. Memory returned to an allocator need not immediately reduce process RSS. These costs are different from continuously allocating a maximum-size buffer for every small message.

The fixed-port/unknown-peer policy is not silently changed to reduce association ambiguity. Multiple unknown clients sharing one fixed relay endpoint can be associated with the wrong control connection. A forced dynamic-port fallback would change the configured behavior and network reachability requirements; it is not part of this implementation.

## Verification contract

`Tests/udp_compat_audit.py` executes real native networking and separate controlled-boundary fixtures. Source, native patch order, formatting and exact patch reversal are checked independently from behavior. The address fixture covers port values, normalized addresses, canaries and IPv6 preservation. Peer tests cover foreign first senders, wrong ports, queued packets and continued progress after rejected batches.

The buffer fixtures exercise demand rounding, expiry, large-to-small retention, overflow and allocation failure, queue/zero-length distinctions, truncation, partial success, cancellation and final cleanup. A reference history calculation checks the bucket policy rather than assuming the implementation's own result is correct. The live-hold and timer fixtures use actual sockets, clock, allocator and Hev scheduling; their test-only communication timeout is distinct from the application's configured timeout.

The stream-boundary fixture checks complete frames, every tested truncation point, address/header consistency, partial sends and wire-length rejection in sanitizer and optimized configurations. The network suite compares full payload content and address, including payloads above the base capacity. Negative controls prove that missing peer, address, length or completion checks are detected. Observational fixed-unknown failures remain explicitly separate from required supported profiles.

The feature's SDK checks compile the actual patched C/session and applicable Swift source for the configured target. They do not constitute a new device installation or an IPA produced by a native-only audit route. The documentation checker validates inherited prose without changing any of these functional test inputs or oracles.

## Operation and limitations

Use a clean full-history checkout and `python3 Tests/udp_compat_audit.py` for the standalone audit. Feature manifests identify the source roots and patch order. The application's server configuration accepts UDP port zero, but its default and configured fixed-port behavior are not automatically migrated. A client must use the relay endpoint returned by its association response.

Correct independent shutdown of multiple unknown-peer associations on a single fixed UDP endpoint is an explicit limitation. Peer checks are not cryptographic authentication, and a valid first sender sharing the expected IP can still compete to establish an unknown source port. NAT, firewall and socket/path limits are not overridden by a larger buffer.

The configured minimum is iOS 17.2 and the primary target is physical iOS 27 through SideStore standalone or LiveContainer guest execution. Actual installer, host, VPN/hotspot, suspension, long-background and device-resource behavior require separate evidence. Timer intervals are scheduling policies, not deadlines that override blocked I/O or process suspension.

## Related documents

The [shared baseline](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/main-baseline.md) describes source inputs. The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) distinguishes execution layers. `Build/features.json` is the executable composition and `docs/documentation.json` is the current-parent document contract.
