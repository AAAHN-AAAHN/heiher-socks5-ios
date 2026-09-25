# Server execution control

## Current audit — 2026-09-26

This branch owns server options and serialized Start/Stop/reconfiguration, not JSON
storage or the integrated application. The final review starts at
`b4d20f8402cdcd5ee687d17f46bf71d38a9febb5`. No additional runtime defect was reproduced
in the reviewed model/controller/native boundaries. The changes below repair audit
input identity and the native-header/SDK handoff without modifying production code.
New native and SDK execution is pending publication of this exact candidate; the
previous green runs do not validate the new audit entry points.

The complete preceding README is preserved byte-for-byte in
`docs/history/server-control-before-final-audit-20260926.md`, including original
failures, corrections, source/run/artifact identities and evidence qualifications.
Historical claims apply to their own revisions. This README is identical to
`docs/features/server-control.md` and is the current contract.

## Versions, actual environment and ownership

The target is a physical iOS 27 iPhone installed independently with SideStore or
executed as a LiveContainer guest. Signing, app/container identity, permissions,
process-global engine/signal state and host arbitration differ between these paths.
Neither a native host test nor an iOS SDK typecheck establishes either installation
method. No particular installer/host version, physical permission or background
execution has been tested in this audit. The configured minimum remains iOS 17.2.
Actual toolchain and execution versions must be recorded with each completed run.

The unchanged base is main `d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`.
`main -> server-control -> settings-persistence` is the one-way dependency. The
server layer never reads AppSettings, SettingsStore, UserDefaults or JSON. It has
no dependency on UDP compatibility, statistics, Background or app-icon features.
A downstream update must inherit the completed owner and exact mapped files rather
than edit or duplicate its controller. Other branches and the existing integrated
release/IPA are not automatically changed by a server audit.

The four project principles govern this work: preserve established behavior before
minimal, simple and efficient changes; target the actual SideStore/LiveContainer
environments; document purpose, scope, costs, versions and limits; and keep source,
mock, native, SDK, CI, package, installation and physical-runtime evidence distinct.

## Server option contract

ServerSettings is a Codable value containing the existing eleven options. Defaults
remain workers 4, listen address ::, TCP port 1080, empty UDP address, UDP port 1080,
IPv4 bind 0.0.0.0, IPv6 bind ::, empty interface and credentials, IPv6-only false.
The UDP sibling's port-zero operating recommendation does not silently change them.

Executable validation permits workers 1-64, TCP port 1-65535 and UDP port 0-65535.
The seven text fields passed to native fixed-size buffers must be single-line,
control-free and at most 255 UTF-8 bytes. Authentication is both empty or both set.
Single quotes are escaped when producing the original YAML. Invalid drafts can be
held while stopped; validation errors do not start the engine. Codable itself is
not persistence or native readiness certification.

The ten string fields use UTF-8-view equality and the Boolean uses normal equality.
This preserves raw credentials/drafts that Swift canonical String equality would
otherwise merge. There is no Unicode normalization, second stored representation,
hash cache or JSON encoding on every comparison. The validator, YAML and errors
remain unchanged. Comparison work is linear in the compared bytes.

## Controller and native cancellation contract

One root-owned MainActor ServerController owns the blocking native call independently
of view visibility. ServerSettings supplies options, ContentView edits bindings and
AppRoot connects intent. The standalone root starts stopped and keeps options only
in memory. The same editor/controller can be supplied by downstream persistence.

Current/desired/attempted values serialize execution. Changes or Stop request quit
once; a replacement starts only after the previous main call returns and its actor
completion is handled. Latest Stop cancels a pending replacement. Unrelated repeated
apply calls do not retry an exited/invalid configuration; explicit Start, changed
options or completed Stop/Start may retry. Running denotes scheduled invocation,
not proof of socket bind/listen success. Unexpected native exit remains visible.
The worker callback retains its controller until completion. Concurrent independent
controllers/engines in one process are not a supported composition.

The one existing native patch preserves three related boundaries:
- Set SYNC_ABRT on the proxy's early pre-start Stop return so other workers exit.
- Check the worker run flag before I/O yield as well as after it; an already-delivered
  Stop wakeup must not be followed by a fresh unbounded wait.
- Call project API hev_socks5_server_prepare after validation, while idle and before
  dispatching the next call. It clears only obsolete SYNC_STOP from a prior call;
  a later Stop retains cancellation semantics. Legacy C callers remain unchanged.

The committed baseline XCFramework and source/submodule pins stay unchanged. The
baseline alone has no prepare symbol: actual builds must rebuild the existing patch
before linking. There is no readiness polling, new native API in this audit, added
queue/timer, service, logging, permission, host patch or automatic retry policy.
These tests do not serialize unrelated LiveContainer host code or prove universal
signal/loader compatibility. CPU, energy and latency improvements are not measured.

## Findings and minimal audit corrections

### Working files and index could differ from the recorded revision

The build and SDK entry points read working files, while record_evidence archives
HEAD. They now reject both working-tree-versus-HEAD and index-versus-HEAD differences
before native/Apple work. Native input is checked again before the optional packaging
phase; SDK input is checked again before success. This also catches a staged change
whose working file has been restored. In checks-only runs no tracked file changes.
The existing optional packaging phase still generates its patched framework/product;
that intentional build output is not claimed to be committed baseline bytes.

### SDK checks could reuse unrelated or modified compiled headers

The old SDK entry accepted any nonempty compiled-headers files, including a previous
revision or output remaining after a failed native run. The build now records its
HEAD and SHA-256 of hev-main.h/module.modulemap beside the exact copied headers.
The SDK entry requires native SUCCESS, the same HEAD, and both matching hashes before
Apple tools. Missing identity, stale revision or modified header/module is rejected.
Native and SDK success markers still represent different phases. A standalone SDK
run after changing even documentation requires a fresh native pass at that revision.

input_integrity_check.py executes the exact old/current shell bodies in real isolated
Git fixtures: clean, unstaged, staged and index-only states; stale/missing header
identity, changed header/module, and missing native success. All 26 cases passed
locally. The fixtures stop at a deliberately failing downstream boundary and do not
pretend to build Hev or use an Apple SDK. The original six stale-success controls
remain unchanged. Previous diagnostics are retained and rejected attempts invalidate
only their applicable success markers.

These are checkpoint comparisons and local provenance checks, not a cryptographic
trust boundary against an adversary rewriting both files and attestations. Untracked
inputs, external toolchains and concurrent edits restored between checks are not
certified. Run audits in separate, clean complete Git checkouts.

## Validation commands and retained checks

```sh
BUILD_IPA=0 bash Build/build.sh
# On the actual Xcode 27 host, after native success at the same commit:
bash Build/check_swift_sdk.sh
python3 Build/record_evidence.py
```

The unchanged workflow runs Linux and Xcode 27 with BUILD_IPA=0. It retains seven
server scenarios, 84 revalidation assertions, 512 exact-old validation/YAML parity
cases and the expected 22 old-equality failures. The actual controller links to the
patched native library for authentication/byte replacement, 14 result records and
40 active Stop/restarts per host. Twelve active-client cases cover incomplete SOCKS,
partial authentication, active echo, backpressure and reset clients. Six expected
old-controller failures and two old final-Stop controls accompany eight corrected
delayed-completion schedules. Forty original pre-start and 100 legacy/prepared
cancellation cycles, exact worker controls, TCP echo/parser fixtures, formatting,
patch reversal, owner and baseline checks remain. Counts contain repetitions.

Five actual production Swift files are typechecked against iPhoneOS 27 with the
ARM64/iOS17.2 target and warnings-as-errors, using the native output's verified
headers. This is not an iPhone link/archive/IPA or UI test. Existing source archive,
full hash manifest and source identity are retained. Inspect actual exits, all jobs,
run/attempt, ZIP digests/CRCs, commit/tree/modes and per-test logs, not only a badge.
A later README-only completion must match all executed non-document inputs.

Local actual-body tests passed seven server scenarios and all 84 assertions. The
settings child also passed its existing 209 current-store assertions locally. These
local runs substitute the existing UI/engine/provider boundaries and do not replace
fresh native/SDK CI. New execution results are recorded only after inspection.

## Unperformed and unchanged scope

Physical SideStore provisioning/install, LiveContainer guest loading, host signals
and permissions, UI/keyboard/accessibility, real IPv4/IPv6/VPN/hotspot, app suspension
or termination, lock screen, long-duration operation and energy remain unperformed
for this revision. Neither branch adds background keep-alive. Saved downstream Start
is intent, not a promise of relaunch or execution while suspended. Main, unrelated
features, release/integrated, branch count and existing build 7 IPA remain unchanged.

Primary contracts, not device execution evidence:
- https://docs.swift.org/swift-book/documentation/the-swift-programming-language/stringsandcharacters/#String-and-Character-Equality
- https://www.rfc-editor.org/rfc/rfc1929
