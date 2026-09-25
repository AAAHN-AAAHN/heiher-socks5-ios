#!/bin/bash
# Resource audit only; the production archive/IPA pipeline is never called.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT="$PWD/artifacts/icon-checks"
mkdir -p "$OUT"
rm -f "$OUT/SUCCESS.txt"
git rev-parse HEAD > "$OUT/tested-commit.txt"
git rev-parse 'HEAD^{tree}' > "$OUT/tested-tree.txt"
git archive --format=zip HEAD -o "$OUT/tested-source.zip"
git archive --format=zip f88e8c8946b095c4d5551d413dee3b4a60943714 -o "$OUT/input-source.zip"
git archive --format=zip d2534cd6bce7389fdf8f362bd8f681c0bd583eb1 -o "$OUT/main-source.zip"
git diff --check f88e8c8946b095c4d5551d413dee3b4a60943714 HEAD > "$OUT/whitespace.log"
python3 Build/check.py baseline > "$OUT/baseline.log"
python3 Build/check.py composition > "$OUT/composition.log"
python3 Tests/AppIcon/audit_driver_check.py > "$OUT/audit-driver.log"
python3 Tests/AppIcon/check_icon.py > "$OUT/source-review.json"
python3 Tests/AppIcon/test_icon.py > "$OUT/mutation-tests.log" 2>&1
python3 Tests/AppIcon/check_compiled.py > "$OUT/compiled-review.log" 2>&1
python3 - <<'PY' > "$OUT/source-sha256.json"
import hashlib, json, pathlib, subprocess
names = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
print(json.dumps({n: hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest() for n in names}, indent=2))
PY
printf 'PASS: app-icon resource audit, Xcode 27 asset compilation, actual Simulator app registration/launch. No iPhone archive or IPA.\n' > "$OUT/SUCCESS.txt"
