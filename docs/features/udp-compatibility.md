# Project-wide final verification — UDP compatibility

## Current state — 2026-09-26

The current baseline is main `75335d201cb1e541bb153e9899badbc11ccf1973`,
an actual ancestor, not only a configuration label. The application, original three
native patches, project/plist, defaults, source pins and committed baseline framework
are unchanged from the prior completed UDP owner `7f603a7e063422df460fb171d3b95b36cc6230af`.
The complete preceding specification is preserved byte-for-byte in
`docs/history/udp-before-project-alignment-20260926.md`; the earlier history remains
unchanged too. This README and `docs/features/udp-compatibility.md` are identical.

## Environment, responsibility and source contract

The target is a physical iOS 27 iPhone installed independently through SideStore or
executed as a LiveContainer guest. Signing, container, permission and shared-process
boundaries differ. Neither host tests nor SDK typechecking certifies either physical
path. The configured minimum is iOS 17.2, not a claim of testing every supported OS.
No installer/host version is inferred from the Xcode toolchain.

This independent feature contains UDP compatibility only, not statistics, Background,
JSON persistence, the separate ServerController or a custom icon. The unchanged
single-scene and local-network configuration is preserved. There is no BGTask,
NetworkExtension, host patch, identity override or resolver replacement.

The app pin is `180012e8b9dbaa2002a68ebd2c75bccebcfb789c`; server pin is
`b3585289622561caf4b8789b436cc8820ecd6be0`, with exactly its original core/task/yaml
gitlinks from Build/upstream.json. The 16-file committed XCFramework is the shared
unpatched baseline. A normal feature build rebuilds the declared patches before
linking; the committed framework is not represented as already patched.

## Preserved native implementation

| Patch | Responsibility |
| --- | --- |
| hev-udp-port-zero.patch | Skip the invalid initial client UDP connect when the expected remote port is zero; preserve nonzero behavior, binding, failures and reply order. |
| hev-udp-sockaddr.patch | Normalize AF_INET receive addresses to IPv4-mapped sockaddr_in6, retain port and Darwin length, and reset reusable receive capacity; preserve existing IPv6 scope/flow. |
| hev-udp-peer-filter.patch | Validate unknown-port discovery against the TCP peer and established packets against the selected UDP peer, compact accepted descriptors, and keep draining after an entirely rejected batch through the existing cancellable yield. |

An unspecified remote/client port in UDP ASSOCIATE is different from local
UDP Listen Port 0. The latter allocates a per-association relay endpoint; it is not
a per-packet socket and does not replace the initial-connect repair. Address
normalization is not NAT64 or DNS rewriting. Descriptor compaction does not copy
payloads. Genuine errors, empty queues, cancellation, bounded buffers, vector I/O
and the existing worker/coroutine lifetime remain unchanged.

Peer lookup/comparison, bounded address storage and getpeername have CPU/stack/syscall
costs. No added heap history, periodic timer, thread, listener, dispatcher or packet
log is introduced. No measured zero-cost, throughput or energy claim is made.

## Operating limits retained

Use UDP Listen Port 0 for multiple unknown-client associations. Clients still use
the configured TCP SOCKS endpoint, then the negotiated BND.ADDR/BND.PORT; the network
must permit that UDP endpoint. The existing default 1080 and saved values are not
automatically changed. Fixed ports with accurately advertised client endpoints retain
required tests. Multiple unknown-client associations sharing a fixed port retain an
ownership/independent-close limitation affecting actual delivery, not only accounting.
One successful observation cannot establish that the limitation disappeared.

Source filtering is not cryptographic authentication. Same-IP first-port races,
FRAG/RSV policy, arbitrary/truncated datagrams, empty payloads, family binding and
arbitrary VPN/hotspot routing remain the previously documented scope boundaries.
No dispatcher, association identifier, fallback policy or client modification is
added. Historical Moonlight success is not a new physical-deployment test. Aggregate
old failure counts are never assigned to a particular cause without individual logs.

## Common audit changes and preservation

The inherited main checks all tracked native inputs and the index before applying
patches and after reversing them, rather than only C/H paths or the worktree.
Python optimization is rejected before assertion-based checks. The generic build
invalidates obsolete overall success, checks clean root input/final boundaries, and
places its generated framework only in a disposable HEAD product copy. It no longer
overwrites the tracked baseline. Old staged-reversal and dirty Makefile/script false
accepts are covered by the shared exact-old/current 46-case fixture.

The dedicated UDP entry adds that fixture without changing the native profiles,
peer tests, timeouts, payloads or sanitizer/formatter requirements. Its existing
10 driver methods include the real dual-stack wildcard reservation controls and
old/current source/marker boundaries. This audit does not call generic IPA packaging.

These checks bind inputs at explicit checkpoints. They are not an atomic adversarial
snapshot and do not certify untracked inputs, external toolchains or modification
and restoration between checks. Use a clean, complete, isolated checkout. Old logs
are retained, but invalidated markers are not new successful execution evidence.

## Executed current verification

Run **36219497734**, attempt 1, executed
`3b78847619c5123a1c13a2413faa4ee2525eef77`, tree
`e17f6fa4462e156ba070996a9da0396e655032e5`, with 56 tracked files. Linux and Xcode27
jobs both succeeded. The resumed review downloaded and checked both original ZIPs,
CRC/digest, genuine source commit comments, all file bytes/modes and the tested tree.
No old execution was relabeled as this run; no retry or assertion/timeout relaxation
was needed. This documentation-only completion changes no tested implementation.

Each host passed 58 required profile-case executions, eight current peer/queue cases,
four expected old peer controls, ten driver methods and the new 46 common cases.
Address/capacity/canary ASan/UBSan, optimized strict-aliasing, formatter18, source pins,
composition and exact reverse tests passed. Input/final worktree/index logs and the
Darwin C/Swift SDK diagnostic logs are empty. Counts include controlled repetitions,
not independent physical-device trials or whole-program sanitizer certification.

Observation-only fixed-unknown results: Linux workers1 passed9/9, workers4 passed8/9
with errno111 on independent closure; macOS workers1/4 each passed8/9 with a timeout
on independent closure. These retained observations do not weaken mandatory gates
or claim that the accepted fixed-port restriction is fixed.

| Original artifact | SHA-256 |
| --- | --- |
| Linux10898695813 | 08fe4e0fd092192a3d403587a6975ed96fd66e7d7ac8b329bcb384cd043054dd |
| macOS10898616717 | 52f4f91d8c19cabb25fa617dd19a9ea6dd3a894dd492bd9064456dac116cae91 |

The archived toolchain and raw per-case outputs remain the execution authority.
No new Simulator, iPhone archive, IPA, physical SideStore or LiveContainer execution
occurred in this dedicated UDP run. Historic failures and exact preceding evidence
remain in the two retained history documents.

## Reproduction, inheritance and unperformed work

From a full Git checkout run `python3 Tests/udp_compat_audit.py`. Historical controls
and ancestry need actual Git objects; a source snapshot alone is insufficient.
Normal product rebuilds use `bash Build/build.sh` and its disposable product copy.
Statistics must inherit this completed owner as a real ancestor with its exact
mapped tests, patches, documents and prerequisite ref. The final release must also
inherit the latest completed owners and run combined checks; standalone success is
not integrated-product success.

Physical signing/install, guest loading, permissions, real IPv4/IPv6/VPN/hotspot,
Moonlight, calls/Bluetooth, lock/suspend/termination, long-duration survival and
energy/throughput remain unperformed for this revision. The four top-level principles
in docs/top-level-principles.md apply without replacing those missing evidence levels.

Primary protocol/address contracts, not execution evidence:
- https://www.rfc-editor.org/rfc/rfc1928
- https://pubs.opengroup.org/onlinepubs/9699919799/functions/recvmsg.html
