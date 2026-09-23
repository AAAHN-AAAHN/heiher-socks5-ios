#!/bin/bash
# Build a declared composition from exact sources. No repository writes or ref changes.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
NAME=$(python3 -c 'import json; print(json.load(open("Build/features.json"))["name"])')
OUT="$ROOT/artifacts/$NAME"
CORE="$ROOT/.build/core"
mkdir -p "$OUT"
python3 Build/check.py baseline > "$OUT/baseline-audit.log"
SERVER_REF=$(python3 -c 'import json; print(json.load(open("Build/upstream.json"))["sources"]["."])')
if [ ! -d "$CORE/.git" ]; then
    git clone --no-checkout https://github.com/heiher/hev-socks5-server.git "$CORE"
    git -C "$CORE" checkout --detach "$SERVER_REF"
    git -C "$CORE" submodule update --init --recursive
fi
python3 Build/check.py apply "$CORE" > "$OUT/source-audit.log"
CF=$(command -v clang-format-18 || command -v clang-format)
"$CF" --version | grep -E 'version 18\.'
python3 Build/check.py format "$CORE" "$CF" >> "$OUT/source-audit.log"
python3 Build/check.py composition >> "$OUT/source-audit.log"
cp Build/features.json "$OUT/features.json"
{
    git rev-parse HEAD
    git -C "$CORE" rev-parse HEAD
    git -C "$CORE" submodule status --recursive
} > "$OUT/build-info.txt"
feature() { python3 -c 'import json,sys; sys.exit(sys.argv[1] not in json.load(open("Build/features.json"))["features"])' "$1"; }
# The shared dispatcher exercises the actual compiled I/O mode and the full
# retained UDP/statistics probes instead of inferring modes from CFLAGS labels.
python3 Build/native_checks.py "$CORE" "$OUT/native" > "$OUT/native-checks.log" 2>&1
make -C "$CORE" clean > "$OUT/native-clean.log" 2>&1
if feature background; then
    python3 Tests/Background/run_checks.py > "$OUT/background.log" 2>&1
    if [ "$(uname -s)" = Darwin ]; then
        python3 Tests/Background/check_subscription.py > "$OUT/background-subscription.log" 2>&1
        swift Tests/Background/check_silence.swift Socks5/BackgroundKeepAlive/Silence.wav > "$OUT/decoded-silence.log"
    fi
fi
if feature server; then
    python3 Tests/ServerControl/run_checks.py > "$OUT/server-control.log" 2>&1
fi
if feature settings; then
    python3 Tests/Settings/run_checks.py > "$OUT/settings.log" 2>&1
    python3 Tests/Settings/run_checks.py --baseline-import > "$OUT/original-import-negative.log" 2>&1
fi
if [ "$(uname -s)" = Darwin ]; then
    MODULE="$ROOT/.build/typecheck-module"
    mkdir -p "$MODULE"
    cp "$CORE/src/hev-main.h" "$MODULE/hev-main.h"
    printf 'module HevSocks5Server { header "hev-main.h" export * }\n' > "$MODULE/module.modulemap"
fi
if [ "$(uname -s)" = Darwin ] && [ "${BUILD_IPA:-1}" = 1 ]; then
    (cd "$CORE" && ./build-apple.sh) > "$OUT/core-apple.log" 2>&1
    rm -rf HevSocks5Server.xcframework
    cp -R "$CORE/HevSocks5Server.xcframework" .
    xcodebuild archive -project Socks5.xcodeproj -scheme Socks5 -configuration Release \
        -sdk iphoneos -destination 'generic/platform=iOS' \
        -archivePath "$ROOT/.build/$NAME.xcarchive" \
        CODE_SIGN_IDENTITY='' CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO \
        SWIFT_TREAT_WARNINGS_AS_ERRORS=YES \
        MARKETING_VERSION=1.1.0 CURRENT_PROJECT_VERSION=6 \
        > "$OUT/app-build.log" 2>&1
    APP="$ROOT/.build/$NAME.xcarchive/Products/Applications/Socks5.app"
    xcrun lipo "$APP/Socks5" -verify_arch arm64
    python3 Build/check.py package "$APP" > "$OUT/package.log"
    mkdir -p "$ROOT/.build/package-$NAME/Payload"
    ditto "$APP" "$ROOT/.build/package-$NAME/Payload/Socks5.app"
    (cd "$ROOT/.build/package-$NAME" && zip -qr "$OUT/Socks5-$NAME-unsigned.ipa" Payload)
    unzip -t "$OUT/Socks5-$NAME-unsigned.ipa" >> "$OUT/package.log"
    ditto -c -k --keepParent "$ROOT/.build/$NAME.xcarchive/dSYMs" "$OUT/Socks5-dSYMs.zip"
    git archive --format=zip HEAD -o "$OUT/Socks5-$NAME-source.zip"
    (cd "$OUT" && shasum -a 256 *.ipa > SHA256SUMS.txt)
fi
python3 Build/check.py reverse "$CORE" >> "$OUT/source-audit.log"
printf 'PASS: %s build and applicable checks completed\n' "$NAME" | tee "$OUT/SUCCESS.txt"
