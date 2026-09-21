# Hev UDP compatibility patches

These two patches are used together by `build-keepalive-ipa.yml`.
They modify two C files in total. The Swift app, background keep-alive module,
public interfaces, packet buffers and HevTaskSystem remain unchanged.

## Pinned sources

| Repository | Commit |
| --- | --- |
| `heiher/hev-socks5-server` | `b3585289622561caf4b8789b436cc8820ecd6be0` |
| `heiher/hev-socks5-core` (`src/core`) | `162dd996299fc2d2bff2dd63728f8a2cd71ed31a` |

## Patch scope

### `hev-udp-port-zero.patch`

Applies to `src/hev-socks5-session.c` in the server repository.
Only call the initial UDP `connect()` when the requested client port is nonzero.
The existing error handling and `udp_associated` assignment are retained.

The guard is functionally unchanged from the tested version. Its 83-column
`connect()` statement is wrapped to match upstream's 80-column formatting rule.

### `hev-udp-sockaddr.patch`

Applies to `src/hev-socks5-udp.c` in the core submodule.
Normalize received `AF_INET` addresses to Hev's IPv4-mapped `AF_INET6` format
before first-peer `connect()` and before response-address serialization.
Restore receive-address capacities before reusing the message vector.

The helper, its two call sites and the pre-receive capacity reset retain the
behavior of the tested address patch. Two unnecessary first-peer aliases are
removed: `saddr` already points to `taddr`, and `alen` equals `sizeof (taddr)`.
The normalized buffer and its size are now passed to `connect()` directly.
This is source simplification, not a measured runtime speedup.
The patch adds 27 lines and removes 3 lines: a net addition of 24 lines.

## Correctness and resource review

- Both receiving sites provide a real `sockaddr_in6`-sized address buffer.
  The in-place conversion does not write into a 16-byte-only allocation.
- Copy the original IPv4 structure before clearing that same destination.
  This avoids overlapping input/output and incompatible-structure reads.
- Preserve the network-order port and all four IPv4 address bytes. Clear
  flowinfo and scope before constructing the mapped address. Set `sin6_len`
  on Apple platforms.
- Already-IPv6 addresses return immediately without mutation. Existing mapped
  addresses, IPv6 scope identifiers and flow information are preserved.
- Use the normalized buffer size for first-peer `connect()`, not the shorter
  IPv4 length reported by the receive operation.
- `msg_namelen` is a value-result field. Its capacity must be restored before
  reuse; otherwise an IPv4 receive can limit a subsequent IPv6 address copy.
  The bounded pre-call reset is retained rather than relying on the contents
  of output fields after unsuccessful receive operations. With the upstream
  default, it resets ten length fields per receive attempt, not ten packets.
- The helper uses a small automatic temporary, no heap allocation, new task,
  thread, lock, persistent state or additional socket operation. First-peer
  conversion runs only while the peer is unassociated; response conversion
  runs once per received response, not once per allocated vector slot.
- Keep the shared existing address serializer instead of adding a second
  IPv4-specific serialization path. Do not force inlining or make assumptions
  about a particular compiler's generated instruction sequence.

This is a small, resource-light compatibility repair within the current design,
not proof of globally minimal CPU time or RAM consumption. No performance or
battery benchmark was performed for this review.

## Verification

Audit date: 2026-09-21. Audit workflow run: `35595997639`.
The audit workflow is isolated on `audit/udp-patches-20260921` and creates no
object files, libraries, executable applications or IPA files.

Linux x86_64 and iOS ARM64 frontend checks passed using
`-std=gnu11 -Wall -Werror -fsyntax-only`. Clang-format 18.1.3 used the pinned
upstream `.clang-format`; the final C files match its output. The final session
file differs from the syntax-checked guard only in whitespace, with an
identical non-whitespace token sequence.

The original helper and buffer reset are byte-identical to the working patch.
A separate Python byte-layout model passed 22,000 Darwin/Linux IPv4 and IPv6
cases, including preserved ports, IPv6 fields and repeated normalization.
That model is not execution of the compiled C implementation.

Patch application, reversal and original Git blob identities were checked.
The existing native socket tests remain unchanged; they were not re-run and
no binaries were built during this review.

## Source identities

| File | Original Git blob | Patched Git blob |
| --- | --- | --- |
| `hev-socks5-session.c` | `06ce823dd3d29df9107bb53c12178e6b4ebf45c4` | `ef8556619e498b8217b16d75d16a2973b73ac62a` |
| `hev-socks5-udp.c` | `084c03b98d8f80b646381d5cbf82eca95de2eddb` | `5016df65e4a0b66ecdebfef8fbbce46856e042a6` |

Patch SHA-256 values:

```text
9cd0a43550a6128046f81d11bd16971e426386e2656e3e8f16fa790d57bbb315  hev-udp-port-zero.patch
0b2088e6f0519fe01d9d0c64d0bda4cc5909f292ed9095613a1b2434f930ac0e  hev-udp-sockaddr.patch
```

## Unchanged limitations

The minimal port-zero guard still relies on the existing first-datagram peer
selection without adding a TCP-peer IP check. These patches are not a security
hardening change or a full SOCKS5 compliance audit. Existing UDP payload limits,
fragment handling, fixed-port association policy and background execution
behavior are outside this patch scope.
