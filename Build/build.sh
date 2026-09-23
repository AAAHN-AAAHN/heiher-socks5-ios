#!/bin/bash
# Validate exact declared sources; only an explicit non-checks build archives an IPA.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
MODE="${1:-build}"
case "$MODE" in build|--checks-only) ;; *) echo 'Use no argument or --checks-only' >&2; exit 2;; esac
NAME=$(python3 -c 'import json; print(json.load(open("Build/features.json"))["name"])')
OUT="$ROOT/artifacts/$NAME"
CORE="$ROOT/.build/core"
mkdir -p "$OUT"
rm -f "$OUT/SUCCESS.txt"
git rev-parse HEAD > "$OUT/tested-commit.txt"
git rev-parse 'HEAD^{tree}' > "$OUT/tested-tree.txt"
git archive --format=zip HEAD -o "$OUT/Socks5-$NAME-source.zip"
git diff --check "$(python3 -c 'import json; print(json.load(open("Build/features.json"))["base_commit"])')" HEAD -- . ':(exclude)Patches/*.patch' > "$OUT/whitespace.log"
python3 Build/check.py baseline > "$OUT/baseline.log"
python3 Build/check.py composition > "$OUT/composition.log"
python3 Build/verify_split.py > "$OUT/ownership.json"
feature() { python3 -c 'import json,sys; sys.exit(sys.argv[1] not in json.load(open("Build/features.json"))["features"])' "$1"; }
if feature server-runtime; then
    python3 Tests/ServerRuntime/run_checks.py > "$OUT/server-runtime.log" 2>&1
fi
if feature config-persistence; then
    python3 Tests/Settings/run_checks.py > "$OUT/config-persistence.log" 2>&1
    python3 Tests/Settings/run_checks.py --baseline-import > "$OUT/original-import-negative.log" 2>&1
fi
if feature background; then
    python3 Tests/Background/run_checks.py > "$OUT/background.log" 2>&1
    if [ "$(uname -s)" = Darwin ]; then
        python3 Tests/Background/check_subscription.py > "$OUT/background-subscription.log" 2>&1
        swift Tests/Background/check_silence.swift Socks5/BackgroundKeepAlive/Silence.wav > "$OUT/decoded-silence.log" 2>&1
    fi
fi
SERVER_REF=$(python3 -c 'import json; print(json.load(open("Build/features.json"))["sources"]["."])')
if [ -e "$CORE" ]; then echo 'Use a clean .build/core for a new run' >&2; exit 2; fi
git clone --no-checkout https://github.com/heiher/hev-socks5-server.git "$CORE" > "$OUT/clone.log" 2>&1
git -C "$CORE" checkout --detach "$SERVER_REF" >> "$OUT/clone.log" 2>&1
git -C "$CORE" submodule update --init --recursive >> "$OUT/clone.log" 2>&1
python3 Build/check.py apply "$CORE" > "$OUT/native-sources.log"
CF=$(command -v clang-format-18 || command -v clang-format)
"$CF" --version | tee "$OUT/formatter.txt" | grep -E 'version 18\.'
python3 Build/check.py format "$CORE" "$CF" >> "$OUT/native-sources.log"
python3 Build/native_checks.py "$CORE" "$OUT/native" > "$OUT/native-checks.log" 2>&1
if [ "$(uname -s)" = Darwin ]; then
    xcodebuild -version > "$OUT/toolchain.txt"
    xcrun --sdk iphoneos --show-sdk-version | tee -a "$OUT/toolchain.txt" | grep -E '^27\.'
    xcrun swiftc --version >> "$OUT/toolchain.txt"
    # Generated headers include statistics declarations; the committed framework is
    # an immutable unpatched baseline and must not masquerade as the patched build.
    MODULE="$ROOT/.build/typecheck-module"
    mkdir -p "$MODULE"
    cp "$CORE/src/hev-main.h" "$MODULE/hev-main.h"
    printf 'module HevSocks5Server { header "hev-main.h" export * }\n' > "$MODULE/module.modulemap"
    SDK=$(xcrun --sdk iphoneos --show-sdk-path)
    mapfile_compat=() # macOS bash 3 has no mapfile; repository source paths have no spaces.
    while IFS= read -r path; do mapfile_compat+=("$path"); done < <(find Socks5 -name '*.swift' | LC_ALL=C sort)
    xcrun swiftc -typecheck -swift-version 5 -warnings-as-errors -sdk "$SDK" \
        -target arm64-apple-ios17.2 -I "$MODULE" "${mapfile_compat[@]}" > "$OUT/ios-typecheck.log" 2>&1
    plutil -lint Socks5/Info.plist Socks5.xcodeproj/project.pbxproj > "$OUT/project.log"
    if [ "$MODE" = build ]; then
        make -C "$CORE" clean > "$OUT/native-clean.log" 2>&1
        (cd "$CORE" && ./build-apple.sh) > "$OUT/core-apple.log" 2>&1
        rm -rf HevSocks5Server.xcframework
        cp -R "$CORE/HevSocks5Server.xcframework" .
        xcodebuild archive -project Socks5.xcodeproj -scheme Socks5 -configuration Release \
            -sdk iphoneos -destination 'generic/platform=iOS' -archivePath "$ROOT/.build/$NAME.xcarchive" \
            CODE_SIGN_IDENTITY='' CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO \
            SWIFT_TREAT_WARNINGS_AS_ERRORS=YES > "$OUT/app-build.log" 2>&1
        APP="$ROOT/.build/$NAME.xcarchive/Products/Applications/Socks5.app"
        xcrun lipo "$APP/Socks5" -verify_arch arm64
        python3 Build/check.py package "$APP" > "$OUT/package.log"
        mkdir -p "$ROOT/.build/package/Payload"
        ditto "$APP" "$ROOT/.build/package/Payload/Socks5.app"
        (cd "$ROOT/.build/package" && zip -qr "$OUT/Socks5-$NAME-unsigned.ipa" Payload)
        unzip -t "$OUT/Socks5-$NAME-unsigned.ipa" >> "$OUT/package.log"
        ditto -c -k --keepParent "$ROOT/.build/$NAME.xcarchive/dSYMs" "$OUT/Socks5-dSYMs.zip"
        python3 Build/check_release_package.py "$APP" "$OUT/Socks5-$NAME-unsigned.ipa" > "$OUT/package-details.json"
        (cd "$OUT" && shasum -a 256 *.ipa > SHA256SUMS.txt)
    fi
fi
python3 Build/check.py reverse "$CORE" > "$OUT/reverse.log"
python3 - <<'PY' > "$OUT/committed-source-sha256.json"
import hashlib,json,subprocess
paths=subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD'],text=True).splitlines()
print(json.dumps({p:hashlib.sha256(subprocess.check_output(['git','show','HEAD:'+p])).hexdigest() for p in paths},indent=2))
PY
printf 'PASS: %s declared checks (%s). See individual logs; no physical-device or installer claim.\n' "$NAME" "$MODE" > "$OUT/SUCCESS.txt"
