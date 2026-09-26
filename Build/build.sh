#!/bin/bash
# Build a declared composition from exact sources. No repository writes or ref changes.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
NAME=$(python3 -c 'import json; print(json.load(open("Build/features.json"))["name"])')
OUT="$ROOT/artifacts/$NAME"
CORE="$ROOT/.build/core"
mkdir -p "$OUT"
# A rejected retry must not retain the previous overall verdict.
rm -f "$OUT/SUCCESS.txt"
python3 -c 'import sys; sys.exit(0 if __debug__ else "Assertions must be enabled.")'
git diff --exit-code HEAD -- > "$OUT/input-worktree.log"
git diff --cached --exit-code HEAD -- > "$OUT/input-index.log"
python3 Build/check.py baseline > "$OUT/baseline-audit.log"
python3 Tests/baseline_audit.py > "$OUT/baseline-driver.log" 2>&1
git rev-parse HEAD > "$OUT/tested-commit.txt"
git archive --format=zip HEAD -o "$OUT/source.zip"
git bundle create "$OUT/history.bundle" HEAD
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
mode=buffered
for flags in '' '-DENABLE_IO_SPLICE_SYSCALL'; do
    if [ -n "$flags" ]; then
        if [ "$(uname -s)" != Linux ] || ! feature statistics; then break; fi
        mode=splice
    fi
    make -C "$CORE" -j3 CFLAGS="$flags" static exec > "$OUT/$mode-build.log" 2>&1
    python3 Tests/tcp_smoke.py "$CORE/bin/hev-socks5-server" > "$OUT/$mode-tcp.log"
    if feature udp; then
        python3 Tests/udp_sockaddr_regression.py "$CORE/bin/hev-socks5-server" \
            --output "$OUT/$mode-protocol.json" > "$OUT/$mode-protocol.log" 2>&1
    fi
    if feature statistics; then
        cc -std=gnu11 -O2 -Wall -Werror -pthread -I"$CORE/src" Tests/traffic_stats_host.c \
            "$CORE/bin/libhev-socks5-server.a" "$CORE/third-part/yaml/bin/libyaml.a" \
            "$CORE/third-part/hev-task-system/bin/libhev-task-system.a" -o "$OUT/stats-host"
        python3 Tests/traffic_stats_regression.py "$OUT/stats-host" \
            > "$OUT/$mode-statistics.log" 2>&1
        rm "$OUT/stats-host"
    fi
    if feature settings; then
        cc -std=gnu11 -O2 -Wall -Werror -pthread -I"$CORE/src" Tests/server_lifecycle_host.c \
            "$CORE/bin/libhev-socks5-server.a" "$CORE/third-part/yaml/bin/libyaml.a" \
            "$CORE/third-part/hev-task-system/bin/libhev-task-system.a" -o "$OUT/lifecycle-host"
        python3 Tests/server_lifecycle_regression.py "$OUT/lifecycle-host" > "$OUT/$mode-lifecycle.log" 2>&1
        rm "$OUT/lifecycle-host"
    fi
    make -C "$CORE" clean >> "$OUT/$mode-build.log" 2>&1
done
if feature statistics; then
    swiftc Socks5/Statistics/TrafficStatistics.swift Tests/traffic_statistics_model.swift -o "$OUT/stats-model"
    "$OUT/stats-model" > "$OUT/statistics-model.log"
    rm "$OUT/stats-model"
fi
if feature background; then
    python3 Tests/Background/run_checks.py > "$OUT/background.log" 2>&1
    if [ "$(uname -s)" = Darwin ]; then
        swift Tests/Background/check_silence.swift Socks5/BackgroundKeepAlive/Silence.wav > "$OUT/decoded-silence.log"
    fi
fi
if feature settings; then
    python3 Tests/Settings/run_checks.py > "$OUT/settings.log" 2>&1
fi
if [ "$(uname -s)" = Darwin ]; then
    (cd "$CORE" && ./build-apple.sh) > "$OUT/core-apple.log" 2>&1
    # Keep the committed baseline and all later source checks untouched.
    PRODUCT="$ROOT/.build/$NAME-product-source"
    test ! -e "$PRODUCT"
    mkdir -p "$PRODUCT"
    git archive HEAD | tar -x -C "$PRODUCT"
    rm -rf "$PRODUCT/HevSocks5Server.xcframework"
    cp -R "$CORE/HevSocks5Server.xcframework" "$PRODUCT/"
    xcodebuild archive -project "$PRODUCT/Socks5.xcodeproj" -scheme Socks5 -configuration Release \
        -sdk iphoneos -destination 'generic/platform=iOS' \
        -archivePath "$ROOT/.build/$NAME.xcarchive" \
        CODE_SIGN_IDENTITY='' CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO \
        > "$OUT/app-build.log" 2>&1
    APP="$ROOT/.build/$NAME.xcarchive/Products/Applications/Socks5.app"
    xcrun lipo "$APP/Socks5" -verify_arch arm64
    python3 Build/check.py package "$APP" > "$OUT/package.log"
    rm -rf "$ROOT/.build/package-$NAME"
    mkdir -p "$ROOT/.build/package-$NAME/Payload"
    ditto "$APP" "$ROOT/.build/package-$NAME/Payload/Socks5.app"
    rm -f "$OUT/Socks5-$NAME-unsigned.ipa"
    (cd "$ROOT/.build/package-$NAME" && zip -qr "$OUT/Socks5-$NAME-unsigned.ipa" Payload)
    unzip -t "$OUT/Socks5-$NAME-unsigned.ipa" >> "$OUT/package.log"
    ditto -c -k --keepParent "$ROOT/.build/$NAME.xcarchive/dSYMs" "$OUT/Socks5-dSYMs.zip"
    git archive --format=zip HEAD -o "$OUT/Socks5-$NAME-source.zip"
    (cd "$OUT" && shasum -a 256 *.ipa > SHA256SUMS.txt)
fi
python3 Build/check.py reverse "$CORE" >> "$OUT/source-audit.log"
git diff --exit-code HEAD -- > "$OUT/final-worktree.log"
git diff --cached --exit-code HEAD -- > "$OUT/final-index.log"
printf 'PASS: %s build and applicable checks completed\n' "$NAME" | tee "$OUT/SUCCESS.txt"
