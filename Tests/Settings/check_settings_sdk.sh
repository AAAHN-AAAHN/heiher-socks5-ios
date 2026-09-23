#!/bin/bash
# Checks only: this script must never archive an app or package an IPA.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
OUT="$ROOT/artifacts/settings-checks"
CORE="$ROOT/.build/settings-check-core"
mkdir -p "$OUT"
xcodebuild -version | tee "$OUT/toolchain.txt"
xcrun --sdk iphoneos --show-sdk-version | tee -a "$OUT/toolchain.txt" | grep -E '^27\.'
xcrun swiftc --version >> "$OUT/toolchain.txt"
sw_vers >> "$OUT/toolchain.txt"
git rev-parse HEAD > "$OUT/tested-commit.txt"
git rev-parse 'HEAD^{tree}' > "$OUT/tested-tree.txt"
git archive --format=zip HEAD -o "$OUT/tested-source.zip"
git archive --format=zip 9c2e76afcde7a20ff1bbdcf2a1f7e9092e1a98fd -o "$OUT/input-source.zip"
git archive --format=zip d2534cd6bce7389fdf8f362bd8f681c0bd583eb1 -o "$OUT/main-source.zip"
git diff --check d2534cd6bce7389fdf8f362bd8f681c0bd583eb1 HEAD > "$OUT/whitespace.log"
python3 Build/check.py baseline > "$OUT/baseline.log"
python3 Build/check.py composition > "$OUT/composition.log"
python3 Tests/Settings/check_scope.py > "$OUT/scope.json"
python3 Tests/Settings/run_checks.py > "$OUT/settings-tests.log" 2>&1
python3 Tests/Settings/run_checks.py --baseline-import > "$OUT/original-import-negative.log" 2>&1
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
xcrun swiftc -typecheck -swift-version 5 -warnings-as-errors \
    -sdk "$SDK" -target arm64-apple-ios17.2 \
    -I HevSocks5Server.xcframework/ios-arm64/Headers \
    Socks5/Socks5App.swift Socks5/AppRoot.swift Socks5/ContentView.swift \
    Socks5/Server/ServerController.swift Socks5/Settings/AppSettings.swift \
    Socks5/Settings/SettingsStore.swift Socks5/Settings/SettingsView.swift \
    > "$OUT/ios-sdk-typecheck.log" 2>&1
# Reuse the existing pinned native path without changing the shared build pipeline.
SERVER_REF=$(python3 -c 'import json; print(json.load(open("Build/features.json"))["sources"]["."])')
git clone --no-checkout https://github.com/heiher/hev-socks5-server.git "$CORE" > "$OUT/native-clone.log" 2>&1
git -C "$CORE" checkout --detach "$SERVER_REF" >> "$OUT/native-clone.log" 2>&1
git -C "$CORE" submodule update --init --recursive >> "$OUT/native-clone.log" 2>&1
python3 Build/check.py apply "$CORE" > "$OUT/native-source.log"
CF="$(brew --prefix llvm@18)/bin/clang-format"
"$CF" --version | tee "$OUT/formatter.txt" | grep -E 'version 18\.'
python3 Build/check.py format "$CORE" "$CF" >> "$OUT/native-source.log"
make -C "$CORE" -j3 CC='xcrun --sdk macosx clang' static exec > "$OUT/native-build.log" 2>&1
LIBS=("$CORE/bin/libhev-socks5-server.a" "$CORE/third-part/yaml/bin/libyaml.a" "$CORE/third-part/hev-task-system/bin/libhev-task-system.a")
xcrun --sdk macosx clang -std=gnu11 -O2 -Wall -Werror -pthread -I"$CORE/src" \
    Tests/server_lifecycle_host.c "${LIBS[@]}" -o "$CORE/lifecycle-host"
python3 Tests/server_lifecycle_regression.py "$CORE/lifecycle-host" > "$OUT/native-lifecycle.log" 2>&1
python3 Tests/tcp_smoke.py "$CORE/bin/hev-socks5-server" > "$OUT/native-tcp.log" 2>&1
xcrun swiftc -swift-version 5 -warnings-as-errors Socks5/Settings/AppSettings.swift Tests/Settings/EmitConfiguration.swift -o "$CORE/emit-config"
"$CORE/emit-config" "$OUT/yaml"
xcrun --sdk macosx clang -std=gnu11 -O2 -Wall -Werror -pthread -I"$CORE/src" \
    Tests/Settings/configuration_probe.c "${LIBS[@]}" -o "$CORE/config-probe"
"$CORE/config-probe" "$OUT/yaml/defaults.yml" "$OUT/yaml/quoted.yml" > "$OUT/native-configuration.log" 2>&1
# Controlled proof of the old Swift/native length mismatch, without changing Hev.
git show 9c2e76afcde7a20ff1bbdcf2a1f7e9092e1a98fd:Socks5/Settings/AppSettings.swift > "$CORE/OldAppSettings.swift"
cat > "$CORE/OldLength.swift" <<'SWIFT'
import Foundation
@main struct OldLength {
    static func main() throws {
        var server = ServerSettings()
        server.listenAddress = String(repeating: "x", count: 256)
        try server.configuration().write(toFile: CommandLine.arguments[1], atomically: true, encoding: .utf8)
        print("Original Swift validator accepted 256 UTF-8 bytes for listenAddress.")
    }
}
SWIFT
xcrun swiftc -swift-version 5 -warnings-as-errors "$CORE/OldAppSettings.swift" "$CORE/OldLength.swift" -o "$CORE/old-length"
"$CORE/old-length" "$OUT/yaml/original-overlong.yml" > "$OUT/original-length-negative.log"
cat > "$CORE/check-length.c" <<'C'
#include "hev-config.h"
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc != 2 || hev_config_init_from_file(argv[1]) != 0) return 1;
    size_t length = strlen(hev_config_get_listen_address());
    printf("Actual pinned native parser retained %zu bytes from the 256-byte field.\n", length);
    return length == 255 ? 0 : 1;
}
C
xcrun --sdk macosx clang -std=gnu11 -O2 -Wall -Werror -pthread -I"$CORE/src" \
    "$CORE/check-length.c" "${LIBS[@]}" -o "$CORE/check-length"
"$CORE/check-length" "$OUT/yaml/original-overlong.yml" >> "$OUT/original-length-negative.log"
python3 Build/check.py reverse "$CORE" > "$OUT/native-reverse.log"
python3 - <<'PY' > "$OUT/source-sha256.json"
import hashlib, json, pathlib, subprocess
paths = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
print(json.dumps({p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in paths}, indent=2))
PY
printf 'PASS: source, actual Foundation and controlled-provider tests, iOS 27 typecheck, native lifecycle/TCP/YAML. No app archive, IPA, device or installer test.\n' > "$OUT/SUCCESS.txt"
