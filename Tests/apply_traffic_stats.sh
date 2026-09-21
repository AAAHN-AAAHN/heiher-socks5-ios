#!/bin/sh
# Run from the workspace containing app/ and core/. Never updates upstream refs.
set -eu
PATCH_DIR="$(pwd)/app/Patches"
test "$(git -C core rev-parse HEAD)" = b3585289622561caf4b8789b436cc8820ecd6be0
test "$(git -C core/src/core rev-parse HEAD)" = 162dd996299fc2d2bff2dd63728f8a2cd71ed31a
test "$(git -C core/third-part/hev-task-system rev-parse HEAD)" = 328f35d903221b51811b3d02b277d665dfbdc75f
apply() {
    git -C "$1" apply --check --whitespace=error-all "$PATCH_DIR/$2"
    git -C "$1" apply --whitespace=error-all "$PATCH_DIR/$2"
}
apply core hev-udp-port-zero.patch
apply core/src/core hev-udp-sockaddr.patch
apply core/third-part/hev-task-system hev-stats-task-io.patch
apply core/src/core hev-stats-core.patch
apply core hev-stats-server.patch
