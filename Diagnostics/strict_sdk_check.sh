#!/bin/bash
# Control-CI supplement: actual SDK, exact owner composition, no substitutions.
set -euo pipefail
STRICT_PROFILE=$1
case "$STRICT_PROFILE" in
    settings) STRICT_NAME=settings-persistence ;;
    integrated) STRICT_NAME=integrated ;;
    *) exit 2 ;;
esac
STRICT_OUT="$PWD/artifacts/$STRICT_NAME/strict-sdk"
STRICT_HEADERS="$PWD/artifacts/$STRICT_NAME/compiled-headers"
mkdir -p "$STRICT_OUT"
rm -f "$STRICT_OUT/SUCCESS.txt"
test "$(uname -s)" = Darwin
test -s "artifacts/$STRICT_NAME/SUCCESS.txt"
test -s "artifacts/$STRICT_NAME/sdk-success.txt"
test "$(cat "$STRICT_HEADERS/source-commit.txt")" = "$(git rev-parse HEAD)"
git diff --exit-code HEAD -- > "$STRICT_OUT/input-worktree.log"
git diff --cached --exit-code HEAD -- > "$STRICT_OUT/input-index.log"
(cd "$STRICT_HEADERS" && shasum -a 256 -c SHA256SUMS.txt) > "$STRICT_OUT/headers-before.log"
if [ "$STRICT_PROFILE" = integrated ]; then
    python3 Tests/Integration/intent_boundaries.py --source-only > "$STRICT_OUT/source-contract.json"
fi
xcodebuild -version > "$STRICT_OUT/xcode.txt"
xcrun swiftc --version > "$STRICT_OUT/compiler.txt"
xcrun --sdk iphoneos --show-sdk-version > "$STRICT_OUT/sdk-version.txt"
xcrun --sdk iphoneos --show-sdk-build-version > "$STRICT_OUT/sdk-build.txt"
python3 - "$STRICT_OUT/sdk-version.txt" <<'PY'
from pathlib import Path
import sys
version = Path(sys.argv[1]).read_text().strip()
if not version.startswith('27.'):
    raise SystemExit('Expected the actual iOS 27 SDK, got ' + version)
PY
STRICT_SDK_PATH=$(xcrun --sdk iphoneos --show-sdk-path)
STRICT_SOURCES=(
    Socks5/AppRoot.swift
    Socks5/ContentView.swift
    Socks5/Server/ServerController.swift
    Socks5/Server/ServerSettings.swift
    Socks5/Settings/AppSettings.swift
    Socks5/Settings/SettingsStore.swift
    Socks5/Settings/SettingsView.swift
    Socks5/Socks5App.swift
)
if [ "$STRICT_PROFILE" = integrated ]; then
    STRICT_SOURCES+=(
        Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift
        Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift
        Socks5/BackgroundKeepAlive/LoopAudioService.swift
        Socks5/BackgroundKeepAlive/PlaybackProgressMonitor.swift
        Socks5/BackgroundKeepAlive/RecoveryExecutionLease.swift
        Socks5/Statistics/TrafficStatistics.swift
        Socks5/Statistics/TrafficStatisticsView.swift
    )
fi
python3 - "$STRICT_OUT" "$STRICT_SDK_PATH" "$STRICT_HEADERS" "$STRICT_PROFILE" "${STRICT_SOURCES[@]}" <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import sys
out, sdk, headers = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
profile, paths = sys.argv[4], sys.argv[5:]
actual = sorted(p.as_posix() for p in Path('Socks5').rglob('*.swift'))
expected_count = 15 if profile == 'integrated' else 8
if len(paths) != expected_count or len(set(paths)) != expected_count or sorted(paths) != actual:
    raise SystemExit('Strict SDK input differs from the exact application source inventory')
value = {
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], text=True).strip(),
    'profile': profile,
    'sdk_path': sdk,
    'sdk_version': (out / 'sdk-version.txt').read_text().strip(),
    'sdk_build': (out / 'sdk-build.txt').read_text().strip(),
    'compiler': (out / 'compiler.txt').read_text().strip(),
    'target': 'arm64-apple-ios17.2',
    'swift_version': '5',
    'strict_concurrency': 'complete',
    'warnings_as_errors': True,
    'sources': {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},
    'headers': {p: hashlib.sha256((headers / p).read_bytes()).hexdigest()
                for p in ['hev-main.h', 'module.modulemap']},
    'scope': 'Actual iOS SDK typecheck; no source substitutions and no device execution',
}
(out / 'inputs.json').write_text(json.dumps(value, indent=2) + '\n')
PY
xcrun swiftc -typecheck -swift-version 5 -strict-concurrency=complete \
    -warnings-as-errors -sdk "$STRICT_SDK_PATH" \
    -target arm64-apple-ios17.2 -I "$STRICT_HEADERS" \
    "${STRICT_SOURCES[@]}" > "$STRICT_OUT/typecheck.log" 2>&1
(cd "$STRICT_HEADERS" && shasum -a 256 -c SHA256SUMS.txt) > "$STRICT_OUT/headers-after.log"
git diff --exit-code HEAD -- > "$STRICT_OUT/final-worktree.log"
git diff --cached --exit-code HEAD -- > "$STRICT_OUT/final-index.log"
printf 'PASS: exact %s application inputs; actual iOS 27 SDK, arm64 iOS 17.2, complete strict concurrency, warnings as errors; not device execution.\n' "${#STRICT_SOURCES[@]}" > "$STRICT_OUT/SUCCESS.txt"
