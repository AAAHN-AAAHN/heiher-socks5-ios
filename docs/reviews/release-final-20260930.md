# Release final review — package metadata boundaries

## Checkpoint, 2026-09-30

Starting release: `eff5574a902a8c7efba9675fe49587fdec030e83`.
This is a verification-only change. All twelve production Swift files, eight native
patches, six exact owners, root wiring, default settings, resources, permissions and
build10 identity remain unchanged. In particular, the user explicitly chose to retain
the fixed UDP port/unknown-peer limitation: do not apply the research fallback, change
UDP defaults or require a client change. Existing feature/release histories remain.

## Reproduced defect and minimal repair

The exact prior `check_ipa_files` checks file names, bytes, CRCs and duplicate names,
but not Unix file types/permissions; it also ignores every directory entry. A copy
of the actual previous IPA with identical payload bytes passes even after removing
execute permission from its executable, marking the WAV as a symbolic link, or
adding a traversal/foreign directory. These are synthetic corruptions, not defects
found in the delivered build10 IPA. Its original metadata is valid and is preserved.

The repair inspects the existing archive and ZIP entries. Require a real nonempty
archive app containing only regular files/directories, regular Unix ZIP file types,
file permissions equal to the source archive, and only expected empty usable Unix
directory entries. Source symlinks/special files and unexpected or unsafe directory
names are rejected. Explicit directory entries remain optional; order is irrelevant.
This is the project's Unix-generated IPA contract, not a general ZIP extractor or
an adversarial trust boundary. It cannot authenticate a simultaneously altered
archive and package. No package extraction or new runtime behavior is added.

`Tests/Integration/package_metadata.py` retains the exact prior function body from
blob `cebf999eb5ae461393a4be531d357e9a86d7d5d4`. Thirty-one inputs run against prior
and current functions (62 checks), covering valid reordered/nested/implicit-directory
ZIPs, missing/empty source, file/root/directory symlinks, FIFO, removed/added execution
permission, setuid, file type/creator mismatches, malformed directory metadata/data,
unexpected/traversal/absolute/dot directories, duplicate entries and payload damage.
Twenty-two malformed inputs pass the prior checker but are rejected by the current
checker; four valid inputs remain valid and five old rejection cases remain rejected.
Existing twelve older payload boundary comparisons keep their inputs/oracles; their
ZIP factory now explicitly records source file mode instead of using writestr defaults.

## Cost, retained evidence and completion requirement

The extra stat/type checks execute only during verification, proportional to the
archive entry count. No app CPU/RAM work, allocation policy, timer, thread, callback,
packet I/O, storage write or source pin changes. Original assertions, formatter18,
per-command/workflow timeouts and failure histories remain. The single added build
command runs the new fixture before compilation. Python ZipInfo create_system and
external_attr are documented at https://docs.python.org/3/library/zipfile.html.

Local 62 metadata checks and all12 original payload controls pass. The unchanged
real build10 IPA passes the stronger checker when compared with a faithful extraction
that restores its recorded Unix modes; the four metadata-only corruptions are rejected.
These are verifier/input tests, not new Apple builds or physical installations.

Fresh combined Linux and Xcode27 CI, actual archive/IPA, seeded Simulator and all
three UI tests must pass at this exact changed source before final closure. Until
then the earlier run36693157594 remains evidence only for its recorded source.
Physical SideStore standalone and LiveContainer guest execution, actual interruptions,
permissions/providers, sustained background operation and device power/throughput
remain separate unperformed layers. No finite test suite proves arbitrary histories.
