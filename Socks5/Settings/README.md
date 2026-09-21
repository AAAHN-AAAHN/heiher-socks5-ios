# Application settings

SettingsStore is the only persistence owner. It keeps one versioned JSON file at
Application Support/Socks5/settings.json. Every changed field, switch, server
Start/Stop request and selected tab is saved by atomic replacement. No timer,
statistics sample or location callback writes configuration. Values being edited
are saved as drafts; the server validates them before starting. Storage failures
are visible and never prevent an explicit Stop or Off from taking effect.

The JSON contains all eleven server fields, desired serverRunning, both background
switches, selectedTab and version. Actual connection counters, transient runtime
errors, live location diagnostics and UI dialogs are not settings. The two old
UserDefaults background flags migrate once when the JSON file does not yet exist.
The previous app did not persist server fields, so set those once after updating.

Settings imports/exports use the system Files dialogs. External reads use a
security scope and file coordination off MainActor, limited to 64 KB. Import
validates schema and configuration before changing the stored document or live
services. A running server is stopped and its blocking call allowed to finish
before applying changed options. Import may enable saved services and switch to
the saved tab. Only import configurations you trust.

The primary JSON uses iOS file protection until first unlock; an exported JSON
contains the password in plain text. No credentials or personal settings are
included in the repository. Deleting the app can delete its internal settings;
export JSON first to preserve them elsewhere.

ServerController serializes launch/stop/reconfiguration independently of the
visible tab. Start/Stop is desired state, not a claim about socket readiness.
An engine error is shown; it does not rewrite desired state or enter a busy retry
loop. On the next launch/foreground reconciliation an enabled server is tried
again. Closing the process cannot execute an auto-launch; restoration means the
next time iOS launches or the user opens the app.

Multiple UI scenes are disabled: the native Hev library is process-global, so
opening a second window must not create a second server controller.

Statistics and all five Hev patches are unchanged. The app icon reuses the
original server/globe/bidirectional-network artwork from this conversation.
