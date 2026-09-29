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

## Local execution checkpoint

The runtime has no direct DNS access to github.com, so the local workspace is
reconstructed from prior authenticated source/CI archives. Its native tests are
useful but do not replace remote full-history source guards or Apple execution.
Initial buffered/splice native checks and full111 payload cases passed, as did
24 composed actual-source cases and real mixed/concurrent/restart checks. The new
fixture initially lacked the unmodified hev_malloc prototype before substituting
allocator outcomes; its include order was corrected without changing production
or warnings. The local formatter is clangd17; the original clang-format18 gate
remains authoritative. Fresh combined CI and raw artifacts are still pending.

## Status and limits

This is a checkpoint, not a completion claim. Exact source/run/artifact IDs,
all job outcomes, Simulator results and elapsed retention values will be recorded
after fresh verification. No old passing artifact is relabeled. No IPA, release,
physical SideStore/LiveContainer, real-device background/energy result is claimed.
No evidence currently requires modifying the completed UDP branch itself.
