# Application icon

## Purpose

`feature/app-icon` adds the existing SOCKS5 application icon to the combined main baseline
without adding networking, settings, background services, or runtime code. It is a
presentation feature only. The integrated release reuses the same asset bytes.

The icon represents a server and bidirectional network relay. It is not a system VPN
badge, a claim of encryption, a WireGuard server feature, or an affiliation with
Apple/Hev beyond the source project being used. Earlier generated promotional
mockups in the conversation are not screenshots and are not bundled into the app.

## Files and integration

`Socks5/Assets.xcassets/AppIcon.appiconset/AppIcon.png` is the previously delivered
1024 by 1024 opaque image. `Contents.json` binds it to the universal iOS app icon.
The upstream Xcode target already selects AppIcon, so no custom image loader,
runtime drawing, network image download, or extra dependency is necessary.
The normal asset compiler produces the device icon resources and Info.plist icon
metadata during an archive. Source catalogs and archived resources are different
representations; comparing their file hashes would not be meaningful.

## Resource impact and style

There is no additional timer, actor, task, allocation policy, or networking path.
The only stored application content is the image and standard asset metadata.
The system renders and masks app icons; a second icon view is not injected into
the existing server interface. The image is not used as a splash advertisement.
Icon source and metadata are preserved across feature and integrated builds.

## Validation

The build verifies the PNG signature, width/height and opaque RGB/palette format,
and checks that AppIcon is selected by the Xcode target. The archived app is checked
for Assets.car, CFBundleIcons/CFBundlePrimaryIcon and the AppIcon name. Other branches
that intentionally retain upstream's empty icon catalog do not incorrectly claim to
have the custom icon. The final integration membership manifest also records the
image's SHA-256 so accidental replacement is detectable.

This feature has no behavioral unit tests because it has no executable behavior.
It does have asset validation and an actual ARM64 iPhone archive on its branch.
See the workflow artifacts for source ZIP, archive log and unsigned IPA. Installation
requires signing, for example using the owner's existing SideStore setup. Nothing
in this branch changes the bundle identifier, requests additional account access,
or grants background execution.
