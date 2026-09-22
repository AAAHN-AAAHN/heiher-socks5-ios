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
