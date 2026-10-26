#!/bin/bash
# Build the separately locked upstream tunnel; no application integration.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
OUT="$ROOT/artifacts/tunnel-baseline"
TUNNEL="$ROOT/.build/tunnel"
for path in "$ROOT/artifacts" "$OUT" "$ROOT/.build" "$TUNNEL"; do
    [ ! -L "$path" ] || { echo 'Linked build input/output path' >&2; exit 1; }
done
mkdir -p "$OUT"
[ -z "$(find "$OUT" -type l -print -quit)" ] || { echo 'Linked artifact output' >&2; exit 1; }
rm -f "$OUT/SUCCESS.txt" "$OUT/tested-commit.txt" "$OUT/native-inputs.json" \
    "$OUT/hev-socks5-tunnel" "$OUT/HevSocks5Tunnel.xcframework.zip" "$OUT/SHA256SUMS.txt" \
    "$OUT/source.zip" "$OUT/history.bundle" "$OUT/build-info.txt"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf 'artifact_path=artifacts/tunnel-baseline\n' >> "$GITHUB_OUTPUT"
fi
COMMIT=$(git rev-parse HEAD)
python3 Build/check.py worktree "$COMMIT" > "$OUT/input-identity.log"
python3 Build/check.py baseline > "$OUT/baseline-audit.log"
python3 Tests/native_sources_contract.py > "$OUT/native-lock-contract.log" 2>&1
printf '%s\n' "$COMMIT" > "$OUT/tested-commit.txt"
git archive --format=zip "$COMMIT" -o "$OUT/source.zip"
python3 Build/check.py archive "$OUT/source.zip" "$COMMIT" > "$OUT/archive-audit.log"
git bundle create "$OUT/history.bundle" HEAD
python3 Build/native_sources.py checkout tunnel "$TUNNEL" > "$OUT/native-inputs.json"
python3 Build/check.py native tunnel "$TUNNEL" > "$OUT/source-audit.log"
{
    printf '%s\n' "$COMMIT"
    uname -s
    cc --version
    if [ "$(uname -s)" = Darwin ]; then
        xcodebuild -version
        xcrun --sdk iphoneos --show-sdk-version
    fi
} > "$OUT/build-info.txt"
make -C "$TUNNEL" clean > "$OUT/native-build.log" 2>&1
make -C "$TUNNEL" -j3 exec >> "$OUT/native-build.log" 2>&1
cp "$TUNNEL/bin/hev-socks5-tunnel" "$OUT/"
make -C "$TUNNEL" clean >> "$OUT/native-build.log" 2>&1
if [ "$(uname -s)" = Darwin ]; then
    (cd "$TUNNEL" && ./build-apple.sh) > "$OUT/tunnel-apple.log" 2>&1
    ditto -c -k --keepParent "$TUNNEL/HevSocks5Tunnel.xcframework" "$OUT/HevSocks5Tunnel.xcframework.zip"
fi
python3 Build/check.py native tunnel "$TUNNEL" >> "$OUT/source-audit.log"
python3 Build/check.py worktree "$COMMIT" > "$OUT/final-identity.log"
(cd "$OUT" && shasum -a 256 hev-socks5-tunnel *.zip > SHA256SUMS.txt)
printf 'PASS: locked upstream tunnel compilation and source checks; no TUN/device execution\n' > "$OUT/SUCCESS.txt"
