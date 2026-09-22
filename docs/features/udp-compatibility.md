# UDP compatibility: Darwin peer ports and received addresses

## Purpose and scope

This feature repairs two independent UDP interoperability problems observed when a
Windows sing-box SOCKS5 client relayed Sunshine/Moonlight through an iPhone hotspot.
The Python implementation worked; the native Hev server initially did not. The goal
is to repair the existing C implementation, not replace its event loop, change its
routing policy, or add a second proxy. The application settings and upstream UI are
unchanged on this branch. No Python runtime is included in the app.

The branch is `feature/udp-compat`. Its shared base is the latest app + engine combination on main,
identified by `base_commit` in `Build/features.json`. The build uses the pinned server revision
listed in `Build/features.json`, not the old binary framework committed upstream.

## Evidence and investigation

SOCKS5 UDP ASSOCIATE may contain a zero client port when it is not yet known.
The original server called `connect()` with that zero remote port before the
existing first-datagram peer discovery could run. Darwin rejects that operation.
The first patch defers only that invalid early connect; nonzero ports keep the
original behavior and error handling. The value of `udp_associated` is unchanged.

A second failure remained after that guard: an IPv4 DNS reply was advertised as
`[::]:53`. The relay accepted a Darwin `sockaddr_in` as though it were a
`sockaddr_in6`. Their port fields align but their address fields do not. The same
representation issue affected the first UDP client's peer address. Tests reproduced
the erroneous encapsulated source on macOS. Both patches together enabled the
owner's real Moonlight connection; an address-only comparison failed again for
unknown client ports. Fixed and ephemeral UDP listen ports both worked in the
owner's final test. These are prior observed results, not a claim that CI runs on
an actual iPhone or Sunshine installation.

## Files and exact behavior

`Patches/hev-udp-port-zero.patch` changes `src/hev-socks5-session.c` in the server.
`hev_socks5_session_udp_bind()` invokes its initial `connect()` only when
`dst->sin6_port != 0`. It does not swallow a connection error. A zero port retains
`udp_associated == 0`, and the original receive path learns the real client port.
The association reply is sent before waiting for the first datagram, avoiding a
client/server handshake deadlock.

`Patches/hev-udp-sockaddr.patch` changes `src/hev-socks5-udp.c` in `src/core`.
A file-local helper copies an AF_INET address into a temporary, clears the existing
full-sized destination, and reconstructs an IPv4-mapped AF_INET6 address. It keeps
the network-order port and the four address bytes, and sets `sin6_len` on Apple
platforms. Already-IPv6 addresses are untouched, including their scope and flow
information. The helper is called before first-peer connect and before serializing
external reply addresses. `msg_namelen` capacities are reset before receive-vector
reuse because that field is both an input capacity and an output address length.
The patch is 27 added / 3 removed C lines (net 24), not a second serialization stack.

## Resource and architectural choices

No heap allocation, new socket, timer, thread, lock, queue, payload copy, or
per-packet asynchronous task is added. The address helper uses a small automatic
variable. IPv6 returns immediately. Actual replies are normalized, not all empty
vector slots. The bounded length reset writes only address-length fields. Avoiding
that reset would rely on undocumented state after receive errors or add platform
branches. The first-peer connect passes the normalized buffer and its true size
directly; redundant pointer and length aliases were removed during the earlier audit.
The C formatting follows the pinned upstream `.clang-format`.

## Deliberate limits

The minimal zero-port guard keeps the existing first-datagram peer selection.
It does not add TCP-peer IP verification before accepting that first packet. This
is not a security-hardening or complete RFC compliance patch. Run the service only
on a trusted hotspot/LAN; do not expose an unauthenticated relay publicly. Fixed
shared UDP ports, SOCKS fragmentation, maximum payload sizes, and VPN behavior are
not redesigned. No universal throughput, battery, or uninterrupted-background
claim is made. SOCKS5 itself does not encrypt application payloads.

## Verification and use

`Tests/udp_sockaddr_regression.py` starts the actual native server and echo endpoints.
It checks IPv4 and IPv6, unknown and known peer ports, reply source and payload
integrity, multiple associations and closing one without breaking the rest, and
TCP regression. Six payload lengths are used in single-UDP cases. macOS is required
to exercise Darwin address behavior; Linux alone is insufficient evidence.

`Build/build.sh` applies the branch's declared patches in order, checks exact source
revisions and C formatting, runs the native tests, builds a fresh Apple framework,
and archives the application. See `docs/build-and-validation.md` for commands,
artifact contents, and the distinction between device and host testing. Statistics
has this branch as an explicit prerequisite so its UDP tests are meaningful on iOS.
Other feature branches do not silently inherit this repair unless their manifests
say so. The integrated release includes it unchanged.

## Primary references

- RFC 1928, section 7: https://www.rfc-editor.org/rfc/rfc1928
- Pinned Hev sources and patch paths in `Build/features.json`.
- Apple XNU address families: https://github.com/apple-oss-distributions/xnu
