from pathlib import Path
import hashlib, json, os, subprocess, time
ROOT=Path.cwd(); OUT=ROOT/'artifacts/settings';OUT.mkdir(parents=True,exist_ok=True)
P=Path(os.environ['RUNNER_TEMP'])/'product'
task=json.loads((ROOT/'Diagnostics/task.json').read_text());sha=task['settings']
branch='work/loop-settings-candidate-20261017'
def git(*args):return subprocess.check_output(['git',*args],cwd=P if P.exists() else ROOT,text=True,timeout=120).strip()
subprocess.run(['git','worktree','add','--detach',str(P),sha],check=True,timeout=120)
assert git('rev-parse','HEAD')==sha
p=P/'Tests/Settings/AsyncStorageTests.swift';s=p.read_text()
old='_ condition: @autoclosure () -> Bool';assert s.count(old)==1
s=s.replace(old,'_ condition: Bool').replace('if !condition() {','if !condition {');p.write_text(s)
git('add','Tests/Settings/AsyncStorageTests.swift')
env=dict(os.environ,GIT_AUTHOR_NAME='AAAHN-AAAHN',GIT_COMMITTER_NAME='AAAHN-AAAHN',GIT_AUTHOR_EMAIL='101960409+AAAHN-AAAHN@users.noreply.github.com',GIT_COMMITTER_EMAIL='101960409+AAAHN-AAAHN@users.noreply.github.com')
subprocess.run(['git','commit','-m','test(settings): evaluate throwing disk assertions before comparison'],cwd=P,env=env,check=True,timeout=120)
head=git('rev-parse','HEAD')
remote=git('ls-remote','--heads','origin','refs/heads/'+branch).split()[0];assert remote==sha
print(git('push','--force-with-lease=refs/heads/'+branch+':'+sha,'origin','HEAD:refs/heads/'+branch))
records=[]
def run(args,label,limit=120):
    args=list(map(str,args));begin=time.time()
    with (OUT/(label+'.log')).open('w') as f:
        try:p=subprocess.run(args,cwd=P,stdout=f,stderr=subprocess.STDOUT,timeout=limit);code=p.returncode
        except subprocess.TimeoutExpired:code=124
    records.append({'label':label,'argv':args,'exit_code':code,'seconds':time.time()-begin})
    (OUT/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
    print(label,'exit',code,flush=True)
    if code:print((OUT/(label+'.log')).read_text()[-18000:],flush=True)
    return code
sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
assert subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-version'],text=True).startswith('27.')
owned=['Socks5/Server/ServerSettings.swift','Socks5/Settings/AppSettings.swift','Socks5/Settings/SettingsStore.swift']
run(['xcrun','swiftc','-typecheck','-swift-version','5','-strict-concurrency=complete','-warnings-as-errors','-sdk',sdk,'-target','arm64-apple-ios17.2',*owned],'sdk-owned')
app=[str(x.relative_to(P)) for x in sorted((P/'Socks5').rglob('*.swift'))]
run(['xcrun','swiftc','-typecheck','-swift-version','5','-warnings-as-errors','-sdk',sdk,'-target','arm64-apple-ios17.2','-I','HevSocks5Server.xcframework/ios-arm64/Headers',*app],'sdk-app')
cases=['normal','blocked-load','blocked-save','save-failure','invalid-import','stale-import','cancel-commit','cancel-corrupt-commit','supersede-commit','ordered-imports','load-failure','migration','reentrant-edit']
for mode in ['-Onone','-O']:
    exe=OUT/('storage'+mode)
    if run(['swiftc',mode,'-swift-version','5','-strict-concurrency=complete','-warnings-as-errors','-parse-as-library',*owned,'Tests/Settings/AsyncStorageTests.swift','-o',exe],'compile'+mode)==0:
        for case in cases:run([exe,case],mode+'-'+case,45)
git('archive','--format=zip','HEAD','-o',str(OUT/'source.zip'))
git('bundle','create',str(OUT/'candidate.bundle'),'HEAD','^a22bc4579a82e46b9e20389182bc1e63e6deedbf')
assert not git('status','--porcelain')
(OUT/'result.json').write_text(json.dumps({'head':head,'baseline':'a22bc4579a82e46b9e20389182bc1e63e6deedbf','candidate_branch':branch,'failed':[x['label'] for x in records if x['exit_code']],'commands':len(records)},indent=2)+'\n')
print('RESULT', (OUT/'result.json').read_text(),flush=True)
raise SystemExit(1 if any(x['exit_code'] for x in records) else 0)
