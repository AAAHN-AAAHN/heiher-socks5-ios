# UDP compatibility for the native iOS SOCKS5 relay

## Current disposition: reconciled peer filtering (2026-09-24)

The current feature applies **three** ordered patches: the two preserved port-zero
and address-normalization repairs, followed by `hev-udp-peer-filter.patch`.
The new source-IP/established-port filter is retained, but not the first unfinished
implementation: its all-discarded-batch path has been corrected to yield, observe
cancellation and keep draining the existing receive queue. No new dispatcher,
listener, automatic port fallback or change to the fixed-port policy is introduced.

Current tested source is `e29458bc58cba822c31a0106a29f291cc34d6170`, run
`35947538898`, with successful Linux and Xcode 27 jobs. Read the final reconciliation
section below for behavior, cost, controls and limits. The intervening earlier
records describe their original two-patch snapshots, not today's three-patch
implementation. Historical IPA/Simulator results are not new peer-filter device tests.

## Supported versions, installation environments and verified scope

Latest environment re-audit: **2026-09-23**. The intended support environment,
configured minimum OS, SDK build and actual runtime tests are different claims.
The native-only audit descriptions later in this document describe their own
scoped checks; the separate re-audit below also built IPAs and ran Simulator tests.

| Boundary | Version/environment and evidence |
| --- | --- |
| Configured minimum iOS | **17.2**, unchanged. This deployment target is not evidence that every iOS version from 17.2 onward was tested. |
| Primary intended environment | **iOS 27.0 on a physical iPhone**, installed independently with **SideStore** or run as a **LiveContainer guest**. These are separate installation/execution paths, not interchangeable with Simulator or Xcode installation. |
| Verified iPhone build | **Xcode 27.0 (27A266a), iPhoneOS SDK 27.0, ARM64**. The unchanged production build produced an IPA; archive identity, metadata, linkage and ZIP integrity passed. |
| Verified runtime | **iOS 27.0 Simulator (24A434)**: the actual app launched with its original Bundle ID and a controlled remapped ID. The native-relay test shell used the same rebuilt library bytes as the app. This is not the owner's physical 27.0 (24A437) build. |
| SideStore status | Installation-related source/dependency review and controlled ID-remap tests completed. Actual SideStore signing, provisioning, installation and physical-device launch were **not performed**; no specific installed SideStore version is certified. |
| LiveContainer status | Host/guest dependencies were reviewed. Actual loader transformation, JIT-less signing, host permissions, installed version/options and physical guest execution were **not tested**. No blanket LiveContainer compatibility certification is claimed. |

Verified functional scope: Linux and Darwin each passed **58/58** required UDP
profile scenarios. Actual-source address/port probes, sanitizer and optimized
strict-aliasing checks passed. The iOS 27 Simulator native fixture passed **36/36**
scenario executions across original/remapped IDs and ephemeral/fixed-known-port
profiles. These are scoped results, not whole-app UI or physical-network tests.

The accepted fixed-port/multiple-unknown-client association limitation remains;
use **UDP Listen Port = 0** for that workload. Local-network permission on the
actual device/host, hotspot and concurrent VPN behavior, physical IPv4/IPv6 paths,
production Start/Stop interactions, lock-screen survival and energy/throughput
measurements remain outside this re-audit. Earlier owner observations below do not
establish full coverage of both installation paths at this exact code revision.

This UDP-only branch contains no statistics or Background feature. It makes no
BGTask/NetworkExtension request and adds no feature-specific signing entitlement or
host-ID requirement. No BGTask whitelist, forced LiveContainer Bundle ID option
or host IPA edit is required by this implementation. Ordinary installer signing
and local-network permissions still apply. Continuous background operation needs
the separately maintained `feature/background` (silent audio/location) composition;
this review neither merges it nor certifies `release/integrated` as a whole.

Tested production revision: `49784b7c78a99dab824eceeb071e459bc94b2e90`.
Evidence: [run 35815248222](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/actions/runs/35815248222)
completed with **all four jobs successful**. Its audit-control commit is
`c644dcfa8976094e8443511c3f4c869536a34d5b`, not the production revision above.
The [immutable full review](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/7b397d0251ca0f167b93ed2e4a8713c3599e977c/Validation/FINAL-REVIEW.md)
records toolchain, tests, known limits, artifact hashes and earlier failed attempts.
Adding this support record changes documentation only, not the tested executable
sources, deployment target or previously delivered IPA.

**README maintenance rule:** for future code or verification changes, update this
section and its identical feature-document copy with the minimum OS, intended
installation paths, exact tested OS/build and tool/host versions (or explicitly
unknown), tested commit/run, passed/failed/not-run scope and remaining limits.
Keep SideStore standalone, LiveContainer guest, SDK/Simulator and physical-device
evidence separate. Never promote a successful build into unperformed device tests.

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

## Final operating policy

The owner has chosen to finish this feature with the existing two runtime patches
unchanged and to retain the documented fixed-port limitation. This is an accepted
operating constraint, not a claim that the failing condition has been repaired.
No shared UDP dispatcher, association-ID extension, automatic port fallback, or
client change is added. This documentation does not change any UI default or saved
port value and does not alter the release branch.

**Recommended setting: UDP Listen Port = `0` (`udp-port: 0`).** This is the normal
recommendation when reliable separation and independent closure of several SOCKS5
UDP associations are required, particularly when clients advertise port zero.
A bound ephemeral endpoint separates associations by their local relay endpoint.
This resolves the tested shared-endpoint ambiguity; it does not authenticate the
first packet or repair the other protocol/security limits listed below.

| Requested use | Existing behavior and operating guidance |
| --- | --- |
| UDP Listen Port `0` | The OS selects a local UDP relay port when each association is created. Concurrent unknown-port and independent-close profiles passed. Recommended for general use. |
| Fixed UDP Listen Port; clients advertise distinct, accurate source endpoints | The initial peer can be connected before UDP traffic. Tested concurrent known-port profiles passed. The advertised endpoints must match what the server actually sees. |
| Fixed UDP Listen Port; one active unknown-port association | Can work, including the owner's earlier Moonlight test. One successful session does not establish multi-association safety. |
| Fixed UDP Listen Port; several unknown-port associations | Remains selectable, but first-peer ownership may be ambiguous. Actual tests include timeouts and connection-refused errors; closing one association can disrupt another. Use only with this limitation understood. |

A fixed port is **not** a reliable catch-all mode that merely sacrifices attribution
or statistics. The current implementation still has separate sockets and lifetimes
for separate TCP control connections; it does not merge them into one long-lived
public receiver. Loss of ownership clarity can therefore affect real delivery and
closure. The possible kernel/first-peer assignment explains the failure plausibly,
but this review does not claim a complete packet-by-packet causal trace.

Here, multiple associations means multiple SOCKS5 UDP ASSOCIATE control sessions,
not simply multiple UDP destinations or packets. One association may carry many
destinations. Ordinary SOCKS5 UDP datagrams have no TCP-association identifier;
a flow lookup by source IP/port alone cannot unambiguously identify which of
several same-IP, unknown-port control connections created that flow.

Example (the TCP port is illustrative, not a changed application default):

```text
Server Listen Port: 9876
UDP Listen Port:    0
Client SOCKS5 entry: 172.20.10.1:9876
```

The client first negotiates with TCP port 9876 and then sends UDP to the endpoint
returned in BND.ADDR/BND.PORT. Users do not discover or manually enter each allocated
UDP port. Port zero does not mean one new port or socket per packet, nor does it
close the TCP listener. Hev already allocates a client-facing UDP socket for each
association even with a fixed port; selecting zero adds no second relay layer.
The path/firewall must allow the negotiated UDP endpoint. If an environment permits
only one fixed UDP port, that deployment restriction and the above concurrency
limitation must both be considered; this implementation does not evade either.

The local UDP Listen Port is independent of the client port zero in the ASSOCIATE
request. Using local port zero does not make the existing port-zero guard optional.
A successful scoped audit closes this feature under these stated conditions, not
as unrestricted fixed-port, full-RFC, or security-conformance approval.

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

The branch entered the original review with eight differing files and closed it
with twelve. The follow-up has 14 differing paths. Every changed file is part of
the review, not just the C text.

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
| `Tests/udp_audit_driver_regression.py` | Five rejected/failed-attempt cases verify stale-success invalidation and log preservation. |
| `docs/reviews/udp-compat-20260923.md` | Follow-up review, exact runtime preservation and separately identified fresh evidence. |

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
others, and three bursts of 24 unordered datagrams. The six payload trials
(1, 64, 512, 1200, 1400, then 64 bytes again) and IPv4/IPv6 TCP cases are retained. Shared fixed ports with advertised known
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

On entry to main, the driver removes an earlier SUCCESS.txt before validating or
rejecting the attempt; failed retries must not reuse an old pass marker. Earlier
diagnostic logs are retained. Five test-only cases cover an existing checkout,
unrelated composition, a failed source command, fresh failure, and Python -O.
Require successful process/job exit and matching source, summary and logs as well
as the marker. This guard does not cover import failures before main or arbitrary
filesystem failure. Use separate clean checkouts, not concurrent audit attempts.
The follow-up results and preserved runtime hashes are documented in
`docs/reviews/udp-compat-20260923.md`; earlier runs remain historical evidence.

## Explicit remaining limits

| Condition | Status and consequence |
| --- | --- |
| Several unknown-port associations share one fixed UDP relay port | Concurrent failures are reproduced with both patches. The existing SO_REUSEPORT/first-datagram design permits ambiguous session ownership, but the controls do not prove exclusive upstream causation. Ephemeral local ports passed the tested profiles. |
| First packet before peer establishment | The minimal design does not check that its source IP matches the TCP control peer before learning it. Connected UDP then filters the selected peer, but that is not initial authentication. Do not expose the listener to untrusted devices. |
| SOCKS fragment/reserved fields | These patches do not introduce a FRAG/RSV validation or reassembly policy. The pinned parser's existing behavior is not a full RFC 1928 conformance guarantee. |
| Large/empty datagrams | The original 1500-byte relay buffers, truncation handling and rejection of empty outgoing payloads are not redesigned. The tested payload sizes do not establish arbitrary UDP payload support. |
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


## Six-feature closure recheck (2026-09-24)

The six-feature review found no new defect in the two scoped runtime repairs.
It did find that this branch's regular macOS audit still selected macos-15 and
exposed all of LLVM18/bin. The workflow now selects xcode-27, exposes only the
required clang-format-18 executable, records/asserts iPhoneOS SDK 27 and adds an
actual ARM64 Swift typecheck. Runtime C/Swift, assets, defaults, source pins,
patches and existing test expectations are unchanged. No app or IPA is built.

Tested commit `f5d9d32e8fe1ae743ed9647c589ca5fabf634502`,
tree `62d426f35679d3be3af92ae77a106ddfb04fd9a4`, run `35928444327`:
Linux and Xcode27 jobs both succeeded on the first attempt. Each platform passed
58/58 mandatory protocol scenarios, the actual-source 65,536-port/caller probes
with ASan/UBSan and optimized strict aliasing, driver failure controls and patch
reversal. Fixed-port/multiple-unknown associations again failed observation-only
profiles; their documented accepted limitation and port-zero recommendation remain.
This result is not an unrestricted protocol/security approval.

Xcode 27.0 `27A266a`, iPhoneOS 27.0, Apple Swift 6.4 and macOS 27.0 `26A428`
were recorded. Actual C syntax and Swift typecheck logs contain no diagnostics.
The Linux artifact `10778964876` SHA-256 is
`e4b5bc541915b0f05b6d96b4fa300eddfe0528c76b64983b2f674f20c2626909`;
macOS artifact `10780450446` SHA-256 is
`492abfb41fde147aa3e46305b0ce21bb2fdaea700a3fab5a1166d9d11b3c9ff6`.
Both 49-file tested source archives match the reviewed snapshot.

The finalized UDP owner is then included as a real ancestor of traffic-statistics,
with its current reusable workflow, exact dependency files and documentation.
No dependency on server-control, persistence, Background or app-icon is introduced.
main and release/integrated stay excluded. This fresh native/SDK recheck did not
repeat the historical IPA/Simulator experiment or perform physical iOS 27
SideStore/LiveContainer installation, VPN/hotspot, lock-screen, UI or energy tests.
The section above dated 2026-09-23 remains evidence for that earlier, separate run.

## Reconciled foreign-peer and queue handling: final evidence

The separate work beginning at `d5b5bad3` and `bfa4c606` was reviewed by content.
Its useful change is accepted: an unknown-port association must not learn a first
UDP sender from a different IP than its TCP control peer. After establishment,
source IP, scope and port are checked for each received descriptor, including
packets queued before connect. The two original patch files remain byte-identical.
This explicitly supersedes the historical unchecked-first-IP row above, but is not
cryptographic authentication, protection against a same-IP first-port race, or a
complete RFC/security approval. Clients must send UDP from the expected source IP;
a deployment with unrelated TCP/UDP egress IPs is not silently exempted.

The first candidate's all-discarded batch incorrectly signaled an empty receive
queue. On Darwin, a legitimate datagram could remain behind rejected queued packets
without a new readiness wakeup. The accepted implementation uses the existing
coroutine yielder (including stop/cancellation handling), then retries the same
receive operation. A real empty queue still yields its real I/O result. It does not
sleep on a timer, allocate another socket, invent EAGAIN, increase deadlines or
remove the queued-continuation assertion. The final unit covers repeated rejected
batches, subsequent genuine EAGAIN and cancellation, in sanitizer and optimized
builds. The raw-socket queue observation remains test-only evidence, not a production
workaround or an assertion that every OS queue must behave identically.

`getpeername` is added once per nonempty received batch; stack source-address storage
scales with the existing fixed batch size. Each candidate source is normalized and
compared; accepted descriptors are compacted without copying payload bytes. This
adds real CPU/stack/syscall work, but no heap history, new worker, timer, lock,
dispatcher, saved option or per-packet logging. No energy/throughput benchmark is
claimed. Source-IP validation belongs to this existing UDP receive boundary, not to
Settings, Background or a new cross-feature manager.

Tested commit: `e29458bc58cba822c31a0106a29f291cc34d6170`.
Tested tree: `ced588e00b2d114d002471b4c3a95f74b693aae3`.
Run `35947538898`: Linux and Xcode 27 jobs both succeeded. Per host, 58 required
legacy scenarios and all eight new actual peer/queued-continuation cases passed.
Four old-code peer controls reproduce the previously accepted foreign sender.
The fixed-port/multiple-unknown limitation remains a separate failing observation.
Actual C normalization/caller/sender/cancellation probes passed ASan/UBSan and
optimized strict-aliasing builds. Patch format and reverse checks passed. The
recorded Xcode 27.0 `27A266a`/iPhoneOS 27.0 C syntax and two-file Swift ARM64
checks passed; their logs are empty. No app archive, IPA or new Simulator test ran.

The initial peer candidate's Linux formatter failure and Darwin queued-continuation
failure are not erased. The next queue-corrected revision still failed a new unit
assertion's formatting. The last change split only that assertion to match the
existing formatter. Final success is not a claim that all earlier runs succeeded.
Both downloaded final artifacts were checked against these digests and exact source:
- Linux `10786914702`: `eea1c93267a80f4aa387c6c4b9db38c11b9069f975a5e55298ec7c1b4b1d827a`
- macOS `10787258304`: `54f980d14f6ad658ae3a92ee5016d41f742ff5e0bd815912b71c1e63bf491840`

This final record changes only README and its identical feature specification;
production/test/workflow bytes remain the successful revision above. The completed
owner must be explicitly included by statistics; its prior two-patch pin is not
considered current merely because the original compatibility repairs are unchanged.
No main/release update, new branch, IPA, host patch or implicit device certification
is part of this reconciliation. Physical iOS 27 SideStore/LiveContainer execution,
VPN/hotspot, permissions, same-IP adversaries and all protocol edge cases remain
outside the executed evidence. The eight-branch ownership boundary is preserved.

## Final six-feature verification closure (2026-09-25)

The current three-patch implementation required no further runtime change. Fresh
verification commit `f85cce5818ca1ea448f699e7bb73c550d6c047af` uses exactly the
input owner's tree `8ebafb9784d62d670e49375dc0a5d4f97468a53c`. Run
`36055973873` passed Linux and Xcode 27 on its first attempt. All 58 mandatory
compatibility scenarios and eight peer/queued-continuation cases passed per host.
The existing five audit-driver controls, old-code comparisons, address/cancellation
sanitizers, strict formatter and exact reverse-patch checks also passed. Accepted
observation-only fixed-port/unknown-client failures remain observations, not passes.

Both downloaded artifact ZIPs passed integrity checks. Their complete 52-file
Git source archives independently reconstruct the tested tree, including executable
modes; the archives identify the matching tested commit. This verification does
not invent a source-manifest file that the UDP artifact does not contain.
- Linux `10831884151`: `391b398d44cc45bfb72bf09d726a91a3e0851e1cef67f46754d508a4966a3cf4`.
- macOS `10831874251`: `841612bda5cac742143c287eaee1e45eb4c8b60952bbb44fe64d82621d1d70f9`.

The macOS job recorded Xcode 27.0 `27A266a`, iPhoneOS SDK 27.0, Apple Swift 6.4
and macOS 27.0 `26A428`. The unchanged app passed its actual iOS27 type check.
No Simulator, physical device, app archive, IPA or XCFramework was built here.
The iOS17.2 deployment minimum, intended physical iOS27 SideStore/LiveContainer
paths and previously unperformed permission/UI/VPN/hotspot/lock/energy tests remain
separate claims. Source-IP filtering does not certify same-IP first-port races.

This completion appends only to README and its identical feature specification;
all preceding evidence and all production/test/workflow bytes are preserved.
Statistics must inherit this completed owner as an actual ancestor and match its
fifteen mapped files. The accepted UDP Listen Port=0 operating guidance, baseline
source pins, branch count, main, release/integrated and existing IPA are unchanged.
