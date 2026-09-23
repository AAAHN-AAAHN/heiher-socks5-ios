# Build and validation

Use a complete clone of this repository so pinned feature and historical validation
commits are available. Install clang-format 18, Python 3 and Swift. For iOS use
Xcode 27 and iPhoneOS SDK 27. The minimum deployment target remains 17.2.

- `python3 Build/check.py baseline`: source pins, committed framework and main ancestry.
- `python3 Build/check.py composition`: declared features, UI/source wiring, owner hashes.
- `BUILD_IPA=0 bash Build/build.sh`: native and Swift checks, without application archive.
- `bash Build/check_swift_sdk.sh`: iOS 27 API type checking after headers are available.
- `bash Build/build.sh`: on macOS, rebuild the pinned native library and archive/package.

Only release/integrated is packaged by the new delivery workflow; the two split
feature jobs are checks-only. Native compilation and controller doubles are not
physical iOS tests. The production IPA requires the user's normal SideStore or
LiveContainer signing/import environment. No tool in this repository provisions
a user's certificate or changes a LiveContainer host.

Outputs are under artifacts/<composition>. Source provenance, exact test/build
commit, toolchain, logs and package hashes accompany the release. A test failure
fails its job; an IPA existing on disk is not the same as all jobs succeeding.
