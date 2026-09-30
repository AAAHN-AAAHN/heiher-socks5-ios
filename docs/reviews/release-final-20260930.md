# Release final review — completed package metadata verification

## Exact source and outcome

Starting release: `eff5574a902a8c7efba9675fe49587fdec030e83`.
Executed release: `e119676b2c83236ed465b7b61611db577a9576b2`, tree
`42ee2d39996b7fc2faeb166821266d1308cce442`, 241 tracked paths.
Run36705838060 attempt1 passed Linux and Xcode27; completion metadata is
2026-09-30T11:34:16Z. Both jobs completed all applicable stages. Apple performed
actual archive/IPA, twelve-file SDK checks, ten seeded Simulator cases and three
UI cases; Linux's Apple-only skipped steps are not execution.

This is a verification-only repair. All12 production Swift files,8 native patches,
177 exact owner mappings, root wiring, defaults, resources, permissions, workflow,
pins and build10 identity remain unchanged. The user's explicit decision to preserve
fixed UDP port/unknown-peer behavior is binding: no fallback, UDP default migration,
new client requirement or protocol change has been applied. Main and feature refs
are not modified. All four top-level principles remain in their original document.

## Reproduced verifier omission

The exact prior function, blob `cebf999eb5ae461393a4be531d357e9a86d7d5d4`, compares
file inventories, contents, CRCs and duplicate names, but ignores Unix types/modes
and all directories. Metadata-only copies of the actual original build10 IPA pass
after losing executable permission, marking the WAV as a symlink, or adding an
unexpected/traversal directory. The delivered original IPA is valid; these are
reproduced defects in verification, not evidence that the deployed app was corrupt.

The new helper requires a real nonempty regular archive app, Unix regular ZIP files
with permissions matching the source, and expected empty usable Unix directories.
Source symlinks/special files and unsafe/foreign directory names are rejected.
Directory entries remain optional and order-independent. This is the Unix-generated
pipeline's comparison contract, not a generic extractor or proof against simultaneous
malicious changes to both archive and attestation. Source and product gates remain.

The implementation adds33/removes2 helper lines and one build command. The old
payload fixture keeps its exact six inputs/oracles while recording explicit source
Unix metadata. A new121-line fixture runs31 inputs against prior/current functions
(62 checks on each host). Four valid shapes and five previous rejection cases retain
their results;22 previously admitted malformed inputs are rejected. No warning gate,
timeout, original assertion, formatter18 requirement or physical-proof distinction
is weakened. Test code is not in the application target.

## Verification results and scope

- New62 metadata checks and original12 payload comparisons pass on both hosts.
- Full-history ancestry/177 mappings, baseline46, input37, composition, source/pin,
  whole-worktree/index and exact eight-patch reversal checks pass.
- TCP15,552 parameter cases times three callback modes pass with sanitizer/O3 in
  Linux buffered/splice and Apple buffered. Existing UDP111 full-payload cases,
  24 accounting boundaries,18 associations/126 echoes,426 mixed records and
  145,459 stream boundary cases pass for the combined engine.
- Registry/concurrency/expanded-registry contracts and Apple TSan pass; sampler
  debug/optimized runs each pass98,516 checks. Original native server18, active
  client12, real file/store/controller/Hev16 and model/persistence suites pass.
- The unchanged Background owner driver retains35 policies,1,352 pairs,69,984
  triples,65,536 events/1,024 liveness points,135 ownership and12,096 reentry
  histories. Exact mappings plus direct release controller/async/real host/UI tests
  connect this standalone source-specific scope to the integrated app.
- Apple Foundation/Combine/RunLoop scheduling and WAV decoding pass. Audio/location
  doubles are not physical OS events. All12 production Swift files pass the real
  iPhoneOS27/ARM64 minimum17.2 SDK check; its diagnostic log is empty.

Native timed retention used actual UDP, allocator, clock and Hev timer with a
fixture-only600s communication timeout; application default60s was preserved.
Linux demanded48001/30001 bytes120.060520s apart and reclaimed to30500 at300.147746s,
then1500 at420.256488s. Apple spacing120.004527s; reclamation300.017604s/420.022286s.
No later packet is needed; Total and the registered IP retain In78002/Out0.
This is not a physical RSS/energy test or a deadline that overrides suspension.

The actual iPhone16/iOS27.0 build24A434 UI run passes3 cases with no failures/skips:
audio125.549s, integration122.142s, statistics125.198s, session window474.134s.
The original900s command limit and all case predicates remain. Runtime warnings and
UI/seeded cleanup arrays are empty. Ten original/remapped preseeded cases pass.
All13 UI attachments and5 seeded screenshots were inspected; portrait Total
100.226/100.226/200.452KB and each IP50.113/50.113/100.226KB double after Stop/Start
in landscape. Scroll/hittability checks do not mean every overview/footer is unoccluded.
Actual file-provider transfers, location permission trials and physical installers
were not performed by these tests.

Supplemental local17 full-history/source/model/driver commands pass. The first
outer20s container call interrupted a wrapper before its outcome; its partial log is
retained, not counted as success. The unchanged suite completed in the later run.
An8464-case file-mode/type/creator sweep passes. Three disposable verifier omissions
fail explicit permission/type/directory assertions. The preliminary directory mutant
raised KeyError; the corrected mutation confirms the intended assertion failure.
No disposable mutation enters Git. Actual-old-IPA copies produce the same four old
false acceptances and four new rejections; the unchanged IPA passes both checkers.

## Actual products and source correspondence

New unsigned IPA: version1.1.0/build10, `hev.Socks5`,285407 bytes.
SHA-256 `2ca709d22a9e8f0f0bf1772f45b166aa3072b0d1f20048d5514848265f90ada5`.
Independent reads confirm ARM64/iPhoneOS27/minimum17.2, no signature/encryption,
Unix regular files with executable0755/resources0644 and seven payload files.
Actual app/dSYM UUID is `78205DB1-9792-3928-98C1-B40B14ACF29D`; the DWARF defines
aggregate/client statistics and prepare symbols. Full archive comparison, icon/CAR/
ImageIO and original400-sample silent WAV checks pass.

Every decompressed payload file and its Unix mode matches the preceding valid
build10. ZIP timestamps/extra fields and archive SHA differ. The prior IPA is not
replaced, relabeled or described as defective. The source change is in validation,
not runtime. Subsequent signing/import changes product bytes and requires its own
identity record; this unsigned result does not certify physical installation.

Original current artifacts:
- Linux11091983182: `723ad4aad55efdd023737e89dd8cea7f924729598bd2fb380cf0f082d6baac4a`.
- Apple11093346414: `e62dd93617a0d52973fd859dcd407536e164950432ba1cbd8be80510ea4a6d44`.

Both original ZIP digests/CRCs and four241-file source archives agree with the tested
commit/tree, Git modes and full manifests. Generated framework/product records name
the tested source, distinct from the unpatched committed baseline and final docs.
An offline verifier checks saved source/object/product/evidence correspondence; it
is not another build, CI run or device test. The original artifacts preserve complete
logs, source snapshots and genuine reachable Git history.

Duplicate ZIP-name warnings in negative fixtures, ASan alternate-stack limitations,
upstream libtool/AppIntents and tool notices are retained. Absence of the targeted
synchronous audio advisory and empty SDK/runtime-warning fields do not imply every
tool was silent or every library path sanitizer-instrumented. A running-job log GET
returned BlobNotFound before completion; completed artifacts were subsequently read.
No host setting, cache, runtime or timing workaround was used.

## Publication and limitations

The final publication changes only README, its identical integrated specification
and this review. Other238 tested paths remain byte/mode-identical, including all
production/test/build code. Its direct parent is e119676b; a docs-only commit is not
a new runtime execution. No main/feature ref, release tag or earlier product changes.

Added stat/type work occurs only during packaging validation, proportional to entry
count. No app timer/thread/allocator/counter/log is added. Existing UDP buffer/sizing,
process-lived IP registry, atomic/snapshot work and audio/location activity retain
their costs; no universal CPU/RAM minimum or physical battery gain was measured.
The agreed fixed-port UDP restriction remains an observed limitation, not a failed
required supported-profile test or a new fix. Physical SideStore/LiveContainer,
shared-host audio, permissions/providers, real interruptions, lock/background survival
and device resources remain unperformed. Current required checks pass and reproduced
verifier omissions are repaired within this scope; arbitrary histories are not proven.
