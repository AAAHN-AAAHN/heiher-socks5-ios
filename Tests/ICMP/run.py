#!/usr/bin/env python3
"""Build and run native ICMP tests against the actual prepared server source."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import sys

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("--faults-only", action="store_true")
args = parser.parse_args()
source = args.source.resolve()
test = Path(__file__).resolve().parent / "native.c"
with tempfile.TemporaryDirectory(prefix="icmp-native-") as temp:
    common = [
        "cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
        f"-I{source / 'src'}", f"-I{source / 'src/core/include'}",
        f"-I{source / 'third-part/hev-task-system/include'}", str(test),
        str(source / "bin/libhev-socks5-server.a"),
        str(source / "third-part/yaml/bin/libyaml.a"),
        str(source / "third-part/hev-task-system/bin/libhev-task-system.a"),
    ]
    modes = ["faults"] if args.faults_only else (["faults", "real"] if sys.platform == "linux" else ["real"])
    for mode in modes:
        binary = Path(temp) / mode
        command = common.copy()
        if mode == "faults":
            command += ["-DICMP_TEST_IO", str(test.with_name("faults.c")), str(test.with_name("engine.c"))]
            command += [f"-Wl,--wrap={name}" for name in (
                "socket", "close", "bind", "setsockopt", "getsockname", "sendto", "recvmsg",
                "hev_icmp_engine_send")]
        subprocess.run(command + ["-o", str(binary)], check=True)
        print(f"Running {mode} ICMP tests", flush=True)
        subprocess.run([str(binary)], check=True, timeout=30)
