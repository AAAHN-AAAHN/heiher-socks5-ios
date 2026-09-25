# Latest UDP prerequisite and statistics alignment - 2026-09-23

## Scope and starting state

Statistics starts at `5b6d694a13efb25304689dc8a10e5a2e515e5de4`; the latest
UDP branch is `49784b7c78a99dab824eceeb071e459bc94b2e90`. Both were read from
GitHub before editing. Their source snapshots reconstruct the exact Git trees
`e78f65f593f91cd06e8b8109b2ec209ebe6ce458` and
`098f5f17fee1fb6b5ce1ea2fa2f95714834aa3ae` respectively.

The starting statistics branch used UDP `ae466dab...`, not the latest UDP tip.
GitHub comparison reported a diverged history with two missing UDP commits.
The two UDP runtime patches already matched, so this was not a stale runtime fix.
Three inherited files differed (audit driver, feature specification and copied
root README); the new driver regression and dated follow-up review were absent.
The other seven mapped dependency files already matched.

Only statistics dependency composition, audit wiring and current specifications
change. Main, release, other feature branches and the finalized UDP branch remain
unchanged. No app source, C patch, Xcode/plist, source pin, shared Build file or
committed framework changes. No IPA, app archive or framework build is performed.
The fixed-port limitation, recommendation of local UDP port 0, defaults, DNS policy
and successful-external-I/O measurement contract remain exactly as agreed.

## Complete dependency and merge contract

The statistics merge retains its previous tip as first parent and the latest UDP
tip as second parent. It neither rebases history nor simulates a merge by replacing
only a SHA in documentation. The audit requires UDP to be an actual ancestor.
The following source-to-target mapping is compared byte-for-byte against that pin:

| UDP source | Statistics target |
| --- | --- |
| Patches/hev-udp-port-zero.patch | Same path |
| Patches/hev-udp-sockaddr.patch | Same path |
| Tests/udp_compat_audit.py | Same path |
| Tests/udp_sockaddr_regression.py | Same path |
| Tests/udp_sockaddr_unit.c | Same path |
| Tests/udp_audit_driver_regression.py | Same path |
| Socks5/Info.plist | Same path |
| docs/features/udp-compatibility.md | Same path |
| docs/reviews/udp-compat-20260922.md | Same path |
| docs/reviews/udp-compat-20260923.md | Same path |
| README.md | docs/branches/feature-udp-compat.md |
| .github/workflows/verify-build.yml | .github/workflows/udp-compat-audit.yml |

Build/features.json and the Xcode project intentionally compose two features,
not byte-identical copies of UDP-only files. The existing build manifest retains
UDP's source/base/app pins and exact ordered two-patch prefix, followed by the three
unchanged statistics patches. The project retains its existing statistics source
registration and inherited UDP configuration. Both remain byte-identical to the
starting statistics version. Its root README still equals its own feature spec;
the UDP root README is kept separately without modification.

The original START production freeze remains in force. Its historical review
commit and both prior dated statistics review documents are retained, rather than
rewriting earlier evidence as if it had tested this new dependency snapshot.
The current main-to-statistics inventory is 36 paths: 24 statistics-owned paths and
12 verbatim UDP dependencies. Two newly inherited paths and this report account
for the increase from 33 paths. Old counts in earlier reviews are historical.

## Joint verification without duplicating or weakening the UDP audit

The statistics workflow calls the already preserved UDP reusable workflow with
ref `49784b7c78a99dab824eceeb071e459bc94b2e90`. It uses its existing workflow_call
input and read-only checkout. Both native UDP platform jobs must succeed before
the Linux/macOS statistics matrix starts. The UDP-only guard is not bypassed:
the upstream driver is run on the UDP-only commit, never on a statistics manifest.
No secrets, write permission, alternate relay or new runtime dependency is added.

Statistics audit.py checks its pinned UDP ancestry, all twelve mapped blobs,
source/base/app pin equality, the exact UDP patch prefix and workflow ref/gating.
It then performs the existing native mode, counters, I/O probes, Swift model,
format/reversal and applicable iOS type checks. The earlier stale-success fixes
remain in both drivers. A branch moving later does not silently alter this pin;
future adoption must explicitly update and verify the dependency again.

A new combined run must identify both tested snapshots: the UDP artifact source
and tested-commit.txt must identify the pinned UDP commit, while statistics
artifacts must identify the triggering merge commit. Required profiles, negative
controls and observation-only UDP failures remain distinct. A successful joint
run does not repair the accepted fixed-port/unknown-peer limitation or establish
all-input RFC conformance, iPhone UI/VPN/call recovery or battery/throughput results.
Completion evidence is appended only after inspecting the actual run and artifacts.

## Completed joint evidence

GitHub Actions run `35768013521` completed successfully with four jobs. The UDP
jobs tested exact final UDP commit `49784b7c78a99dab824eceeb071e459bc94b2e90`;
the statistics jobs tested merge `96ed35fadde5643de52b01a522c2129bfd5e0773`.
The run completed at 2026-09-22 18:36:55 UTC (2026-09-23 03:36:55 Asia/Seoul).
The run-level head SHA is the statistics merge even for UDP artifacts; their own
tested-commit.txt and source.zip establish the separate UDP checkout identity.
Neither prior standalone run is counted as a new execution in this joint run.

| Fresh check | Result |
| --- | --- |
| UDP required native profiles, Linux | 58/58 across the six required profiles |
| UDP required native profiles, macOS | 58/58 across the six required profiles |
| Actual UDP C unit, both platforms | ASan/UBSan and separate optimized strict-aliasing runs passed; 65,536 port values and real caller boundary probes |
| UDP audit-driver regression | Five cases passed on each platform |
| Statistics Linux buffered and splice | Ten network scenarios repeated twice in each mode, all passed |
| Statistics macOS buffered | Ten network scenarios repeated twice, all passed |
| Statistics production counter stress | Eight writers and 800,000 updates per native mode, exact totals and concurrent reads |
| Statistics TCP/UDP actual-source probes | ASan/UBSan checks passed in applicable modes |
| Statistics macOS counter TSan | Passed |
| Swift model and pipe reader | 10,000 generated model samples and six pipe scenarios passed on each platform |
| Statistics audit-driver regression | Three cases passed on each platform |
| Source and integration checks | Latest UDP ancestry, 12 exact dependencies, pins, patch prefix, workflow pin/gate and runtime preservation passed |
| Formatting, source reversal and iOS checks | Both audits passed their existing formatter/reversal and applicable ARM64 syntax/project checks; statistics Swift typecheck passed |

The totals are 116 required UDP scenario executions and 60 statistics scenario
executions, not that many distinct specifications or iPhone tests. The complete
four downloaded artifacts matched GitHub's SHA-256 digests. Within each feature,
the Linux/macOS source.zip files are byte-identical. The UDP source has 49 files
and reconstructs tree `098f5f17fee1fb6b5ce1ea2fa2f95714834aa3ae`. Statistics has
70 files and reconstructs tree `62ff8656db830e30439626fc5df00d87f946bca5`.
Both match the verified source snapshots; statistics inventory reports 36 paths,
24 statistics-owned paths and 12 preserved UDP dependencies at the new UDP pin.

| Artifact | ID | SHA-256 |
| --- | --- | --- |
| UDP Linux | 10713146157 | 24cbcc4fb62237b114fc015f0c8d54358ef09836ef70d1e31861ff90fe5fe24a |
| UDP macOS | 10712618276 | 267dacb0167c81ae360c34cee5e108c300901cd46bf30a7d231073f288194eee |
| Statistics Linux | 10713096447 | d6c395cca7da0a7a71f0e259d0b07095e9fd1c8831e2afede116f6d8385ee52f |
| Statistics macOS | 10712458601 | e46e5d941cf91a9879525f6c5400f41c8b95680f4804ac627bb96d572b18bba9 |

The negative controls again distinguish missing port-zero and address repairs.
Unpatched, port-only and address-only ephemeral profiles passed 8/9, 9/9 and 8/9
on Linux and 3/9, 4/9 and 4/9 on macOS. Missing Darwin repairs reproduced the
expected REP=0x01 or wrong-source condition, not an unrelated build failure.
For patched fixed-port unknown-peer observations, all four profiles were 8/9 in
this run: concurrent-close failed with ConnectionRefusedError on Linux (one/four
workers) and TimeoutError on macOS (one/four workers). Linux's unpatched fixed-port
concurrent-close passed, with its only failure in the separate ::1:0 hint case.
These observations stay outside required passes. Differences from earlier trials
do not establish a new fix or exclusive upstream attribution. Port 0 remains the
recommendation; the fixed-port option and accepted limitation are unchanged.

Local tests also passed for the statistics model, statistics driver, pipe reader,
composition and the UDP driver on its UDP-only snapshot. Fifteen local dependency
failure-injection cases rejected altered mapped bytes, workflow ref/gate or patch
prefix; those checks mocked Git/subprocess boundaries and do not substitute for
CI's real Git ancestry checks. A mistaken local invocation of the UDP driver tests
on the statistics checkout was rejected by the unchanged UDP-only guard; its two
errors are retained separately and not counted as passes. The same unchanged test
passed all five cases on the correct UDP checkout. No guard was weakened.

The completion entry is a documentation-only follow-up with CI skipped; it changes
neither the tested executable files nor dependency bytes. Earlier dated review
statements describe their own checkpoints, not an automatic current-status feed.
The UDP branch needs no new commit: its final snapshot was tested directly here.
Statistics now contains that exact final prerequisite in both history and contents.
Main, release, background, settings and icon remain outside this change. Both
features are complete within their agreed scope and explicit operating limits;
no IPA or new runtime feature is part of this dependency alignment.
