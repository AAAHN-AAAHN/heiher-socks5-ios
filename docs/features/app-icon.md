# Application icon — current-main resource verification

## Current status — 2026-09-26

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
is preserved for every unrelated file; configuration may change only its base_ref.
The normal icon entry never calls the generic archive/IPA path.

No resource/runtime defect requiring code or artwork changes was found. Added cost
is audit-time Git/hash/fixture work, not app allocations, threads, timers, disk logs
or network traffic. The source guards are checkpoint comparisons, not an atomic
adversarial snapshot of untracked inputs, external tools or transient modifications.

## Inspected new execution

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
