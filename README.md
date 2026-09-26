# Application icon — preserved artwork and verified resource integration

## Current review — 2026-09-26

This is the independent `feature/app-icon` branch. The audit starts at
`1beaefa4e068a3b4e9473bab478b27526b88defd`, on unchanged main
`d2534cd6bce7389fdf8f362bd8f681c0bd583eb1`. No defect requiring an artwork,
catalog, project or application-runtime change was found. The corrections below
close audit-input and compiled-resource validation gaps. New run 36204666461
completed on the exact source below; older successful runs were not substituted.
Physical installation/execution and untested appearance modes remain unperformed.

The complete former README is preserved byte-for-byte in
`docs/history/app-icon-before-final-audit-20260926.md`, including previous failures,
source/run/artifact identities and qualified results. Historical status applies to
those revisions. This README and `docs/features/app-icon.md` are identical and form
the current specification. The integrated release is maintained separately.

## Target environment and responsibility

The intended environment is a physical **iOS 27 iPhone**, either independently
installed through **SideStore** or executed as a **LiveContainer guest**. These have
different signing, container, registration and host-icon/cache boundaries. An SDK
compile or Simulator installation is not evidence of either physical path. The
configured minimum remains **iOS 17.2**; not every intervening OS has been executed.
Do not infer installer or host versions from the Apple build environment.

This feature supplies only the original application icon and standard resource
metadata. It adds no server patch, statistics, persistent settings, background
service, alternate-icon API, runtime drawing, image download or permission. It has
no dependency on the five sibling features. Original Swift sources and committed
native framework are unchanged from main. Existing single-scene/local-network plist
wiring predates this review and is preserved. Bundle ID remains `hev.Socks5`.

The icon depicts the existing server/network artwork. It is not a system VPN badge,
a claim of encryption or an additional protocol feature. Promotional mockups are
not OS screenshots and are not bundled. A guest icon does not replace LiveContainer's
own application icon; this feature adds no host modification, cache deletion or
web-clip management. Actual guest-list and host rendering remain untested here.

The four governing principles are preservation before minimal, simple and efficient
changes; use of the real SideStore/LiveContainer context; complete version, purpose,
scope, cost and limitation documentation; and distinct evidence for source, mocks,
SDK, CI, products, installation and physical execution. No asset migration or host
workaround is justified merely by an unverified rendering hypothesis.

## Immutable asset and normal integration

The source is `Socks5/Assets.xcassets/AppIcon.appiconset/AppIcon.png`:
1024 x 1024, 3841 bytes, 2-bit indexed PNG, four RGB palette entries. Its ordered
IHDR/PLTE/IDAT/IEND chunks contain no alpha, tRNS, animation, EXIF, ICC or text chunks.
All 1048576 pixels are opaque. The approved SHA-256 is
`4a2f2a9384e8b6db351a9284232db56e719377e60f17123e4a6992cee1799cc2`.
The full decoded RGB hash is
`c20aaf49d0fa8b12b551bb98937f818b334631290b77e17ee80bf985dd8bc08d`.
These identify this preserved artwork, not a general rule for every valid PNG.

Contents.json binds that filename to the one universal iOS 1024x1024 slot. Debug
and Release already select AppIcon with device families 1,2. Xcode generates the
asset catalog, primary-icon dictionaries and fallback PNGs; resized/compiler-
processed files are not expected to have the original source PNG hash. The normal
source catalog path is retained instead of adding Icon Composer or unused variants.
No recoloring, resampling, border, transparency or replacement image is introduced.

Only the original Any artwork is authored. Light/dark system-UI home captures do
not prove manual Dark/Tinted/clear icon selections or separately authored variants.
Masking and OS appearance transformations are not extra code in this application.

## Findings and minimal audit corrections

### Recorded HEAD versus actual working input

The shell previously archived HEAD while its validators/compiler read working
files. It now rejects both working-tree-versus-HEAD and index-versus-HEAD differences
before creating source evidence and before final success. This includes a staged
change whose working file has been restored. The compiled-check entry enforces the
same boundaries even when invoked directly. Commands are rooted at the repository,
not the caller's working directory. Python optimization is rejected so inherited
assert-based shared checks cannot silently disappear.

These are checkpoint comparisons, not atomic filesystem snapshots. They do not
certify unrelated untracked input, external toolchains or concurrent malicious
modification/restoration between checks. Use a clean, complete, isolated checkout.
The existing build/IPA scripts remain unchanged; this entry never calls them.

### Fallback filename false positives

The old compiled() accepted any `name*.png`, including a wrong suffix or a directory.
For example, a valid PNG renamed AppIcon60x60WRONG.png falsely satisfied a reference
to AppIcon60x60. The check now requires an actual file whose whole name matches the
extensionless base plus standard optional scale/device suffixes and .png. Empty
basenames are rejected. Tests retain accepted plain/@2x/@3x and phone/pad variants.
This is validation of this compiler-output contract, not a new image-loading API.
No generated or installed resource is renamed to make the check pass.

### Compiled catalog false positives

The earlier CAR check accepted any Name containing AppIcon. It did not require
actual icon images or both target idioms. The current check requires exact AppIcon
Icon Image records for phone and pad, at 1024x1024 with Opaque true. Exact-old AST
controls demonstrate false accepts for a substring-only name, wrong asset type,
missing pad, incorrect dimensions and transparency. The actual assetutil output
must pass this stronger gate; fixture JSON is not used as compiler evidence.

### Failed retries and stale installation verdicts

Both entries invalidate SUCCESS.txt and simulator-results.json before rejection
paths. The former direct compiled entry could retain both; the former shell could
retain the prior installation verdict. Previous diagnostic logs/screens remain,
but are not new execution evidence. Each completed cleanup writes cleanup.json;
errors still preserve the original failure and cause failure after otherwise
successful work. Simulator deadlines and error propagation are unchanged.

The new test_audit_boundaries.py executes exact-old/current bodies from Git blobs:
20 clean/unstaged/staged/index-only/optimized entry cases; eight fallback-name cases;
eight CAR metadata cases; and two real command-cwd controls. All 38 cases in four
methods passed locally. The SDK/archive boundary in entry fixtures deliberately
fails; it never substitutes for actual Xcode execution. The existing 13 resource
methods, all 30728 one-bit mutations, and three stale-shell controls remain intact.

## Validation procedure and evidence boundaries

Use a full Git checkout; historical controls and scope checks read exact Git objects.
On the Xcode 27 host run:

```sh
bash Tests/AppIcon/run_checks.sh
```

The branch's `[icon-checks-only]` push workflow performs resource validation without
calling the ordinary archive/IPA job. It retains baseline/composition/source-scope
checks; bounded complete PNG parsing, CRC/decompression/filter/palette decoding;
immutable hash and exact manifest tests; actual Debug/Release settings; iPhoneOS
actool for phone and pad; assetutil records; independent Apple ImageIO decoding;
and a real Simulator build using the committed native framework. Swift helper and
app warnings remain errors, with separate platform/build diagnostics retained.

The Simulator product is registered and launched under its original identity and
one copied test-bundle identity, `hev.Socks5.ICONREVIEW`. Only that test copy's
Info.plist changes, followed by ad-hoc signing. Both icon dictionaries, installed
resources and launches are checked, then four original/remapped light/dark-system-
UI home screens are captured. Visual review must confirm the icon is actually in
frame; capturing an empty screen is not appearance evidence. Cleanup must complete.
This is not SideStore signing, LiveContainer execution, App Store validation or a
physical-device launch. The native engine is not re-audited by the icon suite.

For completed execution, record source SHA/tree, run/attempt, exact toolchain and
runtime, decoded pixels, compiler metadata, process/job status, screenshots and
cleanup. Verify original artifact ZIP digest/CRC and source bytes/modes/manifest.
Failed and partially completed phases remain failures or limited evidence. The
companion offline verifier checks those identities, not a fresh SDK/device run.
A later documentation-only commit must match all tested non-document files.

## Costs and explicitly unperformed scope

All product inputs, PNG/catalog, runtime Swift, project/plist, source pins,
framework and shared build scripts are preserved. There is no new app timer, task,
thread, allocation policy, network path, resource decoder or permission. Audit Git,
hash, fixture, compiler and evidence work is test-only. Power, throughput and
physical rendering latency are not measured; no improvement amount is asserted.

Physical SideStore installation/signing/permissions, LiveContainer guest list/cache/
web-clip and loader behavior, actual iPhone icon-cache refresh, iPad runtime,
user-selected Dark/Tinted/clear modes, other OS/devices and App Store acceptance
remain unperformed for this source. No host patch or fixed signing identity is
assumed. Main, other feature branches, release/integrated and build 7 stay unchanged.
This review does not refresh the integrated application or create an IPA.

Primary platform contracts, not test results:
- https://developer.apple.com/documentation/xcode/configuring-your-app-icon
- https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleicons
- https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/CoreFoundationKeys.html

## Completed final audit — 2026-09-26

Run **36204666461**, attempt 1, executed source
`638c0cb2026b77c04874757c11bd9c8f0c9c311f`, tree
`e0c330d1c347629d3acb15aabd561071d18b533b`, with 50 tracked files.
The complete icon-checks job and artifact upload succeeded on the first attempt;
the normal archive/IPA job was intentionally skipped. No failed workflow attempt,
rerun, relaxed deadline or suppressed resource assertion was needed in this run.
The earlier 36055937895 artifact was used to reconstruct the audit input, not as
new execution evidence. Its complete historical results and failures remain archived.

All 13 retained resource methods, including all 30728 single-bit corruptions,
original malformed-PNG/catalog controls and immutable artwork checks passed.
All 38 new boundary cases in four methods and the three previous shell controls
passed on the Apple host as well as locally. These cases deliberately reject
invalid inputs; they are not 38 product defects or physical-device trials.
Baseline/composition/source-scope and all four input/final worktree/index logs pass.
The source and original history bytes are unchanged where required.

Actual Debug/Release settings select AppIcon, families 1,2, hev.Socks5 and minimum
17.2. iPhoneOS actool compiled the full real catalog for phone and pad without
asset warnings/errors. The stronger assetutil check found exact AppIcon Icon Image
records for both idioms, each opaque and 1024x1024. Fallback references resolve to
AppIcon60x60@2x.png (120x120) and AppIcon76x76@2x~ipad.png (152x152).
ImageIO decoded the source and both device fallbacks and the two Simulator fallbacks
completely as single images with every pixel opaque. The source RGB/RGBA hashes
also match independent local decoding. Device and Simulator fallback file hashes
can differ while their decoded RGBA hashes match, as observed here.

The actual Simulator Release app built, registered and launched under hev.Socks5
and the separate copied-test identity hev.Socks5.ICONREVIEW. All four original
full-screen light/dark-system-UI captures were opened and visibly contain the
preserved Socks5 icon and label. These are real Simulator captures, not generated
mockups, manual Dark/Tinted/clear icon coverage or SideStore/LiveContainer results.
All recorded subprocess exits are zero; shutdown/delete completed and cleanup.json
is []. This suite uses simctl registration/launch and inspection, not an XCTest
UI-interaction suite or a native server functional re-audit.

Actual environment: Xcode 27.0 `27A266a`, iPhoneOS SDK 27.0, Apple Swift 6.4
`swiftlang-6.4.0.34.1`, macOS 27.0 `26A428`; iPhone 16 Simulator iOS 27.0
`24A434`. The Simulator build retains two non-asset warnings: multiple matching
destinations and skipped AppIntents metadata extraction. Destination diagnostics
also remain in build-setting command logs. No claim of universally warning-free
or hang-free execution is made.

Original new artifact **10893786621**, SHA-256
`28275b03f5effe820d123848a00730eb205c5000c44283ad7fe1ff8116ad4bd3`,
passed digest/CRC, genuine source-comment, all 50 path/byte/mode and source-manifest
checks. The source archive reconstructs the exact tested Git tree. Final result
documentation changes only this README and its identical specification; the other
48 files remain identical to the executed source. Five existing paths change and
two are added relative to the 48-file audit input; 43 existing files are preserved.
All product resources, app/runtime, project/plist, workflow, shared build scripts,
framework and pins remain byte-for-byte and mode-for-mode unchanged.

Local container clone was unavailable because github.com DNS failed; verified
connector archives and exact blobs supplied the reconstruction, not a full clone.
A supplemental local Pillow attempt could not decode the device-compiled PNGs,
which contain CgBI chunks; the error and chunk CRC checks are retained separately.
It is not counted as a successful Pillow decode or an Apple/product failure.
Actual Apple ImageIO decoding above succeeded on those exact bytes. No image was
rewritten or test weakened to hide that local-decoder limitation.

The companion evidence preserves before/tested/final source snapshots, complete
patch and original artifacts. Its offline verifier checks hashes/trees, documented
outcomes and exact forward/reverse patch reconstruction, not fresh Apple or physical
execution. The branch is complete within these executed source/resource/compiler/
Simulator boundaries. Main, other features, integrated release and build 7 remain
unchanged; physical installation and all unperformed boundaries above remain open.
