# Application icon — current-main resource verification

## Final status — 2026-09-29

The icon-resource review and the identified verifier repairs are complete. Approved
artwork, app runtime and build settings are unchanged. Run36564261479 attempt2
passed the exact54-file source6b8a900073e4dbf06559a01c32c1ec08f5bb3fbc. The first
attempt's120second Simulator-install timeout remains recorded below; it was not
reclassified as success. Physical SideStore/LiveContainer and manual icon-mode
checks remain unperformed. The final documentation-only commit is not a new run.

## Previous completed review — 2026-09-26

This independent feature now inherits main75335d201cb1e541bb153e9899badbc11ccf1973
as an actual parent and exact base_commit. Run36225581121 attempt1 passed on source
39dea8c1f852bb0d927b01fa258adb4507a44e99, tree
531e85b92b6d0b44354f93c16f58d4083a7308ff, with53 tracked files. This completion
changes only README and its identical docs/features/app-icon.md; the other51 files
remain the executed bytes/modes. It does not modify the approved image or app.

The complete previous specification and execution history remain immutable at
https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/d08fdfb2b3187ec2e3aae3ffe1552e7c0a5e3af6/README.md
and in the companion before-source archive. The existing332-line historical file
at docs/history/app-icon-before-final-audit-20260926.md is byte-identical. Prior
failures/results belong to their own revisions; the new results below do not erase
them. docs/top-level-principles.md retains the user's four original instructions.

## Target, immutable asset and responsibility

The intended environment is a physical iOS27 iPhone: SideStore standalone and
LiveContainer guest are distinct signing, registration, container and host/cache
boundaries. Configured minimum iOS17.2 is not a claim of running every supported OS.
SDK compilation and Simulator launch are not either physical installation method.
A guest icon does not replace the LiveContainer host icon. No host patch, cache
removal, web-clip management, identity override, alternate-icon API, dynamic drawing,
image downloading, permissions or dependency on the other five features is added.
This is server/network artwork, not a system VPN badge or encryption claim.

The approved source remains Socks5/Assets.xcassets/AppIcon.appiconset/AppIcon.png:
1024x1024,3841 bytes,2-bit indexed PNG with four RGB palette entries. Its ordered
IHDR/PLTE/IDAT/IEND chunks contain no alpha,tRNS,animation,EXIF,ICC or text. Every
one of1048576 pixels is opaque. SHA-256:
4a2f2a9384e8b6db351a9284232db56e719377e60f17123e4a6992cee1799cc2.
Decoded RGB SHA-256:
c20aaf49d0fa8b12b551bb98937f818b334631290b77e17ee80bf985dd8bc08d.
These are this exact fixed resource's contract, not a generic PNG-format restriction.

Contents.json binds one universal iOS1024 slot. Debug/Release select AppIcon and
families1,2. Xcode generates CAR, primary-icon metadata and fallback PNGs; generated
bytes need not equal source bytes. Source/catalog/project/plist/runtime, hev.Socks5,
all pins and the shared16-file unpatched framework remain unchanged. Only Any artwork
is authored; light/dark system-UI captures do not certify manual Dark/Tinted/clear
selections or authored variants. No recoloring, resizing or resource migration occurs.

## Preserved audit repairs and current-main alignment

The validator fully decodes the fixed PNG with bounded decompression and checks
chunk boundaries, CRCs, pixels and catalog inventory without repairing input. Apple
ImageIO independently decodes source and compiler output. The existing13 methods
include30728 one-bit corruptions and malformed-PNG/catalog negative controls.

Compiled fallbacks require real files and whole standard filename variants, not
an arbitrary prefix glob, directories or empty basenames. CAR requires exact AppIcon
Icon Image entries for phone and pad,1024-square and opaque. Exact-old controls
retain false accepts for wrong suffix/type/name,missing idiom,dimensions or opacity.
Both audit entries invalidate stale SUCCESS/simulator-results before rejection and
record cleanup; failure propagation and all Simulator time limits are unchanged.
Python optimization is rejected, and commands use the repository root.

This alignment adopts the exact current-main shared build/check code and46-case
input fixture, with full native worktree/index/reversal checks and immutable generic
product copies. Icon source checks explicitly compare those inherited files to the
new main rather than accepting arbitrary modifications. The exact old input freeze
is preserved for every unrelated file; configuration may change only its base_commit.
The normal icon entry never calls the generic archive/IPA path.

No resource/runtime defect requiring code or artwork changes was found. Added cost
is audit-time Git/hash/fixture work, not app allocations, threads, timers, disk logs
or network traffic. The source guards are checkpoint comparisons, not an atomic
adversarial snapshot of untracked inputs, external tools or transient modifications.

## Previous inspected execution — 2026-09-26

The first-attempt Xcode27 job and artifact upload succeeded. All46 common cases,
13 retained resource methods/30728 mutations,38 compiled/input/marker/cwd boundary
cases in four methods and three original shell controls passed. Baseline, composition,
source scope and all entry/final worktree/index checks passed. No assertion, warning
rule, decoder or timeout was relaxed to obtain this result.

Actual Debug/Release settings retained AppIcon,families1,2,hev.Socks5 and minimum17.2.
iPhoneOS actool compiled the real catalog for phone and pad. Exact opaque1024 AppIcon
images and120/152-square fallback files passed compiled checks. ImageIO fully decoded
the source, two device and two Simulator fallback images as opaque single images.
Compiler output is not replaced by fixture JSON or rendered mockups.

The real Simulator Release app installed, registered and launched under hev.Socks5
and copied-test identity hev.Socks5.ICONREVIEW. Four original full-screen light/dark
system-UI captures were inspected and display the preserved icon and Socks5 label.
Cleanup is []; command failures were not ignored. This is simctl resource/registration
inspection, not an XCTest interaction suite or new native server functional audit.

Original artifact10900427492, SHA-256:
a2e45af553069cb0cb1bc5f158a2960b69466e9f9b8557ca0a515d6cbb154653.
Its digest,ZIP CRC,genuine source comment,53 paths/bytes/modes,complete source manifest
and Git tree were independently checked. Recorded environment is Xcode27.0 27A266a,
iPhoneOS27.0,Swift6.4,macOS27.0 26A428 and iPhone16 Simulator iOS27.0 24A434.
Retained destination/AppIntents diagnostics are not asset failures and are not hidden;
no universally warning-free or hang-free claim is made.

## Reproduction and remaining boundaries

Run bash Tests/AppIcon/run_checks.sh in a clean complete Git checkout with Xcode27.
Historical controls need actual Git objects. Source snapshots/offline integrity checks
are not new Apple or physical executions. Existing project/runtime/source pins are
unchanged; release must inherit this completed owner and run its combined checks.

SideStore signing/install,LiveContainer loading/guest-list/web-clip/cache behavior,
real device cache refresh,manual Dark/Tinted/clear modes,iPad runtime,other devices/OS
versions and energy remain unperformed. The generic iPhone archive/IPA job was skipped
in this resource-only run. No installer/host version or physical success is inferred.

## Final pre-release review — 2026-09-29

The approved PNG, catalog, both production Swift files, Xcode project/plist,
framework, source pins, main ancestry, shared build scripts and workflow are
preserved. No resource or runtime defect requiring artwork or app-code changes
has been identified. This review strengthens test-only boundaries and reruns the
existing Xcode27 resource/Simulator path. It does not create an IPA or integrate
other features. The code reviewed starts at639de66aa2265f3beffc1d0b433981d2e8073cb2.

Two compiled-reference cases previously accepted a single phone-specific PNG as
proof for the iPad mapping, or the reverse. The checker now requires a compatible
idiom or generic fallback for each mapping, and an actual filename array. Generic
and correctly paired device variants remain valid. The two prior positive fixture
expectations were false accepts and now require rejection; no input case is removed.

The independent ImageIO decoder previously accepted any opaque square up to1024
pixels, including a tiny PNG under a120px fallback name, a wrongly sized source,
a non-PNG image with a.png extension or an empty invocation. It now checks PNG type,
1024-square source dimensions and point-size/scale-derived fallback dimensions.
A new native-only driver runs17 fixtures against the exact prior and new decoder:
34 real ImageIO executions with positive source/2x/3x/fractional-pad cases and
negative size/type/name/opacity/empty cases. Synthetic fixtures never enter the app.
Apple compilation and exact-old/new decoder executions now passed as recorded below.

Simulator Assets.car is now inspected with the same phone/pad rendition contract
as device actool output. Both installed CFBundleIcons mappings, the installed
identity, and every generated icon PNG plus Assets.car must match the built app.
Only the copied test bundle's identity/signature differs. Seven isolated mutation
cases cover identity, iPad metadata, CAR, either PNG and extra files. The original
clean/dirty/index/optimization/marker/timeout and source PNG controls remain intact.

The Linux source suite passed13 methods including30728 one-bit mutations; the
updated audit-boundary suite passed5 methods/46 cases and all3 shell controls.
The filename helper was separately compiled with Linux Swift/Foundation; this is
not ImageIO or iOS evidence. A combined local launcher hit its own20second tool
limit after the boundary suite, so the remaining shell check ran separately; no
repository timeout was changed. The subsequent full-history Xcode27 execution passed on attempt2 as recorded below. Original failure/diagnostic evidence remains historical.

These changes add no app CPU/RAM work: no new runtime instructions, allocations,
threads, timers, image loader, network or API. Audit cost is compile-time/CI-only.
The static image and OS-rendered/cache resources still have a footprint;3841 source
bytes are not a promise of3841 resident bytes or zero system rendering cost. This
review does not claim a measured device-wide speedup, battery saving or zero bugs
across all OS and installation histories. Physical SideStore/LiveContainer and
manual icon appearances remain separate unperformed validations.

Reference contracts (not substitutes for this run):
https://developer.apple.com/documentation/xcode/configuring-your-app-icon
https://developer.apple.com/library/archive/qa/qa1686/_index.html
https://developer.apple.com/library/archive/documentation/2DDrawing/Conceptual/DrawingPrintingiOS/SupportingHiResScreensInViews/SupportingHiResScreensInViews.html

## Final exact-source results and retained failure

Tested commit6b8a900073e4dbf06559a01c32c1ec08f5bb3fbc has parent639de66a and tree
`e224bf788ed5e042399e8646d4f6c7966ac44273`. Run `36564261479` completed successfully
on attempt2; terminal metadata updated2026-09-29T12:05:03Z. Job109395512271 ran the
existing icon-checks workflow and uploaded the original artifact. The generic
archive/IPA verify job was intentionally skipped by the unchanged icon-only selector;
it is not a successful IPA build or an independent Linux job.

Attempt1/job109392245341 passed source, compiler and ImageIO checks and built the
Simulator app, then simctl install exceeded its original120second limit. The source
of that delay is not established. Shutdown/delete completed, cleanup was[], and no
SUCCESS or successful registration result was left. Its original artifact11031262494
is preserved. Attempt2 reran the same commit, assertions and deadlines on a new runner;
installation, registration, launch, uninstall and cleanup passed. No code, host,
cache, sleep allowance or timeout was changed to obtain the second result. This
comparison does not prove the environment cannot stall again.

| Verification layer | Inspected result |
| --- | --- |
| Full-history source scope | Exact main ancestry/pins, immutable artwork/catalog/app/project/plist/framework and shared scripts; baseline/composition and entry/final index/worktree checks passed. |
| Source decoder | 13 existing methods, including all30728 one-bit corruptions and malformed PNG/catalog negative controls, passed. Independent Pillow RGB hash agrees with the unchanged approved image. |
| Audit boundaries | 5 methods/46 cases plus3 original shell controls passed; 46 separate common baseline cases also passed. Cases use exact historical control blobs or deliberately isolated metadata, not fabricated native success. |
| Real Apple decoder | 17 fixtures/34 old/current executions passed. Nine formerly accepted invalid inputs now fail with their expected error domains, and prior non-square/transparency rejections remain. Valid source,120/180/152/167 and60pixel examples pass. |
| Device asset compilation | Actual iPhoneOS27 actool built phone/pad assets without asset warnings/errors. CAR contains exact AppIcon Icon Image records for both families,1024square and opaque. |
| Simulator product | Release app built; its own CAR passed the same contract. ImageIO decoded source1024 and device/Simulator120/152pixel fallbacks as complete opaque PNGs. All five decoded images retain the prior RGBA hashes. |
| Install/registration | hev.Socks5 and copied-test hev.Socks5.ICONREVIEW installed, registered, launched, terminated and uninstalled. Both phone/iPad mappings and all three icon-resource hashes match the built app. |
| Visible result | Four actual original/remapped light/dark system-UI screenshots were opened and show the unchanged icon and Socks5 label. This is not an XCTest interaction suite or a manual Dark/Tinted/clear icon-mode test. |
| Cleanup and evidence | cleanup=[]; successful command exits, source archive/manifest and output bytes inspected. Both attempt archives pass digest/CRC and contain identical54-file tested sources. |

Recorded tools: Xcode27.0 27A266a, iPhoneOS27.0, Apple Swift6.4
swiftlang-6.4.0.34.1, macOS27.0 26A428; iPhone16 Simulator iOS27.0 24A434.
The17 fixture verdicts include deliberate decoder errors; their failure diagnostics
are expected negative evidence, not crashes in the app. Xcode destination-selection
warnings and AppIntents metadata notices remain in raw logs. No universal
warning-free, hang-free, memory-free or physical deployment claim is made.

| Original archive | SHA-256 |
| --- | --- |
| Prior10900427492 / run36225581121 | a2e45af553069cb0cb1bc5f158a2960b69466e9f9b8557ca0a515d6cbb154653 |
| Attempt1 11031262494 | 08d90e907c98d75298af234f41ec0c3f419de8bb4c1277bf803dc0e12e052388 |
| Attempt2 11030969804 | 8738d77170b8171847808db631eef4f6531f4cf7b63bf2638f02ad07cd041352 |

The final closure changes only this README and its byte-identical feature
specification after testing. The other52 of54 paths retain tested bytes and Git
modes. The complete source change since639de66a is limited to those two documents
and four feature-owned audit paths (one newly added); every production path and
all48 common unchanged paths retain their original bytes/modes. No native patch,
asset recompression, alternate icon, dynamic image code or runtime API is introduced.
There is no new app CPU/RAM work from these audit-only changes; OS icon decoding,
rendering and caching are not free and were not measured as device footprint.

All identified icon-audit false accepts are closed within the executed scope.
This does not certify every possible input or transient filesystem/tool change.
Physical signing/install, SideStore standalone, LiveContainer guest/host/cache or
web-clip behavior, manual icon modes, iPad runtime and device energy remain distinct
unperformed checks. Release incorporation and any future IPA need their own exact
source/product validation. Other seven branch refs and release/build9 are unchanged.
