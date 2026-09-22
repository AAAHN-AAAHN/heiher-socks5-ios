# Statistics follow-up final verification - 2026-09-23

## Scope and preserved decisions

This completes the separately requested follow-up to the earlier final audit,
starting at `cf4743d7bb30cc218bf9f0fd1c42e52ffe424ea4`. The earlier successful run
`35718052239` belongs to `acd65e04152495c04c3a9b033b917a6e60d4af9e`; it is not
represented as a new run. Main remains `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`,
UDP remains `ae466dab1a394af0c83f3dc36e51755f25f91910`, and release remains
`b59e3f1b61ae342a944d96f0da24b1908c2b3eac`. Only statistics-owned tests and
specifications are changed. No application, C patch, source pin, shared Build file,
framework, inherited UDP file, or workflow is changed. No IPA is built.

The review retains successful external socket I/O: no duplicate proxy-hop count,
wire-header estimates, system-DNS replacement, new counter category, durable
statistics, or new relay architecture. The accepted UDP limits remain unchanged.
The C caller/callee context, batch-wrapper prefix returns, partial I/O and error
paths, atomic counters, public API, Swift delta calculation, task cancellation,
project wiring, test assertions and feature inventory were re-examined. No scoped
production-code correction was identified. This is not an all-input correctness
proof, device performance measurement, or expanded protocol/security certification.

## Reproduced verification defect and minimal correction

The audit driver previously left an old `artifacts/statistics-final-audit/SUCCESS.txt`
when a retry was rejected by the existing-core guard, or failed a source check.
This could leave a prior pass marker next to a failed current attempt, even at the
same commit. It does not invalidate the earlier clean GitHub Actions success.

The driver now unlinks that marker when entering main, before either validation
or rejection. It does not remove earlier diagnostic logs or weaken any source,
network, sanitizer, formatter or type check. The existing final write is still the
only point that publishes success. Interrupted or failed attempts must not be
reported as complete; matching tested-commit.txt, logs and a new SUCCESS.txt remain
required. Simultaneous attempts in one working directory are not supported.

`Tests/Statistics/audit_driver_probe.py` exercises the actual driver with temporary
paths and a deliberately failing source-check boundary. Three tests cover a rejected
existing checkout, a failing source check after previous success, and a fresh
failure. They do not run native I/O or pretend that a mocked failure is a network
test. Before the fix the first two tests failed because the marker survived; after
the fix all three passed. Earlier diagnostic logs are checked for preservation.
The audit runs these probes on each platform before the existing native checks.

The patch adds three audit-driver lines: a comment, marker invalidation, and the
new probe invocation. The probe and this review are separate test/document paths,
not application resources. The complete feature inventory now differs from main
at 33 paths: 23 statistics-owned paths and ten frozen UDP dependencies. Both
canonical feature specifications are byte-identical and list the new paths.

## Local verification and fresh-run evidence boundary

Both earlier artifact ZIP digests were checked against GitHub's SHA-256 values.
Their identical source ZIPs reconstructed tree `4aa7d4a04790402dc9765c9bc028409a426d7722`.
Applying the sole documentation checkpoint reconstructed the exact starting tree
`41396987c73e0ba0a4fe04efedeb0238f9110f20`. This prevents a remembered or retyped
approximation from being used as the starting production code.

Locally, the new driver's red/green regression, all six existing pipe-reader cases,
the production Swift model with 10,000 generated samples, Python syntax and
composition checks passed after correction. The container could not resolve
GitHub for git clone; full native and iOS checks therefore run through the existing
GitHub Actions workflow, rather than being claimed as local executions.

A fresh run must identify its triggering commit and both platform artifacts.
Completion results are recorded below only after those jobs and artifacts are read.
