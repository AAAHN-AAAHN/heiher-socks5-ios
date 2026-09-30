# Statistics / dynamic UDP integration — 2026-09-29

## Inputs and purpose

Statistics a5c4e6af4f51b64e1e47c0b2c84fd4cc2af661ee and completed UDP
6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5 are the two integration parents.
The purpose is exact existing destination-side payload accounting after inheriting
the four UDP patches, not a new measurement definition or a new UI.

## Identified integration incompatibilities and resolution

The old stats UDP hunks targeted pre-dynamic signatures and direct socket calls.
Blind patch copying would fail to apply. More importantly, placing the In callback
after the new rejection/compaction path would miss reads whose client delivery is
rejected. Out must use the final helper's successful count, including an Apple
sendspace retry, rather than count retries or attempted lengths.

The adapted UDP hunk adds14 lines relative to the new UDP owner: one association
client reference, one lookup at creation, successful-send-prefix accumulation and
raw receive accumulation before filtering. No owner function signature changes are
needed. This lets all mapped UDP source fixtures retain exact owner bytes and
execute against the composed source. Registry and TCP code, public headers, task
and server statistics patches and every production Swift file remain unchanged.
The fourth UDP patch is not edited. No reverse dependency on statistics is introduced.

## Ownership, sources and tests

Seven patches are declared in owner order. The new manifest, prerequisite ref and
all mapped UDP tests/docs/workflow are updated together. The complete old statistics
README is retained byte-for-byte. The new native guard allows only the exact owner
patch in addition to statistics-owned modifications; it still verifies exact byte
identity, real ancestry and the previous production UI/task/server inputs.
The Simulator guard permits the declared native integration, not arbitrary edits,
and separately requires unchanged app/Swift/project bytes since a5c4e6af.

The prior54 size-boundary observations become111 full-length cases, retaining every
former boundary and adding empty,500-byte growth, Apple sendspace and up-to65000-byte
payloads. Each checks exact raw Total and both IP rows. Wrapper failure/cancellation
cases remain unchanged. New real invalid-header/asymmetric/mixed/concurrent/restart
cases check zero destination credit for invalid client input and persistent IP sums.
The actual-source accounting fixture executes dynamic slots with genuine aggregate
and per-IP counters through success, rejected reads, query/allocation failures,
Apple retry, partial client TCP delivery and reclamation. It never replaces the
production counting body. The source-inclusion lifecycle test relays real48001 and
30001byte inputs120s apart, drains actual SOCKS-framed stream replies, and checks
In78002/Out0 before and after actual300s/420s reclamation. Its600s timeout is test-only.

All old required tests, sanitizer scopes, formatter18 and timeouts remain. New
process deadlines apply only to new tests. The exact UDP owner workflow is rerun
as a prerequisite and all its new header/policy tests are also inherited unchanged.
The Simulator test retains small64-byte relays and adds2048/48001-byte payloads;
Total/IP Vol. and Sum must reflect their cumulative exact formatted values in both
orientations. Simulator execution does not certify physical installs.

## Initial local execution checkpoint (historical)

At implementation time the runtime had no direct DNS access to github.com, so
the local workspace was reconstructed from prior authenticated source/CI archives. Its native tests are
useful but do not replace remote full-history source guards or Apple execution.
Initial buffered/splice native checks and full111 payload cases passed, as did
24 composed actual-source cases and real mixed/concurrent/restart checks. The new
fixture initially lacked the unmodified hev_malloc prototype before substituting
allocator outcomes; its include order was corrected without changing production
or warnings. The local formatter is clangd17; the original clang-format18 gate
remains authoritative. Combined CI and raw artifacts were pending at that checkpoint;
the exact-source results below now complete those checks.

## Status and limits

The integration and its scoped native/SDK/Simulator verification are complete.
Exact source/run/artifact IDs, job outcomes, Simulator results and elapsed retention
values are recorded below. No prior passing artifact is relabeled as a new run.
No IPA, release, physical SideStore/LiveContainer or device background/energy result
is claimed. No evidence requires changing the completed UDP branch itself.

## Exact-source verification — 2026-09-29

Run `36550874934`, attempt 1, completed successfully at 2026-09-29T10:09:34Z.
All four jobs passed: independent Linux/macOS UDP prerequisites at
`6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5`, and Linux/macOS statistics at
`c89a2d8bf4dcdae0320d0340bb4f2d9ceb9d4757`. The latter merge has both the prior
statistics owner and this UDP owner as real parents, tree
`be4647c36c54e659d4e6981edf5313306da2345d`. No source rewrite or retry was needed
to obtain the terminal CI result. A documentation-only closure is not a new execution.

Each native mode passed the retained TCP/UDP and registry gates, 111 complete-payload
boundary cases, 24 composed accounting cases in sanitizer and optimized modes, and
18 additional mixed/concurrent/restarted associations. Linux exercised buffered and
splice I/O; macOS exercised buffered I/O plus the applicable ThreadSanitizer gates.
The 111 cases require full original bytes beyond the former 1500-byte limits, not
truncated-prefix success. Normalized peer rows and the aggregate are checked together.
Queries, headers and unused capacity do not count. Successful send prefixes and
actual destination reads remain counted even when later work fails or is rejected.

Actual elapsed reclamation retained Total and peer In=78002, Out=0 after real
48001-byte and 30001-byte inputs and no subsequent payload. Capacity 48500 -> 30500
occurred at 300.103060s on Linux / 300.024134s on macOS after the first input;
30500 -> 1500 occurred at 420.209849s / 420.038323s. The fixture uses its own long
communication timeout, not a changed application timeout. These are observations,
not hard scheduling guarantees under blocked I/O or process suspension.

The unchanged production app also passed one iPhone16/iOS27.0 Simulator XCTest,
zero failures/skips, case time 121.009s, with empty runtimeWarnings and cleanup.
In each orientation it relayed 64, 2048 and 48001 payload bytes through each of
127.0.0.1 and ::1. Portrait Total In/Out=100.226KB and each peer=50.113KB;
landscape after Stop/Start Total In/Out=200.452KB and each peer=100.226KB.
The corresponding Sum cells were checked from the unrounded values. Screenshots,
exact source archives and XCTest results were inspected, not just a status badge.

The native/Simulator toolchain was Xcode27.0 27A266a, iPhoneOS27.0, Swift6.4,
and macOS27.0 26A428. Required C/Swift SDK compiler diagnostic files are empty.
The UI build retains AppIntents metadata-extraction notices; an empty compiler or
runtime-warning result does not mean every tool emitted no diagnostic.

All four original artifact ZIP digests and CRCs were checked. The three statistics
source archives contain the same 110 files and Git modes at the tested merge; both
UDP prerequisite archives contain the same 69-file UDP owner. All 29 mapped UDP
paths and five production Swift files are preserved. Native archives agree on 243
regular-file bytes/modes and 30 symbolic-link targets. POSIX symlink permission bits
differ between host tar formats (0777/0755); Git symlink types/targets, not these
host permission bits, establish their source identity. Compared with the prior
statistics native source, only hev-socks5-udp.c changes. Within that file, the latest
UDP owner gains fourteen statistics C lines and no removals.

Supplementary archive-based Linux rebuilds passed actual-source accounting in ASan/
UBSan and optimized modes, all 111 network cases and the 18-association integration.
Three disposable mutations (skip rejected In, drop partial Out, remove IP attribution)
each fail the unrelaxed oracle. Mutants and test substitutions are not production.
These supplemental checks do not replace the full-history CI or Apple results above.

| Original artifact | SHA-256 |
| --- | --- |
| Statistics Linux11026110312 |09b0421a690186e205a2769c02f14e569684b3d58ce8102d9fdc6f4d45889a33|
| Statistics macOS11024774724 |657475d0b98db511773958a84951cd42b7bf88e56a17cdc465176f8dc76f32f6|
| UDP Linux11025051707 |18fe21af5c73cf440e576d93d74bc2f0adfe091441d2c381912900ee4bb9c679|
| UDP macOS11025317455 |1ef49780f7bd87b82cdf03ba72d91eabf4cb643ea9ce7f2329f2ade460f59095|

No failing mandatory case remains in this executed integration scope. Existing
fixed-port unknown-peer association lifetime restrictions, valid same-IP first-peer
races, independent live snapshot reads, process-lived IP-registry growth, wire/path
bounds and allocation failures are not eliminated. No claim is made for physical
SideStore standalone or LiveContainer guest execution, device background/power or
maximum throughput. No IPA or release integration occurred. Other branch heads are
unchanged. The operational statistics boundary remains successful destination-side
payload I/O, not all application or interface wire traffic and not remote delivery ACKs.

## Documentation closure and correspondence

This closure changes only README.md, its byte-identical feature specification and
`docs/reviews/statistics-dynamic-udp-20260929.md`. All other 107 of the 110 tracked
paths retain the tested commit's exact bytes and Git modes, including the runtime,
all seven patches, tests, workflows and pinned dependencies. The completed UDP
owner remains `6f9848e42fb221b21ea31ce8ab8b00333cc0ecd5`.

The publication commit descends directly from the tested statistics merge
`c89a2d8bf4dcdae0320d0340bb4f2d9ceb9d4757`. Its own Git metadata supplies the final
commit/tree identity; the run above supplies execution evidence for the unchanged
code. No new runtime execution is claimed for this documentation-only commit.
