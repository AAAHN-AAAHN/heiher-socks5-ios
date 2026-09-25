#!/bin/bash
# Validation only: never call the archive/IPA production pipeline.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT="$PWD/artifacts/audio-checks"
mkdir -p "$OUT"
rm -f "$OUT/SUCCESS.txt"
xcodebuild -version | tee "$OUT/toolchain.txt"
xcrun --sdk iphoneos --show-sdk-version | tee -a "$OUT/toolchain.txt" | grep -E '^27\.'
git rev-parse HEAD > "$OUT/tested-commit.txt"
git archive --format=zip HEAD -o "$OUT/source.zip"
BASE=$(python3 -c 'import json; print(json.load(open("Build/features.json"))["base_commit"])')
git diff --check "$BASE" HEAD > "$OUT/whitespace.log"
python3 Build/check.py baseline > "$OUT/baseline.log"
python3 Build/check.py composition > "$OUT/composition.log"
python3 Tests/Background/check_scope.py > "$OUT/background-scope.json"
python3 Tests/Background/audit_driver_check.py > "$OUT/audit-driver.log"
python3 Tests/Background/run_checks.py > "$OUT/controller-tests.log" 2>&1
python3 Tests/Background/check_subscription.py > "$OUT/subscription-tests.log" 2>&1
python3 Tests/Background/check_live_scheduling.py > "$OUT/live-scheduling.log" 2>&1
swift Tests/Background/check_silence.swift Socks5/BackgroundKeepAlive/Silence.wav > "$OUT/apple-wav.log" 2>&1
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun swiftc -typecheck -swift-version 5 -warnings-as-errors \
  -sdk "$SDK" -target arm64-apple-ios17.2 \
  -I HevSocks5Server.xcframework/ios-arm64/Headers \
  Socks5/Socks5App.swift Socks5/AppRoot.swift Socks5/ContentView.swift \
  Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift \
  Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift > "$OUT/ios-sdk-typecheck.log" 2>&1
python3 - <<'PY' > "$OUT/source-sha256.json"
import hashlib, json, pathlib, subprocess
paths = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
print(json.dumps({p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in paths}, indent=2))
PY
printf 'PASS: iOS 27 SDK typecheck, controller/Combine tests and WAV checks. No app archive or IPA created. No physical-device interruption test.\n' > "$OUT/SUCCESS.txt"
