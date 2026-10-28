#!/usr/bin/env python3
"""Observe the host's mapped-wildcard TCP semantics; no product changes."""
import argparse
import json
import os
import platform
import socket
from pathlib import Path


def observe(host):
    result = {"requested": {"family": "AF_INET6", "host": host, "port": 0,
                             "ipv6_only": 0}, "connects": []}
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
        listener.settimeout(1)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            listener.bind((host, 0))
            listener.listen(100)
            result["actual"] = {"sockname": listener.getsockname(),
                                "ipv6_only": listener.getsockopt(socket.IPPROTO_IPV6,
                                                                  socket.IPV6_V6ONLY)}
            for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
                attempt = {"family": int(family), "host": address,
                           "port": listener.getsockname()[1]}
                with socket.socket(family, socket.SOCK_STREAM) as client:
                    client.settimeout(1)
                    try:
                        client.connect((address, attempt["port"]))
                        attempt.update(connected=True, sockname=client.getsockname(),
                                       peer=client.getpeername())
                        accepted, peer = listener.accept()
                        with accepted:
                            attempt["accepted_peer"] = peer
                    except OSError as error:
                        attempt.update(error=repr(error), errno=error.errno)
                result["connects"].append(attempt)
        except OSError as error:
            result.update(error=repr(error), errno=error.errno)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    result = {"platform": platform.platform(), "system": platform.system(),
              "euid": os.geteuid(), "cases": [observe(host) for host in
                  ("::ffff:0.0.0.0", "::", "::ffff:127.0.0.1")]}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
