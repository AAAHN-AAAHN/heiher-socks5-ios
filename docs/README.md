# Documentation map

## Purpose and scope

This directory describes the implemented application, its feature ownership and its verification contracts. The root README identifies the current checkout's composition. The documents explain what each feature does, how its code is organized, why that design is used and which observations do or do not verify it.

## Functional behavior

The shared baseline, build guidance and documentation contract are common to the branch family. Feature-specific implementation guides are stored in `docs/features`. Parent root READMEs are retained in `docs/branches`; the upstream README is retained in `docs/upstream`. The upstream license remains at the repository root.

Each child contains its parent's complete document set without rewriting the parent's prose. The current branch's own README is mirrored by its specification. Duplicate shared paths have the same contents, not independently edited copies.

## Implementation and ownership

The machine-readable `docs/documentation.json` maps current document parents and owned guide paths. Functional ownership and native source inputs remain in their separate build and membership manifests. `docs/top-level-principles.md` contains the exact governing instructions.

The feature guides are `udp-compatibility.md`, `traffic-statistics.md`, `server-control.md`, `settings-persistence.md`, `background.md` and `app-icon.md`, present where that feature is inherited. `integrated.md` describes the release composition. The absence of a sibling's guide from an independent feature does not imply that sibling code is linked into that branch.

## Design rationale and resource cost

A feature-oriented document tree avoids duplicating progress narratives in every branch. Exact parent copies keep the explanation of a shared implementation under one owner. Separate branch READMEs preserve context where root names necessarily collide.

Documents and their validators are not application resources. Their organization adds no runtime service, packet path or persistence operation.

## Verification contract

The documentation checker verifies structure, links, complete inheritance, mirrors and frozen-code identity. The implementation guides describe the actual model, socket, SDK, product and UI tests separately. Document inventory and link validity do not establish behavioral coverage.

## Operation and limitations

Start with the root README, then use the shared baseline and the guides for the features declared by `Build/features.json`. Use a full-history checkout for verification commands that rely on exact Git source objects. Distinguish configured minimum OS, intended physical deployment and actually executed test environments.

Physical SideStore standalone and LiveContainer guest behavior is not certified merely by a well-formed document, a host test or a Simulator result. Each relevant feature guide records its deployment limitations.

## Related documents

Read the [shared baseline](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/main-baseline.md), [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) and [documentation contract](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/documentation.md). The [upstream README](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/upstream/README.md) is preserved independently of this map.
