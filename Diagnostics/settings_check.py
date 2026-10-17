from pathlib import Path
import hashlib,json,os,shutil,subprocess,time
ROOT=Path.cwd();OUT=ROOT/'artifacts/settings';OUT.mkdir(parents=True,exist_ok=True)
P=Path(os.environ['RUNNER_TEMP'])/'product'
task=json.loads((ROOT/'Diagnostics/task.json').read_text());sha=task['settings']
branch='work/loop-settings-candidate-20261017'
subprocess.run(['git','worktree','add','--detach',str(P),sha],check=True,timeout=120)
def git(*args,cwd=P):return subprocess.check_output(['git',*args],cwd=cwd,text=True,timeout=180).strip()
assert git('rev-parse','HEAD')==sha
p=P/'Socks5/Settings/SettingsStore.swift';s=p.read_text()
if task.get('fix_syntax'):
    pairs=[('= SettingsStore.read\n','= { try SettingsStore.read($0) }\n'),('= SettingsStore.write\n','= { try SettingsStore.write($0, $1) }\n'),('= SettingsStore.readImported\n','= { try SettingsStore.readImported($0) }\n'),('withCheckedThrowingContinuation { receipt in','withCheckedThrowingContinuation { (receipt: CheckedContinuation<Void, Error>) in')]
    for old,new in pairs:
        assert old in s,old;s=s.replace(old,new)
    p.write_text(s)
    git('add','Socks5/Settings/SettingsStore.swift')
    env=dict(os.environ,GIT_AUTHOR_NAME='AAAHN-AAAHN',GIT_COMMITTER_NAME='AAAHN-AAAHN',GIT_AUTHOR_EMAIL='101960409+AAAHN-AAAHN@users.noreply.github.com',GIT_COMMITTER_EMAIL='101960409+AAAHN-AAAHN@users.noreply.github.com')
    subprocess.run(['git','commit','-m','fix(settings): make storage closure sendability and continuation types explicit'],cwd=P,env=env,check=True,timeout=120)
    assert git('ls-remote','--heads','origin','refs/heads/'+branch).split()[0]==sha
    print(git('push','--force-with-lease=refs/heads/'+branch+':'+sha,'origin','HEAD:refs/heads/'+branch))
head=git('rev-parse','HEAD');print('TEST_HEAD',head,flush=True)
records=[]
def run(args,label,limit=180,cwd=P):
    args=list(map(str,args));started=time.time()
    with (OUT/(label+'.log')).open('w') as f:
        try:r=subprocess.run(args,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=limit);code=r.returncode
        except subprocess.TimeoutExpired:code=124
    records.append({'label':label,'argv':args,'cwd':str(cwd),'exit_code':code,'seconds':time.time()-started})
    (OUT/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
    print(label,'exit',code,flush=True)
    if code:print((OUT/(label+'.log')).read_text()[-20000:],flush=True)
    return code
sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
assert subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-version'],text=True).startswith('27.')
owned=['Socks5/Server/ServerSettings.swift','Socks5/Settings/AppSettings.swift','Socks5/Settings/SettingsStore.swift']
run(['xcrun','swiftc','-typecheck','-swift-version','5','-strict-concurrency=complete','-warnings-as-errors','-sdk',sdk,'-target','arm64-apple-ios17.2',*owned],'sdk-owned')
cases=['normal','blocked-load','blocked-save','save-failure','invalid-import','stale-import','cancel-commit','cancel-corrupt-commit','supersede-commit','ordered-imports','load-failure','migration','reentrant-edit']
for mode in ['-Onone','-O']:
    exe=OUT/('storage'+mode)
    if run(['swiftc',mode,'-swift-version','5','-strict-concurrency=complete','-warnings-as-errors','-parse-as-library',*owned,'Tests/Settings/AsyncStorageTests.swift','-o',exe],'compile'+mode)==0:
        for case in cases:run([exe,case],mode+'-'+case,45)
# A full-app typecheck must use the exact ServerControl-patched API, not the
# intentionally unpatched common XCFramework header.
core=Path(os.environ['RUNNER_TEMP'])/'native';applied=False
lock=json.loads((P/'Build/upstream.json').read_text())
try:
    if run(['git','clone','https://github.com/heiher/hev-socks5-server',core],'native-clone',180,ROOT)==0:
        assert run(['git','checkout','--detach',lock['sources']['.']],'native-pin',180,core)==0
        assert run(['git','submodule','update','--init','--recursive'],'native-submodules',300,core)==0
        assert run(['python3','Build/check.py','apply',core],'native-apply')==0;applied=True
        headers=OUT/'headers';headers.mkdir()
        for src,name in [(core/'src/hev-main.h','hev-main.h'),(core/'module.modulemap','module.modulemap')]:shutil.copyfile(src,headers/name)
        app=[str(x.relative_to(P)) for x in sorted((P/'Socks5').rglob('*.swift'))]
        run(['xcrun','swiftc','-typecheck','-swift-version','5','-warnings-as-errors','-sdk',sdk,'-target','arm64-apple-ios17.2','-I',headers,*app],'sdk-app')
finally:
    if applied:run(['python3','Build/check.py','reverse',core],'native-reverse')
git('archive','--format=zip','HEAD','-o',str(OUT/'source.zip'))
git('bundle','create',str(OUT/'candidate.bundle'),'HEAD','^a22bc4579a82e46b9e20389182bc1e63e6deedbf')
assert not git('status','--porcelain')
result={'head':head,'candidate_branch':branch,'failed':[x['label'] for x in records if x['exit_code']],'commands':len(records)}
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('RESULT',json.dumps(result),flush=True)
raise SystemExit(1 if result['failed'] else 0)
