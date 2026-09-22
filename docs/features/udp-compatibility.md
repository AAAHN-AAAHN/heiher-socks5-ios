# UDP compatibility for the native iOS SOCKS5 relay

## Scope and release qualification

This is `feature/udp-compat`, not the complete application. It adds two small C
repairs to the shared **latest-verified iOS app + unpatched server** baseline on
`main`. It does not add statistics, Background services, JSON settings, an icon,
a second proxy, or another I/O loop. The baseline framework committed to Git remains
unpatched; a normal feature build applies the two patches before linking the app.

The review baseline is `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`. This branch began
the focused final audit at `3a76532c14826f8938b0977d30c8d94143bdfeea`.
`Build/features.json` records the exact base and patch order. `Build/upstream.json`
pins iOS app `180012e8b9dbaa2002a68ebd2c75bccebcfb789c`, server
`b3585289622561caf4b8789b436cc8820ecd6be0`, and that server's own submodule revisions.
The word latest describes that verified snapshot, not an automatic update service.

**The two targeted compatibility defects are repaired. This is not an unconditional
SOCKS5 security/conformance approval.** In particular, a shared fixed UDP listen
port with several unknown client ports has a first-peer allocation limitation.
Expanded native tests reproduce a concurrent-association failure with both patches
on Linux and macOS. A single successful Moonlight session does not disprove this
multi-association limitation. Use `udp-port: 0` when multiple unknown-port
associations must coexist. Observations remain separate from required passes.

Evidence qualification: in completed run `35696504942`, Linux's unpatched fixed-port
profile passed the concurrent-association scenario; its one failure was the separate
`::1:0` hint scenario. That aggregate 8/9 result does NOT establish the same
concurrent failure in unpatched code. Darwin's unpatched version fails earlier at
association setup. The two-patch shared-port failure is real, but these controls do
not establish that it is exclusively inherited rather than exposed or affected by
the patch. See `docs/reviews/udp-compat-20260922.md` and each named JSON result.

## Why the patches exist

The owner uses a Windows sing-box SOCKS5 client over an iPhone hotspot, including
Sunshine/Moonlight UDP. The earlier Python relay worked, while the native Hev relay
initially failed. Inspection and comparative tests identified two different stages:

1. Unknown client port: the server performed an initial UDP `connect()` to peer
   port zero. Darwin rejected this before UDP ASSOCIATE could complete.
2. Address representation: after bypassing that call, an IPv4 reply could be
   encapsulated as `[::]:53` instead of the real IPv4 source. On the relevant Darwin
   receive path an AF_INET address occupied the buffer that Hev interpreted as
   AF_INET6. Port fields overlap, but IP address fields do not.

Earlier owner device tests succeeded with both patches and failed again when the
port-zero guard was removed. Fixed and ephemeral listening ports both worked in
that use case. Those are historical device observations. Native host tests, unit
I/O doubles and a successful compile are not new iPhone/VPN/Moonlight measurements.

## Complete file inventory relative to main

The branch entered review with eight differing files. The completed audit has
12 differing paths. Every changed file is part of the review, not just the C text.

| File | Responsibility and reason |
| --- | --- |
| `Build/features.json` | Select only `udp`, the two ordered patches, and the exact base commit; source pins match main. |
| `Patches/hev-udp-port-zero.patch` | Guard the invalid initial peer-port-zero connect in the server session binder. |
| `Patches/hev-udp-sockaddr.patch` | Normalize received AF_INET addresses at two boundaries and restore reusable address capacity. |
| `README.md` | Canonical complete feature, scope, verification and limitation specification. |
| `docs/features/udp-compatibility.md` | Identical specification at the shared feature-document location. |
| `Socks5/Info.plist` | Local-network permission explanation and single-scene ownership; no location/audio background modes. |
| `Socks5.xcodeproj/project.pbxproj` | Register that plist and use it in Debug/Release. Existing blank-line differences are non-executable, not another feature. |
| `Tests/udp_sockaddr_regression.py` | Real native TCP/UDP echo tests, expanded with fixed-port, worker, burst and mixed-family profiles. |
| `Tests/udp_sockaddr_unit.c` | Exercise the actual patched C translation unit with scripted I/O boundaries. |
| `Tests/udp_compat_audit.py` | Native-only audit driver, negative controls, source/diff artifacts and iOS syntax-only checks. |
| `.github/workflows/verify-build.yml` | On this branch only, run the native audit at the triggering commit without creating an IPA. |
| `docs/reviews/udp-compat-20260922.md` | Concrete results, corrections, residual limitations and final disposition. |

Common `Build/build.sh`, `Build/check.py`, source locks, baseline framework and
upstream Swift sources remain unchanged. The single-window/local-network metadata
already existed on this feature branch; it is supporting app configuration, not
part of the UDP algorithm. Test code is not registered in the application target.

## Patch 1: unknown client port

Target: server `src/hev-socks5-session.c`, `hev_socks5_session_udp_bind()`.

```c
    if (dst->sin6_port != 0) {
        res = connect (sock, (struct sockaddr *)dst,
                       sizeof (struct sockaddr_in6));
        if (res < 0)
            return -1;
    }

    HEV_SOCKS5 (self)->udp_associated = !!dst->sin6_port;
```

A nonzero client port keeps the original connect and error handling. A zero client
port leaves the association unestablished until the existing first-datagram path
learns its peer. The SOCKS reply is still returned before waiting for a datagram,
so clients waiting for BND.ADDR/BND.PORT are not deadlocked. Comparing with zero
needs no `ntohs()`. The patch adds six and removes three C lines (net three).

There are **two different ports** here. `dst->sin6_port` is the client's remote UDP
port; the application's UDP Listen Port is the local relay port. Local port zero
requests an ephemeral port and can independently be used with known or unknown
client ports. Changing one is not an alternative implementation of the other.

## Patch 2: received address normalization

Target: core `src/hev-socks5-udp.c`. The file-local helper is called in
`hev_socks5_udp_recvmmsg_udp()` before first-peer connect, and in
`hev_socks5_udp_fwd_b()` before constructing the SOCKS reply's source address.

The receive buffers at both call sites really are full-sized, aligned
`struct sockaddr_in6` objects. These are kernel-returned addresses from IP sockets,
not unvalidated arbitrary pointers or a 16-byte caller-owned IPv4 allocation.
For AF_INET input the helper:

1. Copies the IPv4 structure to a small automatic variable before overwriting it.
2. Clears the full destination so flow information and scope cannot retain garbage.
3. Sets AF_INET6, preserves the network-order port, creates the IPv4-mapped prefix,
   and copies the original four IPv4 address bytes into its final four bytes.
4. Sets Darwin's `sin6_len` to the complete destination size on Apple platforms.

AF_INET6 input returns without modification, retaining native/mapped addresses,
port, flow information and scope. The copies avoid overlapping reinterpretation
and type-punning through two incompatible struct pointers. This is address
representation normalization, **not NAT64 synthesis or IPv6 network translation**.
No payload is transformed, and no DNS query is introduced.

`msg_namelen` is restored to `sizeof(struct sockaddr_in6)` for every reusable
external receive vector before each receive attempt. The API treats it as both
input capacity and output address length. Leaving a previous shorter IPv4 length
can truncate a later IPv6 address. Resetting the bounded vector is correct even
after EAGAIN; replacing it with hidden state/platform assumptions is not justified.
Only actually received reply addresses are normalized. The first peer is normalized
once before successful connect, not on every later client datagram.

The helper and both call sites remain identical to the working two-patch version.
The address patch adds 27 and removes three C lines (net 24); together the two
repairs change two C files by net 27 lines. The original includes already supply
the required types and memory functions; no public API or persistent field is added.

## Minimality, standard style and resource review

The change preserves native C, the original socket families, vector I/O, coroutine
yield/wait/error paths, socket/buffer allocation, peer state and relay direction.
It adds no heap allocation, socket, thread, lock, timer, queue, payload copy, log
per packet, Swift call, or dynamic history. The helper uses a small stack temporary.
The zero-port branch runs at association setup. The external capacity reset is a
bounded set of stores (default ten entries), plus normalization of received replies.
These instructions have nonzero cost; no unsupported claim of zero overhead or
absolute best CPU/battery performance is made.

Both patched C files follow their pinned upstream `.clang-format`, including
four-space indentation, function spacing, explicit casts and 80-column wrapping.
GNU C is the existing build dialect. Existing GNU extensions in unchanged upstream
code are not misrepresented as new ISO-C-only code. Unchanged files are not globally
reformatted. Swift app logic is untouched. Python tests use standard-library code,
bounded socket waits and process cleanup; assertions are required, not disabled
with `python -O`. Tests are not listed as app sources or resources.

## Reproducible audit, without an IPA build

On a clean Git checkout with Clang, Python 3, make and clang-format 18:

```sh
python3 Tests/udp_compat_audit.py
```

The driver refuses an unrelated feature composition or an existing audit checkout.
It verifies shared main ancestry, source pins and the committed framework, clones
the exact recursive native source, and compares four variants: unpatched,
port-only, address-only, and both. Darwin controls must fail for the specific missing
repair, not merely fail for any reason. Linux results are reported without
pretending its socket behavior is Darwin's. Failure details remain in JSON and
server logs. On macOS, both patched C files also undergo ARM64 iOS syntax-only
compilation against the installed iPhoneOS SDK; this creates no app or IPA.

Strict two-patch profiles exercise ephemeral listening ports with one/four workers,
explicit IPv4/IPv6 outbound binds and unbound outbound sockets, repeated mixed
external families, three simultaneous associations, closing one while keeping the
others, and three bursts of 24 unordered datagrams. The original six payload sizes
and IPv4/IPv6 TCP cases are retained. Shared fixed ports with advertised known
client ports are also required to pass. Fixed-port/unknown-peer cases are explicit
**observations**, not hidden expected-success tests.

The C unit includes the actual patched `hev-socks5-udp.c`, not a reimplemented
Python address model. Only connect/receive/send boundaries are scripted. It checks
all 65,536 port values, IPv4 bytes, zeroed scope/flow, Darwin length, canaries,
idempotence and byte-for-byte IPv6 preservation. Actual caller paths are exercised
for EAGAIN, connect failure, first-peer state, capacity reuse and mixed-family reply
serialization. It runs with AddressSanitizer/UndefinedBehaviorSanitizer and again
at `-O3 -fstrict-aliasing`. Linked support libraries are not claimed to have full
sanitizer coverage. No full-app sanitizer or real-device energy test is implied.

Artifacts under `artifacts/udp-final-audit/` contain the tested source ZIP, complete
main-to-feature diff, manifests, controls, strict profiles, observations and unit
logs. Patch reversal must restore upstream source. This audit never invokes
`build-apple.sh`, `xcodebuild archive`, or IPA packaging. A separate future
distribution build can use the unchanged `Build/build.sh`; it must not be confused
with this review's native audit.

## Explicit remaining limits

| Condition | Status and consequence |
| --- | --- |
| Several unknown-port associations share one fixed UDP relay port | Concurrent failures are reproduced with both patches. The existing SO_REUSEPORT/first-datagram design permits ambiguous session ownership, but the controls do not prove exclusive upstream causation. Ephemeral local ports passed the tested profiles. |
| First packet before peer establishment | The minimal design does not check that its source IP matches the TCP control peer before learning it. Connected UDP then filters the selected peer, but that is not initial authentication. Do not expose the listener to untrusted devices. |
| SOCKS fragment/reserved fields | These patches do not introduce a FRAG/RSV validation or reassembly policy. The pinned parser's existing behavior is not a full RFC 1928 conformance guarantee. |
| Large/empty datagrams | The original 1500-byte relay buffers, truncation handling and rejection of empty outgoing payloads are not redesigned. Six successful test sizes do not establish arbitrary UDP payload support. |
| Outbound address-family binding | A socket explicitly bound for one family need not support later traffic of the other family. Mixed-family tests intentionally omit that bind. |
| Wildcard/public relay addresses, link-local scope, VPN transitions | These settings and routing behaviors remain upstream responsibilities; this audit is not coverage of every deployment. |

The source-IP rule and nonzero-FRAG drop requirement in RFC 1928 are separate from
C language/style correctness. Merely passing the targeted compatibility tests must
not be described as fixing these unrelated protocol/security limits. Addressing
them requires a separately scoped decision rather than enlarging a previously
agreed minimal patch without explaining the behavior change. Main and release are
not modified by this audit.

## Primary references

- SOCKS5 association and relay rules: https://www.rfc-editor.org/rfc/rfc1928
- Receive address length/truncation contract: https://pubs.opengroup.org/onlinepubs/9699919799/functions/recvmsg.html
- Apple address structure: https://developer.apple.com/documentation/kernel/sockaddr_in6
- Darwin socket implementation: https://github.com/apple-oss-distributions/xnu
- Exact code revisions and applicable repositories: `Build/features.json`.

The full build and common baseline policy remain in `docs/build-and-validation.md`
and `docs/main-baseline.md`. Their paths are relative to the repository root.
