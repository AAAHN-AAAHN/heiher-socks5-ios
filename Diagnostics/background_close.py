from pathlib import Path
import json,os,shutil,subprocess,time
ROOT=Path.cwd();OUT=ROOT/'artifacts/background';OUT.mkdir(parents=True,exist_ok=True)
P=Path(os.environ['RUNNER_TEMP'])/'product'
BASE='3c2901f57a2bdfc76aaf248dedd9d0cdd64f3157';BRANCH='work/loop-background-candidate-20261017'
subprocess.run(['git','worktree','add','--detach',str(P),BASE],check=True,timeout=120)
def git(*args):return subprocess.check_output(['git',*args],cwd=P,text=True,timeout=120).strip()
records=[]
def run(args,label,limit=90):
    with (OUT/(label+'.log')).open('w') as f:
        try:r=subprocess.run(list(map(str,args)),cwd=P,stdout=f,stderr=subprocess.STDOUT,timeout=limit);code=r.returncode
        except subprocess.TimeoutExpired:code=124
    text=(OUT/(label+'.log')).read_text(errors='replace')
    records.append({'label':label,'argv':list(map(str,args)),'exit_code':code})
    (OUT/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
    print(label,'exit',code,flush=True)
    if code:print(text[-5000:],flush=True)
    return code,text
extension='''
extension LoopAudioService {
    // Test-only scheduling control. Not compiled into the product target.
    func auditStopAdmission(owner: UInt64, direct: Bool, result: @escaping @Sendable (Bool) -> Void) {
        control.async { [self] in
            if work != nil {
                control.asyncAfter(deadline: .now() + 0.001) { [self] in
                    auditStopAdmission(owner: owner, direct: direct, result: result)
                }
                return
            }
            cancelTimer()
            setEnabled(false, owner: owner)
            setEnabled(true, owner: owner)
            if direct { begin(.inspect) } else { tick() }
            if case .stop? = work?.command { result(true) }
            else { result(releaseBarrier) }
        }
    }
}
'''
service=P/'Socks5/BackgroundKeepAlive/LoopAudioService.swift'
monitor=P/'Socks5/BackgroundKeepAlive/PlaybackProgressMonitor.swift'
lease=P/'Socks5/BackgroundKeepAlive/RecoveryExecutionLease.swift'
test=P/'Tests/Background/RecoveryBoundaryTests.swift'
shutil.copyfile(ROOT/'Diagnostics/RecoveryBoundaryTests.swift',test)
def compile_probe(kind,mode):
    source=OUT/(kind+mode+'-service.swift');source.write_text(service.read_text()+extension)
    exe=OUT/(kind+mode)
    code,_=run(['swiftc',mode,'-swift-version','5','-strict-concurrency=complete','-warnings-as-errors','-parse-as-library',source,monitor,lease,test,'-o',exe],'compile-'+kind+mode)
    assert code==0
    return exe
expected={'race-tick':'ACCEPTED_STOP_BARRIER_LOST','race-admit':'ACCEPTED_STOP_BARRIER_LOST','lease-blocked':'LEASE_BLOCKED_CONTROL','progress-clock':'PROGRESS_CLOCK_DISCONTINUITY'}
for mode in ['-Onone','-O']:
    exe=compile_probe('before',mode)
    for case,reason in expected.items():
        code,text=run([exe,case],'before'+mode+'-'+case,30)
        assert code not in (0,124) and reason in text,(case,code)
s=service.read_text()
def replace(old,new,count=1):
    global s
    assert s.count(old)==count,(old,s.count(old),count)
    s=s.replace(old,new)
replace('    typealias Factory = (DispatchQueue,','    typealias Factory = @Sendable (DispatchQueue,')
replace('        case loading = "Loading silent WAV"','        case protecting = "Requesting finite recovery execution time"\n        case loading = "Loading silent WAV"')
replace('    private func drain() {','''    /// Every control-lane observation preserves stop/resource transitions. Reading
    /// a newer ingress ticket in a timer may not consume a pending Off-On barrier.
    private func adopt(_ next: Ticket) {
        if next.stop != current.stop { releaseBarrier = true }
        if next.epoch != current.epoch {
            rebuild = true
            playing = false
            monitor.knownFailure(now: Self.now)
        }
        current = next
    }

    private func drain() {''')
replace('        if next.stop != current.stop { releaseBarrier = true }\n        current = next','        adopt(next)')
# Only standalone assignments; retain the assignment inside adopt itself.
replace('        current = latest()','        adopt(latest())',3)
replace('        let input = latest()\n        if case .start = command, !input.on { drain(); return }','''        adopt(latest())
        if releaseBarrier {
            if case .stop = command {} else { begin(.stop); return }
        }
        let input = current
        if case .stop = command {} else if !input.on { drain(); return }''')
replace('                claim.start()','                // The platform request runs on I/O, while control keeps watching.')
replace('        io.async { [self] in\n            self.mark(job.id, .queued, entered: true)','''        let executionClaim = lease
        io.async { [self] in
            self.mark(job.id, .queued, entered: true)
            if let executionClaim {
                self.mark(job.id, .protecting)
                executionClaim.start()
            }''')
# ASCII source contract, preserving the exact displayed punctuation.
s=''.join(c if ord(c)<128 else '\\u{'+format(ord(c),'x')+'}' for c in s)
service.write_text(s)
m=monitor.read_text()
old='            && b.deviceTime >= a.deviceTime'
assert m.count(old)==1
m=m.replace(old,'''            && b.deviceTime >= a.deviceTime
            && abs((b.deviceTime - a.deviceTime) - (b.finishedAt - a.finishedAt))
                <= max(0.01, max(a.bufferDuration, b.bufferDuration) * 4)
                    + (a.finishedAt - a.startedAt) + (b.finishedAt - b.startedAt)''')
old='        let moved = distance(s.position - p.position, period: s.duration) > tolerance(p, s)'
assert m.count(old)==1
m=m.replace(old,'''        let observed = s.position - p.position
        let expected = (s.deviceTime - p.deviceTime) * s.rate
        let uncertainty = tolerance(p, s)
        let moved = distance(observed, period: s.duration) > uncertainty
            && distance(observed - expected, period: s.duration) <= uncertainty''')
monitor.write_text(m)
# Keep source-wide ASCII invariant without changing strings shown to the user.
for p in (P/'Socks5/BackgroundKeepAlive').glob('*.swift'):
    original=p.read_text();value=''.join(c if ord(c)<128 else '\\u{'+format(ord(c),'x')+'}' for c in original)
    if value!=original:p.write_text(value)
# The test-only extension is assembled by its driver, never a target source.
(P/'Tests/Background/RecoveryAdmissionAccess.swift.inc').write_text(extension)
for mode in ['-Onone','-O']:
    exe=compile_probe('after',mode)
    for case in [*expected,'lease-matrix']:
        assert run([exe,case],'after'+mode+'-'+case,30)[0]==0
    exe=OUT/('service'+mode)
    assert run(['swiftc',mode,'-swift-version','5','-strict-concurrency=complete','-warnings-as-errors','-parse-as-library',service,monitor,lease,'Tests/Background/LoopAudioServiceTests.swift','-o',exe],'service-compile'+mode)[0]==0
    for case in ['normal','finite-failure','pending-off-on','pending-reset','pending-owner','pending-deactivation','pending-inspection','storm','stopped-player','duplicate-completion']:
        assert run([exe,case],'service'+mode+'-'+case,30)[0]==0
sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
assert subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-version'],text=True).startswith('27.')
assert run(['xcrun','swiftc','-typecheck','-swift-version','5','-strict-concurrency=complete','-warnings-as-errors','-sdk',sdk,'-target','arm64-apple-ios17.2',*sorted((P/'Socks5/BackgroundKeepAlive').glob('*.swift'))],'sdk-owned')[0]==0
git('diff','--check')
git('add','Socks5/BackgroundKeepAlive','Tests/Background/RecoveryBoundaryTests.swift','Tests/Background/RecoveryAdmissionAccess.swift.inc')
env=dict(os.environ,GIT_AUTHOR_NAME='AAAHN-AAAHN',GIT_COMMITTER_NAME='AAAHN-AAAHN',GIT_AUTHOR_EMAIL='101960409+AAAHN-AAAHN@users.noreply.github.com',GIT_COMMITTER_EMAIL='101960409+AAAHN-AAAHN@users.noreply.github.com')
subprocess.run(['git','commit','-m','fix(background): preserve stop admission and isolate recovery claims'],cwd=P,env=env,check=True)
head=git('rev-parse','HEAD')
assert git('ls-remote','--heads','origin','refs/heads/'+BRANCH).split()[0]==BASE
print(git('push','--force-with-lease=refs/heads/'+BRANCH+':'+BASE,'origin','HEAD:refs/heads/'+BRANCH))
git('archive','--format=zip','HEAD','-o',str(OUT/'source.zip'))
git('bundle','create',str(OUT/'candidate.bundle'),'HEAD','^618b3d2b413937aaad7373ee2af9e693ec81b84a')
result={'head':head,'before':BASE,'negative_cases':8,'normal_boundary_cases':10,'normal_service_cases':20,'owned_sdk':'pass','product_branch_published':False}
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('RESULT',json.dumps(result),flush=True)
# Actual app UI assertions and timeouts are unchanged.
code,_=run(['python3','Tests/Background/check_async_ui.py'],'original-ui',1200)
raise SystemExit(code)
