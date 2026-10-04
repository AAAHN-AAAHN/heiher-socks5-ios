# Documentation inheritance and frozen-code contract

## Purpose and scope

Documentation describes the final implemented behavior, its ownership, the reasons for its design, its verification and its actual limits. The document contract allows explanatory material to be organized without changing the application, native patches, functional test inputs or product configuration.

The upstream README, upstream license and governing user principles are exact source documents. They remain verbatim rather than being rewritten into the project's editorial style. All project-authored implementation guides use the same section order and describe functionality rather than a chronology of edits.

## Functional behavior

Each branch carries its current document parent's complete explanatory-document set. A parent's root README is preserved under `docs/branches`, while the child's root README describes the child's own composition. Shared paths inherited from multiple parents must agree byte-for-byte. The main branch retains the upstream README at `docs/upstream/README.md` and its own guide at both `README.md` and `docs/main-baseline.md`.

UDP compatibility and server control are document parents of traffic statistics and settings persistence respectively. Independent features inherit main. The integrated release inherits the six feature document sets. Parent revisions are actual Git ancestors, not merely names written in prose. The document manifest records the precise parent snapshot so a detached checkout can be verified reproducibly; live-parent verification additionally checks the remote branch tips.

The root README and the branch's own feature specification are identical. Parent copies retain their original bytes, including links. Guides use repository-qualified links where the same body is stored at more than one directory depth. A current implementation's OS requirements, wire format, schema identifiers and timing constants remain meaningful technical information; document titles and prose do not carry dated progress reports or an edit log.

## Implementation and ownership

`docs/documentation.json` identifies the branch, the frozen functional-source boundary, the document parents, owned documents, README mirror and approved document-validation files. `Build/documentation-baseline.json` independently approves this branch and frozen source in the committed HEAD. Its working bytes, mode and index must match that committed approval; changing the document manifest cannot approve a different source. These files are verification metadata, not runtime configuration. Existing functional source pins remain in their original build manifests.

`Build/check_documentation.py` and its documentation regression driver are byte-identical across the branch and its recorded repository parents; the checker rejects a divergent copy. Branch-specific frozen-source approval resides in the baseline record, not in checker code. `Build/check_documentation.py` checks the working files against this contract. It verifies the complete document inventory, parent ancestry and exact parent copies, protected upstream text, README mirrors, required headings, link destinations and document formatting. It also compares both working-file and staged-index contents and modes against the frozen source. Inherited prose is checked for content, Git mode and index consistency. Only explicitly identified documentation-validation changes and related document-reference metadata are exempted from the unchanged-file comparison; those permitted files are themselves checked against their approved content identities.

Where an existing source guard also checked prose against an executable-source revision, only that documentation portion uses the document contract. Native patch order, application modules, SDK settings, feature behavior, functional test cases and failure thresholds remain under their original checks. Feature membership retains its code-owned mappings; documentation-owned mappings are checked by the document contract instead of binding prose to a different purpose's source identifier.

`Tests/documentation_contract.py` creates disposable worktrees and verifies acceptance of the complete valid tree and rejection of damaged documentation or frozen inputs. It does not modify a user's working branch. The checker supports normal offline verification using available Git objects and a separate live-parent check when current remote refs are required.

Repository-qualified document links are resolved against the current checkout and its recorded parent Git objects. Local files and heading anchors are checked directly. Ordinary external links are checked for an allowed URL form, not fetched to prove remote availability or authority. Link validation therefore does not replace reading the linked source or checking whether a technical statement matches the implementation.

## Design rationale and resource cost

Executable composition and explanatory documents have different ownership boundaries. Separating their references makes it possible to preserve a tested implementation while improving its explanation. Requiring actual parent ancestry and byte-identical inherited prose prevents a copied document from drifting independently of its owner.

The unchanged-code comparison is broader than a check of application Swift alone: native patches, functional tests, workflows, build settings, dependencies, resources and executable modes remain protected unless an explicit documentation-only exception applies. The exceptions concern validation of documents, not permission to alter application behavior.

All work occurs during documentation or source validation. No application timer, observer, allocation path, service or packet-processing work is added. Git queries and file/link scans scale with the source/document inventory. The contract is a reproducible repository check, not a defense against simultaneous malicious alteration of code and its approval metadata or every possible concurrent filesystem change.

## Verification contract

The documentation tests cover broken parent copies, missing inherited documents, inconsistent README mirrors, malformed section structure, unresolved links or anchors, altered upstream text, narrative-history markers and unexpected document paths. Frozen-input probes cover edited source, changed executable modes, added or removed non-document files, staged-only changes hidden by restored working bytes, and modifications to an approved validation file. Parent-ref mismatches are distinct from content mismatches. The functional membership parent map must match the document parent map. Approval probes reject working or staged baseline edits, linked or executable baseline records, coordinated manifest/approval edits and a different existing frozen-source commit.

Valid documents must still pass all applicable unchanged feature/source checks. The documentation checker does not convert model tests into runtime evidence or reuse an IPA generated from another source as a newly built product. Application behavior remains established by the frozen implementation's separately identified test and product records; this contract establishes that documentation work has not changed that implementation.

## Operation and limitations

Run `python3 Build/check_documentation.py` from a full-history checkout. Run `python3 Build/check_documentation.py --live-parents` when the current remote parent tips must also match the document manifest. Run `python3 Tests/documentation_contract.py` for the documentation-specific rejection tests. Missing Git objects are reported rather than reconstructed from prose or a source ZIP.

An authorized change must keep parent snapshots consistent from main through dependent features and release. A changed frozen input requires a source snapshot first, followed by a commit that points both branch baseline and document manifest to that snapshot and records actual validator blobs. The approval is branch-local; the common checker does not carry unused pins for other branches. A new document at a shared path must have one unambiguous owner. Exact upstream text and governing principles are exempt from the authored-guide section template, but not from byte-identity verification. License dates in the preserved legal text are not editorial progress entries.

The live-parent option checks the recorded direct and transitive repository branch parents. It deliberately keeps the upstream source revision pinned and does not turn it into a floating upstream update. It does not verify that the checkout is itself the current tip of its own remote branch; publication verification must compare that tip separately. A parent advanced after a check requires a new parent comparison before claiming current inheritance.

Code freezing does not claim that every device environment is proven correct. SideStore standalone, LiveContainer guest operation, actual permissions/providers, interruption sequences, prolonged background execution and device resources require their own evidence. Documentation must distinguish a defined behavior, an executed check and an unperformed deployment test.

## Related documents

The [shared baseline](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/main-baseline.md) identifies common functional inputs. The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) describes evidence layers. The [governing principles](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/top-level-principles.md) retain the user's full requirements.
