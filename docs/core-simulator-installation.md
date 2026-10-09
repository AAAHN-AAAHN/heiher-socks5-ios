# CoreSimulator installation observations

## Purpose and scope

This auxiliary probe investigates a Simulator installation timeout using the exact app preserved in a failed integrated-release artifact. It distinguishes the installer's process state from waiting for captured output to close.

## Functional behavior

The first case installs the app with piped output on a fresh iPhone 16 Simulator running iOS 27. Only if that installation reaches its 120-second timeout does a second fresh device run the same installation with output directed to regular files. Both cases retain the original deadline.

## Implementation and ownership

The dedicated workflow on `work/simulator-diagnostics` downloads a fixed artifact ID and run, then invokes `Diagnostics/CoreSimulator/install_probe.py`. The probe checks the archive digest and source identity, preserves the app's bytes and modes, and records observations under `artifacts/simulator-install-probe`. The historical boot observer remains separate.

## Design rationale and resource cost

At most two disposable Simulators run sequentially. Process sampling and service queries have bounded deadlines. The comparison changes command-output handling while retaining the same captured app, avoiding a rebuild or signing change as an additional variable.

## Verification contract

Evidence records the host macOS version, source and archive identity, installation PID and return state, installed-container observations, service diagnostics, app invariance and cleanup. `summary.json` separates diagnostic completion from product verification: a completed observation can include installation timeouts and always records `product_gate_pass: false`.

## Operation and limitations

Changes to the probe or its workflow trigger this diagnostic; manual dispatch uses the same fixed input. Input, setup, app-invariance or cleanup failures leave the diagnostic incomplete. Missing observations and command timeouts remain visible. Different devices, service readiness and execution times prevent this small comparison from establishing a cause by itself. It does not certify the Release CI gates or physical SideStore/LiveContainer operation.

## Related documents

See the [workflow](../.github/workflows/simulator-install-probe.yml), [probe](../Diagnostics/CoreSimulator/install_probe.py), [documentation contract](documentation.md) and [governing principles](top-level-principles.md).
