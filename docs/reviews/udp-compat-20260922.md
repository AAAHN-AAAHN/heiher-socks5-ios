# Focused UDP compatibility final audit - 2026-09-22

## Identity and scope

- Main baseline: `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
- Feature entering review: `3a76532c14826f8938b0977d30c8d94143bdfeea`.
- First complete cross-platform audit: `09f0e173067d49e235b59f7ffe99b2dfa26f82e4`.
- Evidence: GitHub Actions run `35695795618`, Linux and macOS artifacts.
- Release to preserve: `b59e3f1b61ae342a944d96f0da24b1908c2b3eac`.

Only this feature branch is changed. There is no new IPA or XCFramework build.
Native C test/server compilation is deliberately separate from distribution builds.
The following final commit formats the new unit test, enforces that format, pins
checkout to the triggering SHA and removes an unused artifact-name step. It runs
the same audit again; use that run's `tested-commit.txt` for its exact identity.

## Disposition

The two existing runtime patches remain byte-identical. Their scoped compatibility
behavior, caller buffer contracts, error handling and project C style pass review.
The audit does NOT approve unrestricted shared-fixed-port operation or complete
SOCKS5 protocol/security conformance. New tests and documentation were necessary:
the former eight-case suite did not exercise fixed-port concurrency, mixed address
families in the same outbound socket, bursts or deterministic receive-buffer reuse.

Initial diff versus main: eight files, all inspected. The manifest selects only
the two UDP patches; both source patches are unchanged; the README and feature
specification now explain all limitations and exact semantics; Xcode/Info.plist
changes are only the existing local-network/single-scene configuration; the old
native regression test is expanded. New audit/unit-test files and this report are
not in the app target. The branch-specific workflow now performs native-only checks.
Common build/check scripts, source locks and committed baseline framework stay equal
to main. Original app Swift sources, TCP relay implementation and public API are not
modified. The complete initial file list is in the root README.

Runtime patch SHA-256:

```text
9cd0a43550a6128046f81d11bd16971e426386e2656e3e8f16fa790d57bbb315  hev-udp-port-zero.patch
0b2088e6f0519fe01d9d0c64d0bda4cc5909f292ed9095613a1b2434f930ac0e  hev-udp-sockaddr.patch
```

## Actual complete-run results

Counts below are scenario executions, not unique specifications or physical-device
measurements. Every required patched scenario passed on both host platforms.

| Required two-patch profile | Linux | macOS |
| --- | --- | --- |
| Ephemeral relay, one worker | 9/9 | 9/9 |
| Ephemeral relay, four workers | 9/9 | 9/9 |
| Unbound external socket, mixed IPv4/IPv6, one worker | 11/11 | 11/11 |
| Unbound external socket, mixed IPv4/IPv6, four workers | 11/11 | 11/11 |
| Fixed relay, known concurrent client ports, one worker | 9/9 | 9/9 |
| Fixed relay, known concurrent client ports, four workers | 9/9 | 9/9 |
| Total required executions | 58/58 | 58/58 |

Negative controls, which are not release passes:

| Missing repair | Linux passed/total | macOS passed/total |
| --- | --- | --- |
| No patches, ephemeral relay | 8/9 | 3/9 |
| Only port-zero guard | 9/9 | 4/9 |
| Only address normalization | 8/9 | 4/9 |

On macOS, removing the port-zero guard reproduces REP=0x01 for unknown peer ports.
Removing normalization reproduces `[::]` instead of the actual IPv4 reply source.
Linux passing the port-only case cannot validate Darwin's address representation.

## Confirmed remaining shared-port limitation

The fixed-relay/unknown-concurrent-peer observation yielded 8/9 on Linux and macOS,
with either one or four workers. The failing scenario creates three associations,
queues their first datagrams and later closes one; a remaining exchange times out
or is refused. Linux's unpatched server also fails this shared-port scenario.
macOS's unpatched control fails earlier at association setup, so it cannot isolate
that later demultiplexing behavior without the compatibility repairs.

The existing SO_REUSEPORT sockets and first-datagram selection permit ambiguous
association ownership before peer connect. This is a source-derived explanation
consistent with the observed failures, not a packet-by-packet kernel trace. A full
solution preserving a shared port would require additional association/demultiplexing
policy; silently forcing a different user-selected port would change semantics.
Those changes are not hidden inside this narrowly agreed minimal guard. For multiple
unknown-port associations the tested isolated-port configuration is `udp-port: 0`.
Passing single-session Moonlight tests at a fixed port does not establish this
concurrent property. Observation failures remain visible in `summary.json` and
are deliberately not added to the 58 required passes.

## Memory, state and style checks

The actual patched C translation unit passes AddressSanitizer and
UndefinedBehaviorSanitizer in the exercised paths, plus `-O3 -fstrict-aliasing`.
All 65,536 port values are checked with varied IPv4 bytes, canaries, mapped address
construction, idempotence and unchanged IPv6 scope/flow information. Scripted OS
boundaries exercise the real first-peer function with EAGAIN and connect failure,
and the reply function with shortened address capacities and alternating families.
All ten vector address capacities must be restored before receive. Linked support
libraries are not presented as fully sanitizer-instrumented. Whole-app safety and
all unexecuted error paths are not proved by these probes.

The two production C files match their pinned upstream clang-format-18 output.
The unit test is formatted and checked the same way. Native builds and unit checks
pass without unit compiler warnings. Patch reversal restores exact upstream files.
The first attempted workflow had a test-harness whitespace false positive on the
mandatory single-space blank context lines inside unified patch files; the runner
now excludes patch text from that check, while still checking actual patched C via
git apply whitespace validation and clang-format. It was not a production defect.

The documented residual source-IP/FRAG validation, 1500-byte buffering/truncation,
empty payload and explicit address-family bind limits are not silently repaired or
claimed compliant. There is no new timer, socket, payload buffer, queue, per-packet
allocation or task. Existing address-copy/reset instructions are retained because
they fulfill the buffer/API contract; no absolute CPU/battery optimum is claimed.

## Reproduction

```sh
python3 Tests/udp_compat_audit.py
```

Use a clean checkout with the documented native toolchain. Every result carries
its profile and failures; the final audit logs the tested commit. No invocation of
build-apple.sh, xcodebuild archive, or IPA packaging occurs in this audit workflow.
Main and release must be checked again after publication to confirm they did not
move. Root README and `docs/features/udp-compatibility.md` are identical feature
specifications; this report records the concrete audit outcome and qualification.
