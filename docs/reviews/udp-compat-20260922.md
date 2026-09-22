# Focused UDP compatibility final audit - 2026-09-22

## Identity and scope

- Main baseline: `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
- Feature entering review: `3a76532c14826f8938b0977d30c8d94143bdfeea`.
- Completed pre-resumption audit: `baaa2c49fc559223904fcf6dadc447be08efd2e2`.
- Its evidence: GitHub Actions run `35696504942`, Linux and macOS artifacts.
- Release to preserve: `b59e3f1b61ae342a944d96f0da24b1908c2b3eac`.

The interrupted chat response did not mean that repository work had failed. The
commit above and its native-only audit completed successfully before the missing
completion report. This says nothing about the internal cause of ChatGPT's failure;
no request termination code or service trace is available in the repository.

Only this feature branch is changed. There is no new IPA or XCFramework build.
Native C test/server compilation and iOS syntax-only checks are deliberately
separate from distribution builds. Every audit artifact records `tested-commit.txt`.

## Disposition

The two existing runtime patches remain byte-identical. Their scoped compatibility
behavior, caller buffer contracts, error handling and project C style pass review.
The audit does NOT approve unrestricted shared-fixed-port operation or complete
SOCKS5 protocol/security conformance. New tests and documentation were necessary:
the former eight-case suite did not exercise fixed-port concurrency, mixed address
families in the same outbound socket, bursts or deterministic receive-buffer reuse.

Initial diff versus main: eight files, all inspected. Final diff: twelve paths,
including the native-only workflow, audit driver, C unit and this review document.
The root README lists every path. Common build/check scripts, source locks and
committed baseline framework stay equal to main. Original app Swift sources, TCP
relay implementation and public API are not modified. App configuration differences
are the existing local-network/single-scene plist and its Xcode registration; the
remaining blank-line differences do not execute or add a feature.

Runtime patch SHA-256:

```text
9cd0a43550a6128046f81d11bd16971e426386e2656e3e8f16fa790d57bbb315  hev-udp-port-zero.patch
0b2088e6f0519fe01d9d0c64d0bda4cc5909f292ed9095613a1b2434f930ac0e  hev-udp-sockaddr.patch
```

## Completed-run evidence

The following table refers specifically to run `35696504942`, not an unexecuted
future test. Counts are scenario executions, not unique specifications or device
measurements. Use the current run's JSON for its own outcomes and exact commit.

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

## Confirmed limitation and corrected attribution

With both patches and a fixed relay port, the unknown-concurrent-peer observation
returned 8/9 on Linux and macOS, with either one or four workers. The failing test
opens three associations, sends their first datagrams and closes one, then checks
the remaining exchanges. Failure is a timeout. This is a real unsupported condition,
not an expected-success test that the audit quietly marks passed.

The preceding review incorrectly generalized that the same concurrent test failed
in Linux's unpatched control. Reinspection of `control-unpatched-fixed.json` in
run `35696504942` shows that its concurrent case PASSED; its failure was instead the
separate IPv4 connection with a `::1:0` request hint. An aggregate 8/9 result does
not identify which case failed. That prior causal attribution is withdrawn.
Darwin's unpatched control fails before this relay phase and cannot distinguish it.

The existing SO_REUSEPORT sockets and first-datagram selection permit ambiguous
association ownership before peer connect. This is a source-derived explanation
consistent with the observed patched failures, not a packet-by-packet kernel trace.
Whether a particular shared-port result is inherited, exposed by the new path, or
affected by timing/platform behavior is NOT settled by these controls. The final
patch must not be called regression-free for all fixed-port deployments.

Ephemeral relay ports and known concurrent client ports passed their tested profiles.
For concurrent unknown ports, `udp-port: 0` is the verified configuration. A full
shared-port solution requires deciding association identity/demultiplexing policy;
silently changing a user's requested fixed port would alter semantics. Neither
policy change is hidden inside the narrowly agreed minimal two-patch repair.

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

The two production C files and new C unit follow upstream clang-format-18. Native
unit builds use warnings as errors. Patch reversal restores exact upstream source.
On resumption, explicit ARM64 iOS syntax-only compilation of both production files
was added. It does not produce a library, an application archive or an IPA.
The first audit attempt's whitespace false positive concerned mandatory single-space
context lines inside unified patches, not a runtime defect. Actual added C whitespace
is still checked by git apply and clang-format.

## Resumption changes

1. Correct the unsupported unpatched-concurrency claim in README, feature spec and
   this report. State the precise failed test, not just aggregate pass counts.
2. Include all twelve differing paths in the specification, not only the initial eight.
3. Save the complete main-to-feature diff and tested source ZIP for inspectable evidence.
4. Require identical root/feature specifications and the expected Darwin negative-control
   error type, rather than accepting any failure as proof of the missing repair.
5. Compile both changed C files in syntax-only ARM64 iOS mode without packaging.

No runtime patch, Swift app logic, baseline file or other branch changes in this
completion. There is no new timer, socket, payload buffer, queue, per-packet
allocation or task. Existing address copy/reset operations fulfill buffer/API
contracts; no absolute CPU/battery optimum is claimed.

The documented residual source-IP/FRAG validation, 1500-byte buffering/truncation,
empty payload and explicit address-family bind limits remain outside these two
compatibility repairs. Passing the targeted tests is not full RFC conformance.

## Final closure and accepted operating constraint

The owner explicitly chooses to keep the two runtime patches as they are and
finish by documenting operation, rather than implementing shared-port multiplexing
or changing any port policy. The production-code freeze is the state at
`8c81e6165b3f84b20957ef39e60016a7a0dfd71a`. This closing change edits only README.md,
its identical feature specification, and this review. Tests, workflow, source pins,
app code/configuration, public API, baseline framework and both patches are unchanged.
Main, release/integrated and the other feature branches are outside the write scope.

The canonical recommendation is **UDP Listen Port = 0** for general operation and
for reliable separation of concurrent associations with unknown client ports.
The fixed-port setting is retained, not banned or silently converted to zero.
Known, accurately advertised client endpoints passed the existing fixed-port tests.
Unknown concurrent endpoints on the same fixed port remain an accepted limitation:
loss, timeout, refusal and disruption after another association closes are possible.
This is not an equally reliable mode with only less detailed attribution.

The README now distinguishes association count from destination count, explains
BND.PORT negotiation with an unchanged TCP server entry, separates client port zero
from local listening port zero, and states that allocation is per association rather
than per packet. The recommendation changes neither the stored configuration nor
the actual application defaults. It does not authenticate the initial sender, fix
FRAG/RSV or buffer-size limits, or establish arbitrary network/VPN behavior.

### Follow-up evidence already completed

Run `35698841052` tested the frozen runtime at commit `8c81e616...` after the
preceding attribution correction and ARM64 iOS syntax checks were added. Its
required profiles again passed 58/58 on Linux and 58/58 on macOS. Its fixed-port,
unknown-concurrent-peer observations failed the concurrent-close scenario with
one and four workers on both platforms; Linux four-worker output reported
ConnectionRefusedError and the other three reported TimeoutError.

In that follow-up run the Linux *unpatched* fixed-port profile was 7/9 and also
failed the concurrent-close scenario, whereas run `35696504942` passed that
scenario. Both individual records are retained. The new result is evidence that
the unpatched implementation can fail too; it does not retroactively validate the
previous run's incorrect attribution or prove every failure has one exclusive cause.
No failure is added to the required-pass count or removed from the observation log.

The closing documentation commit invokes the same native-only audit without
changing it. Its own tested-commit.txt and summary.json identify its actual results;
the historical counts above must not be mistaken for an unexecuted future run.
No IPA, XCFramework or application archive is produced by that audit.

### Final inspection against the owner's criteria

| Criterion | Final disposition |
| --- | --- |
| Minimal, concise implementation and resource efficiency | Retain two C files and net 27 C lines. No new heap allocation, socket, task, timer, queue, payload copy, or public API. No unsupported absolute-performance claim. |
| Standard style and existing structure | Preserve the upstream GNU C dialect, class/interface and coroutine paths. Patched C and the unit follow upstream clang-format 18; iOS syntax and warning checks remain required. |
| Residual defects and omissions | The two targeted Darwin failures are repaired in the tested configurations. Shared-fixed-port ambiguity and the listed upstream protocol/security/buffer limits are explicitly not declared resolved. |
| Correct scoped behavior without unnecessary expansion | Keep existing failure returns, association-state changes, address fields, receiving capacities and IPv6 preservation. Add no automatic fallback or alternative relay architecture. |
| Complete documentation | Retain the twelve-path inventory, exact targets, rationale, port semantics, resource review, operating table, examples, test scope, named historical evidence and limitations. Root README equals the feature specification. |

All twelve differing paths relative to main were rechecked against the inspected
snapshot; files outside the three documentation paths remain byte-identical. The
existing regression and actual-C probes remain available and are rerun at the
closing commit. This is completion of the agreed feature with accepted limitations,
not a statement that all UDP configurations or every future iOS version are safe.

## Reproduction

```sh
python3 Tests/udp_compat_audit.py
```

Use a clean checkout with the documented native toolchain. Every result carries
its profile and failures; the audit logs the tested commit. No invocation of
build-apple.sh, xcodebuild archive, or IPA packaging occurs in this workflow.
Main and release must be checked after publication to confirm they did not move.
The root README and feature specification are identical and describe purpose,
implementation, cost, integration, tests and limits. This report distinguishes
completed evidence, further verification steps and the limited release decision.
