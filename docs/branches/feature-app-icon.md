# Static application icon and asset validation

## Purpose and scope

This feature supplies the approved application icon through the standard asset catalog and verifies that the compiled and installed application uses the intended assets. It does not introduce runtime icon generation, alternate-icon switching, background activity or a new appearance-management subsystem.

The approved source artwork is preserved byte-for-byte. The feature extends the shared application baseline through the catalog and project configuration; it does not change the upstream server interface or implement other feature behavior.

## Functional behavior

The project selects the AppIcon asset set through the ordinary Xcode app-icon configuration. The source is a 1,024 by 1,024 PNG with an indexed palette and fully opaque pixels. The operating system and asset compiler produce and display the appropriate device representations.

The Xcode target declares both phone and tablet device families; that declaration is not evidence of an executed iPad runtime test. The compiled icon metadata must associate each family with an appropriate icon image or common fallback. A phone-specific image alone is not proof of a valid tablet mapping, or vice versa. Original and remapped application identifiers must retain the same intended icon resources after installation.

The feature has no independent user setting and does not change its icon in response to server, statistics, location or audio state. System light/dark UI presentation is not the same thing as a custom Dark, Tinted or clear icon variant.

## Implementation and ownership

The source files are `Socks5/Assets.xcassets/AppIcon.appiconset/AppIcon.png` and its `Contents.json`. The Xcode project references the AppIcon set, and the source image is compiled into the application asset catalog and generated fallback PNGs. Source identity is checked independently from compiler-produced compressed bytes.

The authored catalog supplies one universal iOS 1024 slot. The approved PNG is 3,841 bytes, uses a 2-bit indexed palette with four RGB entries and has no transparency chunk; all 1,048,576 pixels are opaque. These properties identify the approved resource rather than restrict PNG images in general. No separate authored Dark or Tinted artwork is supplied. Source-file and decoded-pixel fingerprints are enforced by the source checker, while compiler outputs are decoded and compared under their own size/family contract.

The source-image checker validates PNG signature, chunk boundaries, declared lengths and CRCs, complete decompression, exact dimensions and opacity. The source pixel content and file fingerprint bind the approved artwork. Recompression, resizing or a visually similar replacement is not silently accepted as the same source.

The compiled-asset checks inspect the application's plist icon dictionaries, Assets.car representations and generated files. Filename point size and scale determine the required pixel dimensions. Apple ImageIO verifies that files are actual PNG images, have the expected square dimensions and are opaque. Empty input and a different image format renamed to PNG are not accepted as successful decoding.

Installation checks compare the registered bundle identifier, icon metadata and the complete installed Assets.car/fallback-image fingerprints with the built application. Phone and tablet metadata are checked separately. A registration test does not infer installation identity from a filename alone.

All validation helpers and image fixtures remain outside the application target. Source checks preserve the application code, native inputs and baseline framework while allowing only the declared icon/catalog/project behavior.

## Design rationale and resource cost

A static catalog uses the platform's intended icon mechanism and avoids extra lifecycle state or per-launch work. One approved source avoids redundant hand-maintained device-size images and makes source identity reviewable. Comparing decoded pixels as well as file structure prevents format or metadata errors from being hidden by a superficial filename check.

There is no app timer, network call, dynamic renderer, icon-switching API, observer or extra cache manager for this feature. The asset compiler and operating system still incur storage, decode, rendering and cache costs. The small compressed source-file size is not a measurement of physical RAM use, and static integration does not establish zero energy cost.

## Verification contract

`Tests/AppIcon` separates source PNG/catalog validation, checker-boundary regressions, actual Apple decoding and compiled-asset/installation checks. Deliberate invalid inputs cover damaged chunks, inconsistent dimensions, transparency, format mismatch, incorrect device-family mapping and missing metadata. Valid catalog shapes remain accepted.

The source scope verifies exact native/app inputs and project settings. Current parent prose and document structure are checked independently through the document contract. Runtime-source comparisons, source artwork identity and compiled resource expectations remain enforced.

On an Apple host, actool compiles the real catalog for the declared device targets. Assets.car and fallback checks run on device and Simulator products. The Simulator route installs, inspects, launches, terminates and removes original and remapped bundle identities and retains the actual screen evidence. Source parsing, SDK/asset compilation, installation metadata, execution and visible rendering are separate results.

## Operation and limitations

Use the branch's AppIcon workflow or its existing `Tests/AppIcon/run_checks.sh` route with the required Apple tools for compiled and installation checks. A source-only PNG pass is not sufficient evidence for the generated catalog or installed application. A feature-check workflow that omits an IPA archive does not create a device-installable product.

The configured minimum iOS version is 17.2 and the primary target is physical iOS 27 through SideStore standalone or LiveContainer guest execution. Signing, icon registration, host guest lists, web clips and device caches can differ from Simulator behavior. Physical icon-cache behavior, manually selected appearance modes, iPad runtime and installer-specific display require separate tests. No host cache deletion or speculative identity override is part of this implementation.

## Related documents

The [shared baseline](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/main-baseline.md) defines preserved application inputs. The [build and verification guide](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/build-and-validation.md) defines product and execution layers. `docs/documentation.json` describes the branch's inherited documents and frozen non-document files.
