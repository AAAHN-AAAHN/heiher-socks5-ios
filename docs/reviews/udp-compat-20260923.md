# UDP compatibility follow-up verification - 2026-09-23

## Scope and source identity

This follow-up starts at `ae466dab1a394af0c83f3dc36e51755f25f91910` and preserves
the owner's final operating decision: retain the two runtime patches, recommend
local UDP Listen Port 0, retain the fixed-port option and its accepted concurrent
unknown-peer limitation, and change neither defaults nor saved settings. No
shared dispatcher, association-ID extension, automatic fallback, or client change
is added. Only UDP-owned audit code and documentation may change in this review.

Main is `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`; release is
`b59e3f1b61ae342a944d96f0da24b1908c2b3eac`. Statistics remains at
`5b6d694a13efb25304689dc8a10e5a2e515e5de4` and continues to reference its frozen
UDP prerequisite. This follow-up does not propagate new UDP audit files into
statistics or release, change other branches, rebuild the committed framework,
or create an IPA. The existing native-only workflow is retained.

The prior Linux/macOS artifacts for run `35702373232` were downloaded and their
SHA-256 values matched GitHub. Their identical source.zip files contain 47 files
and reconstruct tree `90ae55653484591f7b3831d756ffa2d034ba81f1`, the exact starting
snapshot. The twelve original main-to-feature paths, both complete patches, the
native network tests, actual-C unit, source/build manifest, project/plist and
specifications were re-examined. No approximation of remembered code is used.

## Runtime and caller/callee review

The first patch preserves local bind, socket options, address selection, errors,
nonzero peer connect and reply construction. It skips only the premature connect
to remote client port zero; the existing association state and first-datagram
path perform peer establishment. Local listen port zero is a different setting.
The association reply is not delayed until a client packet arrives.

The second patch's normalization helper receives full-sized sockaddr_in6 storage
at both call sites. Its small IPv4 temporary avoids overlapping source/destination
conversion; port and address bytes are preserved, scope/flow are cleared for IPv4,
and Darwin length is set. Native or mapped IPv6 remains byte-identical. The first
peer is normalized before connect; external sources are normalized before SOCKS
serialization. Every reusable external address capacity is reset before receive,
including an EAGAIN retry. Buffer sizes, payload bytes, coroutine/yield behavior,
allocation, socket ownership and protocol parsing remain the existing design.

The native controls and unit are complementary: real Darwin socket behavior
separates the two defects, while scripted OS boundaries exercise the actual C
translation unit's state, address memory, failed connect and capacity reuse. They
are not independent reimplementations of the helper. The test harness bounds
startup and subprocess execution, records individual failures and cleans up the
server. The six payload trials contain five distinct sizes; 64 bytes is repeated.
Observation-only fixed-port failures are not required-pass results.

No scoped runtime defect requiring a patch change was identified. Both C patches,
the native network/unit tests, app Swift sources, project/plist, Build files, source
pins and baseline framework are unchanged. Existing source-IP/FRAG/RSV, 1500-byte
buffer/truncation, empty-payload and explicit address-family binding limitations
remain outside these two repairs. This is not full RFC/security certification.

## Reproduced audit-driver defect and minimal correction

An old SUCCESS.txt survived when a new audit was rejected (existing core,
unrelated composition, or optimized Python) or its first source command failed.
That can place an old pass marker beside a failed attempt, including a retry at
the same commit. This does not invalidate the earlier clean CI success.

The driver now invalidates that marker at entry to main, before these guards.
It retains earlier diagnostic logs and all existing native checks. A new test-only
script invokes the actual driver with temporary paths and a deliberately failing
command boundary, plus an actual Python -O subprocess. Before the fix, four of
five cases failed; after correction all five passed. A fresh failure with no old
marker is also covered. These tests are not network or iPhone measurements.

The driver adds three lines: a comment, marker invalidation, and invocation of
Tests/udp_audit_driver_regression.py. The new test and this document are not app
resources. The two canonical specifications stay byte-identical and list all
fourteen paths now differing from main. Old review logs/documents remain intact.

The success marker alone is never sufficient evidence: require a successful
process/job exit, matching tested-commit.txt and source.zip, summary.json and the
individual logs. The entry cleanup covers attempts that enter main, not import
failures before main or arbitrary filesystem failure. Concurrent attempts in one
working directory are unsupported; use a clean checkout for each native audit.

## Earlier observation, accurately attributed

In run `35702373232`, all required profiles passed 58/58 on Linux and 58/58 on
macOS. The patched fixed-port/unknown-peer observations were 9/9 on Linux with
both one and four workers, but 8/9 on macOS in both cases: the concurrent-close
scenario timed out. Linux's unpatched fixed-port profile was 7/9 and failed the
concurrent-close and ::1:0 hint cases. Those outcomes differ from earlier runs
recorded in the 2026-09-22 review; neither set is rewritten or generalized.

The same runtime can pass some shared-port trials and fail others. A passing
observation is not a repair of the accepted limitation, and a failed control is
not sufficient to assign every patched failure exclusively to upstream code.
The port-0 recommendation and the fixed-port option are unchanged.

## Local checks and completion evidence

The new red/green driver regression passed after correction. Source tree identity,
Python syntax, app composition and unchanged-runtime checks were also performed
locally. GitHub could not be resolved by git in the local container, so a new full
native/Linux/macOS audit is performed by the existing GitHub Actions workflow.
Fresh completion is established only by its matching jobs and downloaded artifacts;
results are appended after inspection, not declared in advance.

## Completed fresh audit

Run `35765748273` completed successfully on Linux and macOS at commit
`b6929811a11c30ed8b519d062b9d869caae7be21`. Both jobs, downloaded artifact digests,
tested-commit.txt, source.zip, SUCCESS.txt, summary and individual logs were checked.
This completion entry is documentation only; it does not represent another test
execution. All executable files remain at that tested snapshot.

| Required two-patch profile | Linux | macOS |
| --- | --- | --- |
| Ephemeral relay, one worker | 9/9 | 9/9 |
| Ephemeral relay, four workers | 9/9 | 9/9 |
| Unbound external socket, mixed families, one worker | 11/11 | 11/11 |
| Unbound external socket, mixed families, four workers | 11/11 | 11/11 |
| Fixed relay, known client ports, one worker | 9/9 | 9/9 |
| Fixed relay, known client ports, four workers | 9/9 | 9/9 |
| Required scenario executions | 58/58 | 58/58 |

These are 116 required scenario executions across two platforms, not 116 unique
specifications or device measurements. The existing actual-C unit passed under
ASan/UBSan and separately at -O3 with strict aliasing on both platforms: 65,536
port values, selected IPv4 address bytes, canaries, idempotence, IPv6 scope/flow
preservation, EAGAIN/connect failure and all ten reusable address capacities.
The five new audit-driver tests passed on both platforms. C formatter equality,
source/baseline checks, composition, patch reversal, Darwin project/plist lint and
ARM64 iOS syntax-only compilation passed. No new application link/archive,
Swift runtime, on-device VPN/Moonlight test or energy benchmark is implied.

Negative controls remain distinct from required passes. In this run the ephemeral
unpatched/port-only/address-only controls passed 8/9, 9/9 and 8/9 on Linux, versus
3/9, 4/9 and 4/9 on macOS. On Darwin, missing normalization still produces the
wrong IPv4 source, and missing the port-zero guard still produces REP=0x01 for an
unknown peer. These are specific reproduced failures, not arbitrary build errors.

| Patched fixed-port, unknown-client observation | Result in this run |
| --- | --- |
| Linux, one worker | 8/9; concurrent-close failed with ConnectionRefusedError |
| Linux, four workers | 9/9; no failure in this trial |
| macOS, one worker | 8/9; concurrent-close timed out |
| macOS, four workers | 8/9; concurrent-close timed out |

Linux's unpatched fixed-port concurrent-close case passed in this run; its 8/9
profile failure was the separate ::1:0 hint. That does not overwrite the preceding
run's failure or prove the patched behavior regression-free. The accepted fixed-port
limitation remains open as an operating constraint, not an unfinished hidden pass.

The Linux artifact SHA-256 is
`a275a7a9a57851ed28e2cf39a0c3bfeab91d9463dc21a4ac6490f059d2adc4aa`;
the macOS artifact SHA-256 is
`c62c9fbd4b9efba4f4adee5bf5ec26e4e22f03794ffc737de175a91496611342`.
Both match GitHub's digests. Their source.zip bytes are identical; the 49 files
match the reviewed candidate and reconstruct tree
`4eeb61e4fdd72dd8d50f2ad5417a5aca3c16aae6`. Reversing the original full branch diff
also reconstructed the common main tree `aa9eacf47cc964c5b1c8be7248ae88e79aa0e7be`.
The fourteen-path current inventory was checked against that exact baseline.

Preserved runtime patch SHA-256:

```text
9cd0a43550a6128046f81d11bd16971e426386e2656e3e8f16fa790d57bbb315  hev-udp-port-zero.patch
0b2088e6f0519fe01d9d0c64d0bda4cc5909f292ed9095613a1b2434f930ac0e  hev-udp-sockaddr.patch
```

After the fresh run, all six non-UDP branch tips remained at their starting SHAs.
The source delta is limited to the audit driver, its new regression, the two
identical feature specifications and this review. Neither runtime patch, native
network/unit probe, application, defaults, shared build infrastructure, existing
workflow nor baseline framework changed. The final disposition is completion of
the agreed two-repair feature audit with its explicitly accepted limitations.
