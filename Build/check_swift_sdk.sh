#!/bin/bash
# Type checking only. The release archive is built separately by Build/build.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=$(python3 -c 'import json; print(json.load(open("Build/features.json"))["name"])')
OUT="$PWD/artifacts/$NAME"
mkdir -p "$OUT"
xcodebuild -version | tee "$OUT/toolchain.txt"
xcrun --sdk iphoneos --show-sdk-version | tee -a "$OUT/toolchain.txt" | grep -E '^27\.'
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
MODULE=HevSocks5Server.xcframework/ios-arm64/Headers
if [ -f .build/typecheck-module/hev-main.h ]; then MODULE=.build/typecheck-module; fi
SOURCES=()
while IFS= read -r source; do SOURCES+=("$source"); done < <(find Socks5 -name '*.swift' -type f | sort)
xcrun swiftc -typecheck -swift-version 5 -warnings-as-errors -sdk "$SDK" \
    -target arm64-apple-ios17.2 -I "$MODULE" \
    "${SOURCES[@]}" > "$OUT/ios-sdk-typecheck.log" 2>&1
printf 'PASS: %s production Swift files typechecked; not device execution\n' "${#SOURCES[@]}" > "$OUT/sdk-success.txt"
