# Build and verification infrastructure

## Purpose and scope

The build system creates a product from an explicit feature composition and records evidence for the implementation actually exercised. It must not substitute a source review for a runtime test, a compiled SDK interface for an installed application, or a feature-owner result for the integrated release's execution.

This guide describes the common responsibilities shared by the branches. Each branch's root README specifies its applicable feature tests and commands. The workflow and `Build/features.json` are authoritative about which stages are enabled for that checkout; a feature-only workflow is not automatically an IPA-producing workflow.

## Functional behavior

The build validates input identity before native patching, applies each declared patch at its declared repository root, tests the resulting native engine, checks source formatting and reverses the patches to prove exact restoration. A rejected input or failed operation must not leave an overall success marker that can be reused as a valid verdict.

On Linux, the applicable paths execute native networking, C fixtures and platform-independent Swift models. Statistics-enabled compositions exercise buffered and splice paths. Apple execution adds Darwin networking, the actual iPhoneOS SDK, resource compilation and the product or Simulator stages selected by the branch. Expected platform-specific skips remain skips, not successful executions.

The integrated release validates a freshly generated patched framework, twelve production Swift files, an ARM64 archive and an unsigned IPA. It also exercises seeded original/remapped Simulator installations and the actual integrated, background-audio and traffic-statistics UI tests. These are separate gates, not a single interchangeable success flag.

Each result applies to its recorded source, toolchain and executed stage. The retained runtime evidence covers native host execution, the iPhoneOS SDK, archive/unsigned IPA and Simulator behavior. It does not establish SideStore installation, LiveContainer guest execution or physical background survival. A documentation-only revision preserves the runtime inputs but is not a new execution of those layers.

## Implementation and ownership

`Build/features.json` supplies the composition name, features, native source revisions and ordered patch list. `Build/upstream.json` and `Build/baseline-framework.json` bind the common native inputs and committed unpatched framework. Build code selects behavior from declared features rather than a branch-name substring.

`Build/check.py` owns baseline, patch-application, formatting, reversal, composition and resource checks. Whole tracked working-tree and index equality is required at native input and restoration boundaries. The source checkout is not overwritten by generated frameworks. The product is built from a disposable source copy with the exact declared generated framework substituted into that copy.

Source-composition checks compare feature-owned paths, contents and executable modes with their immutable owners. Documentation has its own current-parent contract in `docs/documentation.json`; it does not change executable source locks. Where a standalone feature's source predicate is inapplicable to the combined application, the original predicate runs in that feature's exact worktree. File equality and separate integrated checks connect the owned implementation to release.

In the release, `Build/release_source.py` verifies the generated framework inventory, source identity, completion prerequisites and copied non-framework files. `Build/verify_release.py` checks the actual device product. The IPA comparison requires the complete regular-file inventory and bytes, Unix file types and permissions, valid CRCs, unique entries and only expected usable directories. Directory records may be omitted without changing the actual payload contract. Source symlinks and unexpected package file types are not accepted as ordinary resources.

Resource verification checks the original silent WAV, permissions and scene declarations, the compiled AppIcon catalog and fallback images, actual ARM64/iPhoneOS/minimum-OS metadata, required native definitions and the executable/dSYM UUID correspondence. Actual product hashes identify bytes; source identities identify the code. An unsigned CI product and a subsequently signed installation are different byte-level objects.

## Design rationale and resource cost

Explicit composition keeps independent features separable and prevents a test from silently exercising an unintended engine. Clean source and generated-product boundaries make artifacts traceable without replacing source files in place. Exact patch reversal detects changes outside the intended native edits. Package type and permission checks matter because identical file contents are not sufficient to make a valid executable or ordinary resource.

Verification scripts and temporary XCTest code are outside the application target. Their subprocesses, hashing, temporary worktrees and package scans are build-time costs. They add no runtime payload copy, audio timer, registry lock or networking dependency. Feature runtime costs remain described by their owners; a successful build does not establish minimum CPU, RAM, latency or battery use.

## Verification contract

| Layer | What is checked | What the result does not prove |
| --- | --- | --- |
| Documentation and source | Current-parent copies, structure, links, frozen code, declared ownership, source locks and worktree/index state | Behavior of every possible input or device state |
| Model and controlled-boundary tests | Actual model/controller or C implementation with specified return values, failures and orderings | Unscripted operating-system or physical-network behavior |
| Native networking | Actual sockets, complete payloads, address/peer rules, cancellation and cumulative accounting | Phone radio, hotspot, VPN or installer behavior |
| Sanitizer and optimized builds | Required fixture memory/undefined-behavior checks and optimized-path invariants | Instrumentation of every library path or absence of every possible defect |
| SDK and archive | Real target compilation, linked implementation and complete unsigned product structure | Signed-device installation or prolonged background survival |
| Simulator | Real application/UI execution, saved state and selected original/remapped identities | SideStore or LiveContainer physical execution |
| Physical deployment | Only a separately recorded device installation and execution qualifies | Any unexecuted permission, interruption, resource or survival scenario |

The baseline/input/package regression fixtures retain their valid inputs and deliberate invalid controls. Checks do not relax assertion policy, warning thresholds, formatting requirements, subprocess limits or cleanup failures to obtain success. Source and product manifests retain exact identities even when a later stage fails. Machine-readable evidence is not rewritten into a narrative claim that an unexecuted stage passed.

Verification is organized by the invariant under test: input identity before patching, exact restored source after patch reversal, service and payload behavior during execution, and complete source-to-product correspondence at packaging. Deliberately invalid controls must be rejected for the intended reason; their rejection is not an application failure. An observational profile documenting a known limitation remains distinct from a required supported-profile test.

## Operation and limitations

Use a full-history checkout and a clean workspace. For the baseline, start with `python3 Build/check.py baseline`, `python3 Build/check.py composition` and `bash Build/build.sh`. Feature READMEs specify their dedicated audit entry points. The integrated path uses `bash Build/build.sh`, `bash Build/check_swift_sdk.sh`, `python3 Build/verify_release.py`, `python3 Build/simulator_review.py`, `python3 Build/ui_review.py` and `python3 Build/record_evidence.py` on the applicable platform.

On an Apple host the release build defaults `BUILD_IPA` to `1`; `BUILD_IPA=1 bash Build/build.sh` makes that archive-producing choice explicit, while `BUILD_IPA=0` skips it. The release workflow explicitly supplies `1`. Run the SDK/product/Simulator commands on an Apple host only after their required source/native/archive stages succeed. A source archive without the recorded Git history cannot satisfy ancestry or exact-owner checks merely by being unpacked and initialized as a new repository.

Run `python3 Build/check_documentation.py` for reproducible document and frozen-input validation. The optional `--live-parents` mode additionally compares recorded parent revisions with current remote refs. `python3 Tests/documentation_contract.py` exercises document-contract rejection cases without modifying application branches or products.

Configured minimum iOS 17.2, the physical iOS 27 target and the actual SDK used by an artifact are different properties. SideStore standalone and LiveContainer guest installation require their own signing, container and runtime evidence. Physical permissions, external providers, audio interruptions, lock/suspension, prolonged background execution and device resource measurements cannot be inferred from host or Simulator success.

## Related documents

The [shared baseline](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/main-baseline.md) defines common inputs. The [documentation contract](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/documentation.md) separates prose inheritance from executable source identity. Each checkout's root README and `docs/features` directory describe its current functional and verification composition.
