# Shared application and native-server baseline

## Purpose and scope

The main branch supplies the common application source, native-server inputs and verification infrastructure from which the feature branches are composed. Its purpose is to make every feature build use the same explicit starting implementation instead of silently combining unrelated dependency revisions.

Main contains the upstream Socks5 application and Xcode project without application-source changes. The upstream README is retained verbatim in `docs/upstream/README.md`; the upstream `LICENSE` is retained at the repository root. The committed XCFramework is an unpatched baseline built from the locked native sources, not a substitute for a feature-enabled generated framework. Main itself does not include the feature patches, persistent settings, traffic tables, background services or custom icon integration supplied by their respective branches.

## Functional behavior

The upstream application exposes the server through its existing interface. The native engine supports IPv4/IPv6, SOCKS CONNECT, UDP ASSOCIATE, the supported UDP-over-TCP command and username/password authentication. The exact feature set and app resources for a checkout are declared in `Build/features.json`; the baseline declares no feature patches.

The feature relationships are one-way. UDP compatibility supplies transport behavior to traffic statistics. Server control supplies configuration and lifecycle management to settings persistence. Background services and the app icon are independent feature owners. The integrated release combines all six owners through its root view and ordered native-patch list.

Documentation inheritance is independent of the frozen executable-composition reference. `Build/features.json` and `Build/upstream.json` identify functional inputs. `docs/documentation.json` identifies the branch's document parents and frozen-code comparison boundary. This separation lets documentation follow the current parent without changing dependency versions, native behavior or test inputs.

## Implementation and ownership

`Build/upstream.json` records the upstream application revision and the server, core, task-system and YAML revisions. The three submodules use the server's selected gitlinks rather than independently selected heads. `Build/baseline-framework.json` records the committed framework inventory. The source identifiers are machine inputs to reproducibility checks; they are not instructions to fetch floating dependencies.

`Build/check.py` checks source-lock agreement, framework contents and feature composition. Before applying a native patch it requires the complete tracked working tree and index to match the declared native revision. Reversing the patches must restore those same tracked inputs, including build scripts and Makefiles, not only C and header files. Formatting follows the pinned native project's clang-format rules.

A feature build applies only the ordered patch entries from its manifest. Generated frameworks are placed into disposable product-source copies. The tracked baseline framework and source checkout remain unchanged. An application archive is therefore associated with both its exact source and the generated native implementation it actually links.

The main specification is mirrored by the root README. Shared build guidance, documentation rules, governing principles and upstream documentation are inherited byte-for-byte by descendants. A child's root README describes that child's functionality; the parent's README is retained under the branch-document path defined by the documentation contract.

## Design rationale and resource cost

A common unpatched baseline prevents accidental feature coupling and makes native patch order reviewable. Explicit immutable source inputs avoid depending on whatever a remote branch happens to contain during a build. Separate product copies prevent a generated binary from being confused with the source artifact that produced it.

These mechanisms operate in build and verification processes. They introduce no app timer, packet-processing allocation, observer, worker or networking layer. The underlying native server still uses resources according to its own implementation. A reproducible source inventory does not by itself establish binary reproducibility, application correctness or minimum energy consumption.

## Verification contract

`Tests/baseline_audit.py` exercises the real source-check functions in isolated Git fixtures. It verifies rejection of modified and staged native inputs, preservation of diagnostic records, invalidation of stale success markers and rejection of Python execution that disables required assertions. Negative controls establish that a checker distinguishes valid input from an implementation that omits the required safeguard.

The normal source checks are `python3 Build/check.py baseline` and `python3 Build/check.py composition`. The baseline contract invokes `Build/check_documentation.py`, which separately checks current-parent document copies, uniform authored structure, links and frozen non-document inputs. `Tests/documentation_contract.py` tests those documentation checks using disposable worktrees; it does not change app test oracles.

`bash Build/build.sh` runs the applicable native and model checks. On an Apple host, the relevant build route also creates the generated framework and application archive. Source checks, native execution, SDK compilation, archive creation, Simulator execution and physical-device execution are distinct results. A source ZIP alone does not provide the complete reachable Git objects required by the repository's exact-input controls.

## Operation and limitations

Use a clean full-history checkout and the commands selected by the checkout's feature manifest and workflow. Main is a baseline, not the integrated six-feature deliverable. Do not link a feature app against the committed unpatched framework when its public native interface requires a generated feature framework.

The committed baseline framework's inventory records Xcode 27.0 and iPhoneOS SDK 27.0 as its build environment. This identifies that checked-in artifact; it is not evidence of runtime execution on the target phone. Feature and release product checks use their own recorded SDK and generated framework rather than treating the baseline build environment as the device's environment.

The configured minimum iOS version is 17.2. The primary intended deployment is a physical iOS 27 device through SideStore standalone installation or LiveContainer guest execution. Those environments have different signing, containers, permissions and shared-session boundaries. Host and Simulator results do not certify either physical installation route, background survival or device power consumption.

## Related documents

The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) describes execution layers. The [documentation contract](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/documentation.md) defines inheritance and code preservation. The [upstream README](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/upstream/README.md) and [governing principles](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/top-level-principles.md) are retained as exact source documents.
