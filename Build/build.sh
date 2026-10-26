#!/bin/bash
# Build a declared composition without changing tracked source or refs.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
case "${1:-server}" in
    server) ;;
    tunnel) exec bash Build/build-tunnel.sh ;;
    *) echo 'Unknown native build target' >&2; exit 1 ;;
esac
NAME=$(python3 -c '
import json, re
name = json.load(open("Build/features.json"))["name"]
if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9-]*", name) is None:
    raise SystemExit("Invalid composition name")
print(name)')
OUT="$ROOT/artifacts/$NAME"
CORE="$ROOT/.build/server"
for path in "$ROOT/artifacts" "$OUT" "$ROOT/.build" "$CORE" "$ROOT/.build/$NAME.xcarchive" "$ROOT/.build/integrated-product-source"; do
    [ ! -L "$path" ] || { echo 'Linked build input/output path' >&2; exit 1; }
done
rm -rf "$ROOT/.build/integrated-product-source"
mkdir -p "$OUT"
LINKED_OUTPUT=$(find "$OUT" -type l -print -quit)
[ -z "$LINKED_OUTPUT" ] || { echo 'Linked artifact output' >&2; exit 1; }
# Keep diagnostic logs, but never label old products as a new attempt's output.
rm -f "$OUT/sdk-success.txt" "$OUT/package-review.json" "$OUT/built-framework.json" \
    "$OUT/SUCCESS.txt" "$OUT/Socks5-$NAME-unsigned.ipa" "$OUT/Socks5-dSYMs.zip" \
    "$OUT/Socks5-$NAME-source.zip" "$OUT/SHA256SUMS.txt" "$OUT/source.zip" \
    "$OUT/history.bundle" "$OUT/tested-commit.txt" "$OUT/features.json" "$OUT/build-info.txt" \
    "$OUT/native-inputs.json"
rm -rf "$OUT/compiled-headers"
# Only this attempt's prepared directory may be uploaded, even after failure.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf 'composition=%s\nartifact_path=artifacts/%s\n' "$NAME" "$NAME" >> "$GITHUB_OUTPUT"
fi
COMMIT=$(git rev-parse HEAD)
python3 -c 'import sys; sys.exit(0 if __debug__ else "Assertions must be enabled.")'
git diff --exit-code "$COMMIT" -- > "$OUT/input-worktree.log"
git diff --cached --exit-code "$COMMIT" -- > "$OUT/input-index.log"
python3 Build/check.py worktree "$COMMIT" > "$OUT/input-identity.log"
python3 Build/check.py baseline > "$OUT/baseline-audit.log"
python3 Tests/documentation_contract.py > "$OUT/documentation-contract.log" 2>&1
python3 Tests/baseline_audit.py > "$OUT/baseline-driver.log" 2>&1
python3 Tests/native_sources_contract.py > "$OUT/native-lock-contract.log" 2>&1
python3 Tests/tcp_smoke_contract.py > "$OUT/smoke-contract.log" 2>&1
printf '%s\n' "$COMMIT" > "$OUT/tested-commit.txt"
git archive --format=zip "$COMMIT" -o "$OUT/source.zip"
python3 Build/check.py archive "$OUT/source.zip" "$COMMIT" > "$OUT/archive-audit.log"
test "$(git rev-parse HEAD)" = "$COMMIT"
git bundle create "$OUT/history.bundle" HEAD
python3 Tests/Integration/review_handoff_boundaries.py > "$OUT/review-handoff-boundaries.log" 2>&1
python3 Build/integration_checks.py > "$OUT/integration-source-checks.log" 2>&1
python3 Build/owner_checks.py > "$OUT/owner-checks.log" 2>&1
python3 Tests/Integration/intent_boundaries.py > "$OUT/intent-boundaries.log" 2>&1
python3 Tests/Integration/input_boundaries.py > "$OUT/input-boundaries.log" 2>&1
python3 Tests/Integration/package_boundaries.py > "$OUT/package-boundaries.log" 2>&1
python3 Tests/Integration/package_metadata.py > "$OUT/package-metadata.log" 2>&1
python3 Build/native_sources.py checkout server "$CORE" > "$OUT/native-inputs.json"
python3 Build/check.py apply "$CORE" > "$OUT/source-audit.log"
CF=$(command -v clang-format-18 || command -v clang-format)
"$CF" --version | grep -E 'version 18\.'
python3 Build/check.py format "$CORE" "$CF" >> "$OUT/source-audit.log"
for SOURCE in Tests/udp_stream_boundaries.c Tests/SocketIO/*.c; do
    "$CF" --style="file:$CORE/.clang-format" "$SOURCE" | cmp - "$SOURCE"
done
python3 Build/check.py composition >> "$OUT/source-audit.log"
cp Build/features.json "$OUT/features.json"
{
    printf '%s\n' "$COMMIT"
    git -C "$CORE" rev-parse HEAD
    git -C "$CORE" submodule status --recursive
} > "$OUT/build-info.txt"
feature() { python3 -c 'import json,sys; sys.exit(sys.argv[1] not in json.load(open("Build/features.json"))["features"])' "$1"; }
# The shared dispatcher exercises the actual compiled I/O mode and the full
# retained UDP/statistics probes instead of inferring modes from CFLAGS labels.
python3 Build/native_checks.py "$CORE" "$OUT/native" > "$OUT/native-checks.log" 2>&1
make -C "$CORE" clean > "$OUT/native-clean.log" 2>&1
export HEV_NATIVE_CORE="$CORE"
if feature background; then
    python3 Tests/Background/run_checks.py > "$OUT/background.log" 2>&1
    python3 Tests/Background/check_async_session.py > "$OUT/background-async.log" 2>&1
    python3 Build/owner_checks.py --background-policy > "$OUT/background-policy.log" 2>&1
    if [ "$(uname -s)" = Darwin ]; then
        python3 Tests/Background/check_subscription.py > "$OUT/background-subscription.log" 2>&1
        python3 Tests/Background/check_live_scheduling.py > "$OUT/background-live-scheduling.log" 2>&1
        swift Tests/Background/check_silence.swift Socks5/BackgroundKeepAlive/Silence.wav > "$OUT/decoded-silence.log"
    fi
fi
if feature server; then
    python3 Tests/ServerControl/run_checks.py > "$OUT/server-control.log" 2>&1
fi
if feature settings; then
    python3 Tests/Settings/run_checks.py > "$OUT/settings.log" 2>&1
    python3 Tests/Settings/run_checks.py --baseline-import > "$OUT/original-import-negative.log" 2>&1
    python3 Tests/Settings/run_checks.py --previous-store > "$OUT/previous-store-negative.log" 2>&1
fi
if [ "$(uname -s)" = Darwin ]; then
    MODULE="$OUT/compiled-headers"
    mkdir -p "$MODULE"
    cp "$CORE/src/hev-main.h" "$CORE/src/hev-socks5-icmp.h" "$MODULE/"
    printf 'module HevSocks5Server { header "hev-main.h" export * }\n' > "$MODULE/module.modulemap"
    printf '%s\n' "$COMMIT" > "$MODULE/source-commit.txt"
    (cd "$MODULE" && shasum -a 256 hev-main.h hev-socks5-icmp.h module.modulemap > SHA256SUMS.txt)
fi
if [ "$(uname -s)" = Darwin ] && [ "${BUILD_IPA:-1}" = 1 ]; then
    (cd "$CORE" && ./build-apple.sh) > "$OUT/core-apple.log" 2>&1
    # Keep the committed baseline and all later source checks untouched.
    PRODUCT=$(mktemp -d "$ROOT/.build/$NAME-product-source.XXXXXX")
    trap 'rm -rf "$PRODUCT"' EXIT
    unzip -q "$OUT/source.zip" -d "$PRODUCT"
    rm -rf "$PRODUCT/HevSocks5Server.xcframework"
    cp -R "$CORE/HevSocks5Server.xcframework" "$PRODUCT/"
    if [ "$NAME" = integrated ]; then
        python3 Build/release_source.py record "$PRODUCT"
    fi
    xcodebuild archive -project "$PRODUCT/Socks5.xcodeproj" -scheme Socks5 -configuration Release \
        -sdk iphoneos -destination 'generic/platform=iOS' \
        -archivePath "$ROOT/.build/$NAME.xcarchive" \
        CODE_SIGN_IDENTITY='' CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO \
        SWIFT_TREAT_WARNINGS_AS_ERRORS=YES \
        MARKETING_VERSION=3.0.0 CURRENT_PROJECT_VERSION=1 \
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
    cp "$OUT/source.zip" "$OUT/Socks5-$NAME-source.zip"
    (cd "$OUT" && shasum -a 256 *.ipa > SHA256SUMS.txt)
    if [ "$NAME" != integrated ]; then
        rm -rf "$PRODUCT"
        trap - EXIT
    fi
fi
python3 Build/check.py reverse "$CORE" >> "$OUT/source-audit.log"
test "$(git rev-parse HEAD)" = "$COMMIT" || { echo 'Source HEAD changed during build' >&2; exit 1; }
git diff --exit-code "$COMMIT" -- > "$OUT/final-worktree.log"
git diff --cached --exit-code "$COMMIT" -- > "$OUT/final-index.log"
python3 Build/check.py worktree "$COMMIT" > "$OUT/final-identity.log"
if [ "$NAME" = integrated ] && [ -n "${PRODUCT:-}" ]; then
    mv "$PRODUCT" "$ROOT/.build/integrated-product-source"
    trap - EXIT
fi
printf 'PASS: %s build and applicable checks completed\n' "$NAME" | tee "$OUT/SUCCESS.txt"
