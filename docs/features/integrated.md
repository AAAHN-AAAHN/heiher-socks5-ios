# Integrated SOCKS5 for iOS — current six-owner composition

## Completed integration — 2026-09-30

This revision combines the six completed owners below while retaining previous
release `8577bb1f9b24593de011076aa3a6cafcebd50240` and main
`75335d201cb1e541bb153e9899badbc11ccf1973` as actual ancestors. The preceding
release specification, build9 results and failures remain at that immutable release
README and in the retained history/review files. They do not certify this revision.
Fresh combined native, SDK, archive/IPA and actual Simulator checks passed in
run36693157594 at the exact source recorded below. The new unsigned product is
version1.1.0 build10;
existing releases, feature refs and build9 products are not replaced or relabeled.
README and `docs/features/integrated.md` are identical.

The primary target is a physical iOS27 device, installed independently with SideStore
or executed as a LiveContainer guest. These are distinct signing, container, permission
and shared-process environments. Configured minimum remains iOS17.2, not certification
of execution on every later OS. All four rules in `docs/top-level-principles.md` apply.
Native/model tests, SDK compilation, IPA generation, Simulator, physical installation,
guest execution and real background survival remain separate evidence layers.

## Exact feature owners and responsibility

| Branch | Integrated owner | Responsibility |
| --- | --- | --- |
| feature/udp-compat | 84d47e88de993a8f4b4cc084f9240f29565c78ed | Peer/address compatibility, full datagrams, adaptive buffers and strict framing. |
| feature/traffic-statistics | dc6feaadb9061eb320bbce5d66c56a7c814c93d3 | Successful destination I/O totals, control-peer IP rows and visible-tab sampling. |
| feature/server-control | 368aa4cf89436651414a8885a2a171f5cff9abd5 | Options, validation, YAML, serialized native Start/Stop and cancellation. |
| feature/settings-persistence | a52f2599c4bdb895bc4e8d04ba84f03f45b2a5c7 | JSON storage, restoration, migration and import/export ordering. |
| feature/background | 5480cbf9859b8d58c20f9001b0c9fda8e23fd6df | Continuous coarse location and serialized silent-audio recovery/ownership. |
| feature/app-icon | a17e33b283025377601aef1bcfd32dfa6b79a426 | Approved original artwork, catalog and compiled-icon validation. |

`docs/feature-membership.json` maps177 source/test/document paths to these exact
owners or shared main, including original paths, SHA-256 and Git mode checks.
The six READMEs are copied verbatim into `docs/branches/`; current feature specifications
and all dated histories/reviews are retained. Release contains every listed tip as an
actual ancestor; listing a SHA in a document alone is not sufficient.

Statistics itself retains its actual UDP dependency `6f9848e4`, which precedes the
new test/document-only UDP review. Its four native patches and manifest are identical
to the latest UDP owner. Release checks that dependency's real ancestry and exact
runtime equivalence, and independently includes the latest UDP tip and tests. It does
not falsify the statistics dependency or modify that feature to manufacture ancestry.
Settings inherits the exact listed server-control owner. Main and all four native
pins agree across all owners; submodule heads are not independently floated.

The existing integrated AppRoot, app entry, project, plist, defaults and schema are
preserved. One SettingsStore, ServerController and BackgroundKeepAlive own the four
tabs: Statistics, Server, Background, Settings. JSON owns persistent intent; there is
no parallel AppStorage writer in release. Server does not depend on storage, Background
does not call Hev or read JSON, and tab changes do not recreate the service owners.

## Native composition and preserved feature contracts

Apply these eight exact owner patches once, in order, at their manifest roots:

1. `hev-udp-port-zero.patch`
2. `hev-udp-sockaddr.patch`
3. `hev-udp-peer-filter.patch`
4. `hev-udp-dynamic-buffer.patch`
5. `hev-stats-task-io.patch`
6. `hev-stats-core.patch`
7. `hev-stats-server.patch`
8. `hev-server-startup-stop.patch`

The unpatched source pins are serverb3585289622561caf4b8789b436cc8820ecd6be0,
core162dd996299fc2d2bff2dd63728f8a2cd71ed31a,
task328f35d903221b51811b3d02b277d665dfbdc75f and
yaml162227cd7d2b6108bc8bc133273e11413222ddf4. App pin180012e8 and the committed
baseline XCFramework/inventory are unchanged. Packaging must link the freshly built
eight-patch framework in its disposable source copy, never the unpatched baseline.

UDP keeps base1500, 500-byte rounding, 300-second demand retention and independent
60-second safe cleanup. Each demand refreshes only its own bucket; small packets do
not indefinitely retain a large block. Allocation has no arbitrary65536 ceiling;
wire-length, arithmetic, allocation and socket/path limits still apply. Do not split
one datagram into independent messages. RSV/FRAG, peer, queue and partial-frame rules
remain the owner implementation. Cleanup cannot move buffers referenced by active I/O.

Statistics counts positive destination reads and socket-accepted destination writes
once, including successful prefixes before later failures. Peeks, headers, unused
capacity and client-side calls are excluded. In survives failed client delivery.
Rows use the normalized TCP control-peer IP or Unattributed, not a device identity.
Total/rows use independent atomics: transient live differences, finite UInt64 wrapping
and display rounding are explicit limits. Stop/Start does not reset process totals.
Visible active sampling remains approximately1s; no hidden-tab sampling loop is added.

Background inherits the exact infinite50ms silent WAV and one0.5s health/retry timer,
serialized async session/preparation ownership, bounded notification recovery and
Off priority. It never releases an unrequested shared session after failed setup.
The existing ownership flag is not an OS lease against an independent host. Location
retains one coarse manager and no coordinate history or polling timer. On is intent,
not permission, guaranteed playback, OS priority or a relaunch entitlement.

Settings/server models, import atomicity, revision ordering, failure-preserving live
Stop/Off, no-op write avoidance, validation and explicit retry behavior remain exact.
Running describes an owned native invocation, not socket readiness. Actual socket
responses are checked separately. Exports contain plaintext credentials.

## Minimal integration and resource effects

Owner runtime files and patches are copied without local rewrites. One release-only
network-fixture correction accepts ENOTCONN/ECONNRESET from shutdown after the server
has already rejected a malformed frame; it still requires no destination payload and
actual EOF/reset, with unchanged deadlines. Ten explicit delayed half-close probes
reproduce ENOTCONN plus correct rejection. Membership hash-locks this exception and
checks its exact small transformation against the untouched UDP owner. No successful
payload, timeout or arbitrary socket failure is excused. The release-only
root and platform configuration remain byte-identical to build9. Required integration
changes are source membership, dependency checks, build identification, native/model
orchestration and UI-test composition. Existing seven-patch/one-second assertions are
updated to the approved eight-patch/0.5second contracts rather than changing owners
back to old behavior. No new production state, allocation policy, payload copy,
thread, timer, lock, logging, permission, entitlement or host workaround is introduced.

Inheriting the newer owners does inherit their documented costs: next-datagram sizing
calls and Linux batching tradeoffs, expanded buffer/history storage, process-lived
IP entries, atomic updates and UI snapshot/sort work,0.5s audio deadlines and location
service activity. Healthy player/manager reuse and on-demand buffers are retained.
Freeing memory need not reduce RSS immediately. This integration does not establish
a global minimum CPU/RAM, zero operating-system cost or measured physical battery gains.

## Combined validation, not a collection of old badges

Use a clean full-history checkout. Source ZIPs alone do not contain the historical
objects needed for exact-negative controls and owner ancestry.

```sh
bash Build/build.sh
# Actual Apple host, after native output at the same HEAD:
bash Build/check_swift_sdk.sh
python3 Build/verify_release.py
python3 Build/simulator_review.py
python3 Build/ui_review.py
python3 Build/record_evidence.py
```

Linux exercises buffered and splice native paths; Apple exercises buffered, SDK,
archive/IPA, original/remapped seeded Simulator installs and actual UI. The latest
statistics native driver runs against the combined eight-patch engine, including
TCP15,552-case accounting, UDP payload/failure boundaries, registry/concurrency and
actual timed reclamation with counters. The latest145,459-case UDP stream fixture
also runs against that combined core. Existing network/peer/socket memory tests,
server/persistence-to-native tests and cancellation checks remain, with the latest
server final-native probe. Current sampler/client models are included.

The unchanged Background-only policy driver runs in its exact pinned-owner worktree
because its app-wide source predicate is specific to that standalone feature. It
includes exact old controls,135 ownership assertions,12,096 reentry histories,69,984
ordered triples and65,536-event liveness histories. Exact release mappings bind that
controller to the combined app, which also runs direct controller/async, actual Apple
Combine/RunLoop, WAV and combined UI tests. Platform doubles remain a separate scope. The latest settings/store/coordination suites and all earlier negative
controls remain enabled. Counts describe their fixture scopes, not physical trials.

Owner-specific source/driver checks run in genuine detached worktrees at their own
SHAs. No standalone gate is tricked into accepting the integrated feature set.
The integrated source mapping, native whole-worktree/index checks, formatter18,
original37 input and12 package boundary controls remain. All assertions, runtime
warning gates, existing per-command deadlines and cleanup failures are retained.

The actual UI target concatenates the original integrated test (class renamed only
to avoid a symbol collision), the unchanged latest Background audio test, and the
unchanged latest statistics full-payload/Total/IP test. It requires three successful
cases without skipped tests. Only temporary test code changes; production target
membership is unchanged. Integrated Start/Stop, durable intent, independent audio,
all tabs and exact large-payload/IP volumes are required on the actual combined app.
The total xcodebuild test deadline remains900s; original case predicates remain.

Generated framework inventory and every copied source path are bound to the tested
commit/tree. The device app must be ARM64/iPhoneOS27/minimum17.2 with the correct
version/build, UUID-matched dSYM, native stats/client/prepare definitions, approved
icon/CAR/fallbacks, WAV, permissions and entire IPA file inventory. Source-only,
native, SDK, archive, Simulator and workflow success are not interchangeable.
No signed device installation is implied by an unsigned archive or a successful CI.

## Publication and unperformed deployment layers

Version1.1.0 build10 and `hev.Socks5` preserve identity/schema continuity; the CI IPA
is an unsigned input for the user's signing/import process. Subsequent signing changes
its hash. Existing build9/earlier IPAs are not overwritten. A completed document-only
closure must name its tested parent; it is not a new runtime execution.

Use UDP Listen Port0 for multiple unknown-client associations. The accepted fixed-port
unknown-peer independent-close limit and valid same-IP first-sender race remain owner
restrictions, not new fixes claimed here. Platform scheduling and blocked/suspended
I/O can defer cleanup. Process termination cannot be overcome by a timer. A failed
save can leave older durable intent even though live Stop/Off is applied; a blocked
provider cannot be forcibly canceled by ignoring its late result.

Physical SideStore signing/install/run, LiveContainer guest/shared-session behavior,
actual location permission/file protection/call/Siri/Bluetooth events, external file
provider transfer, lock/suspension/long background survival, VPN/hotspot and device
CPU/RAM/energy/maximum throughput remain unperformed without corresponding records.
Seeded/remapped Simulator is not either physical deployment. Finite tests cannot
certify every possible OS/input/resource/scheduler history as defect-free.

## Completed exact-source integration — 2026-09-30

Run `36693157594`, attempt1, completed successfully on Linux and Xcode27 at
`18608e4870ebbca0fedff9cc6ee5830673c0b3f2`, tree
`85c4f8f035a096e0908f941a5732bda68bae86c8`, with239 tracked files.
Terminal workflow metadata was updated at2026-09-30T09:28:32Z. Both final jobs pass;
Apple completed native/models, the actual twelve-file SDK check, ARM64 archive/IPA,
ten seeded Simulator cases and all three actual UI tests before publication.
Linux's Apple-only skipped steps are not counted as execution. The two earlier
failed integration runs below remain failures of their own sources, not retries of
this successful final-source run. Individual feature badges are not substituted.

The actual merge `32675a598053a21547ace23780b572cb238c0dd4` has seven real parents:
the previous release and all six completed owner tips in the table above. Genuine
Git history verifies those parents, main ancestry,177 exact mappings and both
feature dependency relationships. The preliminary local240-file/178-map candidate
is superseded by this posted239-file/177-map composition, which records the narrow
release-only rejected-frame test adaptation explicitly. No feature or main ref changed.

### Executed combined behavior

| Layer | Inspected result at the final source |
| --- | --- |
| Native composition | All eight exact patches apply once, format with upstream clang-format18 rules and reverse to the exact pinned native sources. Initial/final tracked worktree and index remain clean. |
| TCP accounting | 15,552 input/error/cancellation/attribution cases times three callback modes pass in sanitizer and O3/strict-aliasing configurations for Linux buffered/splice and Apple buffered. Actual destination-I/O returns, Total/IP/Unattributed and unchanged NULL/legacy traces are checked. |
| UDP and statistics | Per native mode:111 complete-payload network cases,24 controlled accounting boundaries,18 mixed/concurrent/restarted associations with126 complete echoes,426 large/mixed network records, peer/header/canary and preserved required UDP profiles pass. These include whole payloads above1500 and successful I/O retained across later rejection/failure. |
| Stream framing | The latest145,459 actual-C boundary cases pass in sanitizer and optimized modes against the combined core. Scripted wrapper outcomes are codec tests, not145,459 physical transmissions. |
| Registry and sampling | Original concurrent writer/registration/snapshot and expanded-registry contracts pass, including Apple TSan within its fixture scope. Exact sampler debug/optimized runs each pass98,516 checks and reject the old per-row-publication control. |
| Server and durable settings | Each native mode passes the18 final server records at workers1/4/64,12 active-client Stop/reconfigure cases,16 real file/store/controller/Hev records and retained authentication/cancellation/restart/late-completion controls. Model suites retain1,250 schedules/25,544 assertions,512 configuration parity cases and889 settings assertions. |
| Background policy | At the exact pinned owner:35 policy scenarios,1,352 ordered pairs,69,984 triples,65,536-event histories/1,024 recovery checkpoints,135 ownership assertions and12,096 reentry histories pass in both compiler modes. Integrated byte equality and separate combined controller/async/host/UI tests connect that scoped result to this release. |
| Actual Apple host | Real Combine main/worker delivery covers17 registered names/34 deliveries and cancellation. Real RunLoop retries retain0.5s policy with scheduling delay. Audio/location response doubles remain distinct from actual OS interruptions. AVAudioFile decodes400 zero samples from the original50ms WAV. |
| Actual SDK/archive | Xcode27.0 27A266a, iPhoneOS27.0, Apple Swift6.4 and macOS27.0 26A428. Twelve production Swift files pass warnings-as-errors typechecking; its diagnostic log is empty. Generated framework and disposable product source are bound to this exact commit/tree. |
| Seeded Simulator | Ten successful original/remapped-identity installs/launches: saved tabs, durable Start/relaunch with real TCP echo, and saved Stop. Source/product guards and cleanup pass. These are preseeded JSON tests, not user file-picker or physical installer tests. |
| Actual UI | iPhone16/iOS27.0 build24A434: three cases pass, zero failures/skips/expected failures; runtimeWarnings=[] and cleanup=[]. Async audio107.216s, integration111.035s, statistics80.281s; recorded test-session window364.599s. Original predicates and900s command limit are retained. |

Thirteen original UI attachments and five seeded-app captures were visually inspected.
They show all four tabs, Playing/Off, configuration controls, and real Total/IP tables.
Scrolling/hittability tests establish access; an overview capture does not imply every
row or footer is simultaneously unobscured by the floating tab bar. In each statistics
orientation the actual relays carry64+2048+48001=50113 bytes per IPv4/IPv6 peer. Portrait
Total In/Out/Sum is100.226/100.226/200.452KB, each peer50.113/50.113/100.226KB.
After Stop/Start, landscape Total is200.452/200.452/400.904KB, each peer100.226/
100.226/200.452KB. The final JSON records serverRunning=false and both Background
choices false. Runtime counts are not mocked UI values or whole-interface traffic.

### Real retention with cumulative counters

The real composed-forwarder fixture receives48,001 bytes, then30,001 about120 seconds
later, and no further packet. Linux observed30500 capacity at300.175501s and1500 at
420.282022s; Apple observed300.025730s and420.050674s. Demand spacings were120.060183s
and120.007261s. Total and the registered IP retain In78002/Out0 after reclamation.
The fixture uses real UDP, allocator, clock and Hev timer with a test-only600s
communication timeout, not a change to the application's60s default or a physical
RSS benchmark. Scheduling, blocked I/O and process suspension can defer cleanup.

### Actual unsigned product and source correspondence

The generated product is `Socks5-integrated-unsigned.ipa`, version1.1.0/build10,
bundle`hev.Socks5`,285407 bytes. SHA-256:

```text
c84cda95f7e6c31ff8bd507f0180e9f86dd54aa9a3e3a1fc1e3b9b7d4e66b4a1
```

Its actual ARM64 Mach-O targets iPhoneOS27.0/minimum17.2, with no signature load
command or encryption. The IPA has seven regular payload files: executable, plist,
PkgInfo, Assets.car, two fallback icon PNGs and Silence.wav. CI compared the entire
payload inventory and bytes with the archive, not just executable/plist. Independent
post-download parsing confirms the IPA hash/identity, Mach-O target and unsigned
state, WAV hash and actual app/dSYM UUID`78205DB1-9792-3928-98C1-B40B14ACF29D`.
The matching DWARF binary defines server_stats, server_client_stats and server_prepare;
those definitions are not inferred from source declarations or undefined symbols.
Archive/CAR/ImageIO checks pass: original1024 image,120px iPhone and152px iPad
fallbacks are valid and opaque. Background modes and purpose strings remain exact.

The compiled16-file framework inventory is a runner-recorded build result, distinct
from the unchanged committed baseline framework. Its platform slices are generated
from the same eight-patch source; device and Simulator binaries are not claimed to
be byte-identical. The Simulator executable digest is a runner observation. The
actual delivered IPA and dSYM bytes were independently read and hashed.

Original current-run artifact identities:

| Artifact | SHA-256 |
| --- | --- |
| Linux11087850430 | d8810363a1a64aeab7fb58b4056281782c9783da53781f059ef852d98b8ec226 |
| Apple11087913931 | 7347394f223c1ad6754c99a2f474b3f8a32d6ce14fec8d6b0dd73323d299c7d8 |

Both original ZIP CRCs/digests and four239-file source archives (Linux, Apple native,
Apple packaged-source and UI source) were inspected. Bytes, Git modes, comments and
full manifests reconstruct the tested tree. Genuine reachable-history bundles verify
main/previous-release/owner ancestry. Source, SDK, product and UI cleanliness gates
are separate results. The companion delivery includes these originals and an offline
verifier; offline integrity is not another compilation or device execution.

### Resolved integration failures and retained limits

The first posted source32675a59/run36690658776 failed because two out-of-tree inherited
C fixtures were formatted without their upstream style. Source9de1949 explicitly
selects the pinned server's .clang-format, retaining formatter18 and exact fixture
bytes. It does not modify production C to satisfy a different formatter.

Run36691137777 at9de1949 passed the combined native dispatcher on both hosts, then
failed Background's unchanged whole-app no-Task.sleep source predicate: the approved
Statistics sampler legitimately uses Task.sleep in release. Source18608e48 runs that
unchanged full policy driver at the exact Background owner in a genuine detached
worktree. Its model/control-flow bodies still equal the integrated controller; direct
release controller/async/real-host and actual combined UI tests remain. No assertion
is deleted and no predicate is falsely presented as inspecting the whole combined
app. The original shell policy had no aggregate timeout; selected policy execution
retains that behavior and its child limits, while other owner checks keep180s and
worktree operations60s. Existing workflow/UI bounds remain. Only two release
orchestration files change in this repair, no feature or runtime file.

All four original failed ZIPs are retained. The earlier native successes do not turn
those failed workflows or unexecuted Apple stages into passes. The final source ran
fresh on both hosts without retry. Supplemental local full-history source/ownership/
input/package controls passed nine commands; the scoped Background policy also passed
locally. These supplement, not replace, the completed combined CI.

ASan's coroutine alternate-stack limitation, upstream platform-empty libtool warnings,
AppIntents extraction notices and runner action/tool notices remain in original logs.
No matching synchronous-audio main-thread advisory appears in the final console or
xcresult. Empty SDK/runtime-warning results are not a claim that every tool emitted
no notice or that every library path was sanitizer-instrumented. Existing intentional
process-lifetime registry allocations and their leak-check policy remain unchanged.

### Final documentation publication

This closing publication changes only README and its identical integrated feature
specification. The other237 of239 paths keep tested bytes and modes, including all
runtime files, eight patches, tests, source pins and workflow. Its direct parent is
the tested18608e48 commit. Publication identity is separate from the IPA's execution
source; a documentation-only commit does not manufacture a second runtime test.
All other seven branch heads and previous build9 products are unchanged.

The release branch, exact-source combined CI, unsigned build10 product and documented
verification are complete within the executed scope. Known fixed-port unknown-peer
UDP ownership restrictions remain explicit; no physical SideStore/LiveContainer,
real long-running background survival, external file-provider or device resource
measurement is newly certified. This is not an unconditional zero-defect guarantee
for every possible input, scheduler, installer or host environment.
