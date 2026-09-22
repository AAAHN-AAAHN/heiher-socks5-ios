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
