# Shared upstream baseline — complete project review

## Current contract — 2026-09-26

Main combines unmodified latest verified `heiher/socks5-ios` application sources
with the pinned, unpatched `heiher/hev-socks5-server` engine. It is not a byte-for-
byte mirror of the app repository's older bundled binary. The governing four
instructions are retained verbatim in `docs/top-level-principles.md`. Original
maintenance documentation is preserved byte-for-byte in
`docs/history/main-before-project-audit-20260926.md`.

- App: `180012e8b9dbaa2002a68ebd2c75bccebcfb789c`.
- Engine: `b3585289622561caf4b8789b436cc8820ecd6be0`.
- All three submodules use that engine's exact gitlinks in `Build/upstream.json`.
- Main has no feature/native patches. App/project/LICENSE stay exact upstream.
- The committed 16-file framework and its historical Xcode16.4/iPhoneOS18.5
  provenance remain unchanged; fresh product compilation is a separate result.

The intended environment is a physical iOS27 iPhone, either SideStore standalone
or a LiveContainer guest. They have different signing, container and host boundaries.
Configured minimum iOS17.2, supported target, actual build environment, Simulator
execution and physical installation/execution are not interchangeable. No host patch,
permission, relaunch mechanism or background service is added to main.

## Shared source integrity correction

The former native `apply` precondition checked only tracked C/H changes. A changed
Makefile or build script could pass while the recorded commit stayed unchanged.
The former reverse check compared worktree to index rather than both to HEAD;
a staged change could therefore pass as an exact upstream restoration. All declared
native repositories now require both whole tracked worktree and index equality to
HEAD before patching and after reversal. Recursive submodule checks remain enabled.
The Python check entry rejects optimization so assertions cannot silently disappear.
Pinned commits, patch contents/order and formatting rules are not changed.

The former generic build also retained an obsolete SUCCESS on early failure and
mutated the tracked framework during packaging. It now invalidates the overall
verdict before rejection, verifies worktree/index, and packages a disposable exact-
HEAD source copy containing the rebuilt framework. The original checkout and its
committed baseline are never overwritten. Packaging staging and previous IPA output
are cleared before writing a new package. Old diagnostic logs remain; partial output
is not overall success. Source archive, tested commit and reachable history are
recorded independently from generated products. Generated binary reproducibility
is not inferred merely from equality of source hashes.

`Tests/baseline_audit.py` executes exact-old/current functions and shell entries:
46 tracked-source, reverse, Python-optimization and stale-marker cases in isolated
real Git fixtures. Only shell fixtures stop at a deliberately failing next validator;
no fake native or Apple success is used. This is audit-tool validation, not runtime
coverage. Existing app/native tests and operation deadlines are retained.

These checks are provenance checkpoints in a clean isolated checkout, not protection
against adversarial concurrent modification/restoration, unrelated untracked files,
external toolchain compromise or an OS process that cannot make progress. No runtime
cost, production timer/thread/state or energy improvement is claimed.

## Inheritance and build paths

All six feature branches must contain the current completed main as an actual
ancestor and record it as `Build/features.json:base_commit`. Shared pins, baseline
framework/inventory, this specification, principles and common audit fixture remain
identical. Branch-specific build/check logic is not incorrectly required to equal
main when that feature owns a reviewed extension. Source checks still verify each
branch's declared composition and its native patch inventory.

UDP is the parent of traffic-statistics; server-control is the parent of settings-
persistence. Background and icon are independent. Release must contain all six
completed owner tips, preserve exact owner file mappings and rerun the combined
checks. Main ancestry alone does not prove current sibling-owner membership.
Updates preserve old ancestry and never reset or force-rebase feature histories.

Use a full Git checkout and a clean build workspace. The ordinary entry is:

```sh
python3 Build/check.py baseline
python3 Build/check.py composition
python3 Tests/baseline_audit.py
bash Build/build.sh
```

The generic Apple entry archives `.build/<name>-product-source/Socks5.xcodeproj`,
not a root project linked with an outdated committed baseline. Release has its own
strict generated-framework and complete IPA-payload verifier. Its dedicated source
copy remains `.build/integrated-product-source`. Source ZIPs do not supply all exact
historical Git objects required by the negative controls.

## Execution evidence and limits

This source change requires fresh Linux native and Xcode27 Apple checks before a
completion claim. Baseline TCP relay, source identity, exact upstream reversal,
46 audit controls and actual unsigned ARM64 packaging are distinct from feature
runtime tests. Historical successful feature/release runs do not validate this change.
The original main app and unpatched native limitations remain intentional baseline
behavior. Use the audited integrated release for the six-feature application.

Physical SideStore/LiveContainer installation, host arbitration, permissions,
call/Siri/Bluetooth, VPN/hotspot, lock/suspension, long-duration and energy tests are
not performed by these scripts. An unsigned IPA must go through the user's signing/
import workflow; its hash is not the hash of a later signed copy. No original build7
or build8 package is relabeled as a fresh product.

## Completed baseline verification — 2026-09-26

Run **36218740219**, attempt 1, executed exact source
`3e7047cfa52f446e5c5d2f6c15e49e8bbfd7cd8b`, tree
`c9cdbbac0c00ebe1e0ef26f047c443b959ce3689`. Linux and Xcode27 jobs both
passed on their first execution. All46 old/current audit cases, actual native TCP
echo, baseline/composition and exact native source reversal passed on both hosts.
Input and final worktree/index logs are empty. Actual Apple framework generation,
ARM64 app archive and package/ZIP checks completed without changing the tracked
checkout. This is baseline packaging, not the integrated six-feature deliverable.

Original artifacts10898635468 (Linux) and10898475964 (macOS) were inspected:
SHA-256 respectively
`86d1932980659a1ef74d691faab0d9e49e8fd5d3e8cce406aa5a6e78a58d7f51` and
`7a2821c131bb129bbda3c8859e311632a292aa0ae608d6706ad55406732687a0`.
Both ZIP CRCs, genuine source comments and all42 file contents/modes match the
executed tree. Source/history and native/Apple results are distinct evidence.
The baseline unsigned IPA is72545bytes, SHA-256
`33dd1ff63510b11b225b67d93f157e032f0b503087ff6d6b1d2cfbed89c1cd83`.
Its inventory contains the original app executable, plist and PkgInfo only; no
feature resources or tests were added. No device/Simulator execution is implied.
Platform-specific empty-symbol libtool warnings and AppIntents metadata warnings
remain in original logs. No assertion, timeout or warning rule was relaxed.

This result completion changes only the identical README/main-specification pair;
the other40 files are the executed bytes/modes. The subsequent features must inherit
this completed main commit before final integration; their old successes are not
counted as verification of this new common audit implementation.
