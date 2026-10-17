from pathlib import Path, PurePosixPath
import hashlib, io, json, os, subprocess, zipfile
ROOT = Path.cwd()
OUT = ROOT / 'artifacts/provenance'
OUT.mkdir(parents=True, exist_ok=True)
P = Path(os.environ['RUNNER_TEMP']) / 'product'

def git(*args, input=None, env=None, cwd=None):
    return subprocess.check_output(['git', *args], input=input, env=env, cwd=cwd or P, timeout=180).decode().strip()

git('worktree', 'add', '--detach', str(P), '618b3d2b413937aaad7373ee2af9e693ec81b84a', cwd=ROOT)

def artifact(number, digest):
    data = subprocess.check_output(['gh', 'api', f'repos/AAAHN-AAAHN/heiher-socks5-ios/actions/artifacts/{number}/zip'], timeout=120)
    assert hashlib.sha256(data).hexdigest() == digest, (number, len(data), hashlib.sha256(data).hexdigest())
    (OUT / f'{number}.zip').write_bytes(data)
    z = zipfile.ZipFile(io.BytesIO(data)); assert z.testzip() is None
    return z

before = git('ls-remote', '--heads', 'origin')
(OUT/'before.txt').write_text(before+'\n')
z=artifact(12051994151,'eb41049a302bc7b641e3ec0a074d1a95235498a6f9509f2524b38bbf34b705d5')
data=z.read('provenance/candidate.bundle')
assert hashlib.sha256(data).hexdigest()=='bc184957bf0883cea9d1607fc838073e63495e1ca218c7502db890400abd1f6c'
bundle=OUT/'candidate.bundle';bundle.write_bytes(data)
git('bundle','verify',str(bundle))
git('fetch',str(bundle),'refs/heads/feature/background')
z=artifact(12058113666,'16910d3c77a6dfe6a2dde3f56fdd6e514afb9feff629fdb0b0d1f324f1be6a28')
source=z.read('provenance/source.zip');(OUT/'source.zip').write_bytes(source)
source=zipfile.ZipFile(io.BytesIO(source)); assert source.testzip() is None
base={}
for line in git('ls-tree','-r','26e20692ac1c3336fb27c48d1e9b10846f646475').splitlines():
    meta,name=line.split('\t');mode,kind,sha=meta.split();assert kind=='blob'
    base[name]=(int(mode,8),sha)
env=dict(os.environ,GIT_INDEX_FILE=str(Path(os.environ['RUNNER_TEMP'])/'candidate-index'))
git('read-tree','--empty',env=env)
names=set(); records=[];changed=[]
for info in source.infolist():
    if info.is_dir(): continue
    name=info.filename; parts=PurePosixPath(name).parts
    assert not name.startswith('/') and '..' not in parts and '.git' not in parts
    assert name not in names and name in base; names.add(name)
    data=source.read(info); mode=base[name][0]
    assert mode in (0o100644,0o100755,0o120000),(name,oct(mode))
    sha=git('hash-object','-w','--stdin',input=data)
    if sha!=base[name][1]: changed.append(name)
    records.append(f'{mode:o} {sha}\t{name}\0')
assert names==set(base)
assert set(changed)=={'Socks5/BackgroundKeepAlive/LoopAudioService.swift','Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'},changed
git('update-index','-z','--index-info',input=''.join(records).encode(),env=env)
tree=git('write-tree',env=env)
assert tree=='661d825c814b9af8d8d0a1d8301be87bb12f5064', tree
raw=('tree '+tree+'\nparent 26e20692ac1c3336fb27c48d1e9b10846f646475\n'
    'author AAAHN-AAAHN <101960409+AAAHN-AAAHN@users.noreply.github.com> 1792166798 +0000\n'
    'committer AAAHN-AAAHN <101960409+AAAHN-AAAHN@users.noreply.github.com> 1792166798 +0000\n\n'
    'fix(background): enforce queue isolation and reject stale playback events\n').encode()
sha=git('hash-object','-t','commit','-w','--stdin',input=raw)
assert sha=='3c2901f57a2bdfc76aaf248dedd9d0cdd64f3157', sha
git('merge-base','--is-ancestor','618b3d2b413937aaad7373ee2af9e693ec81b84a',sha)
git('checkout','--detach',sha)
git('fsck','--full','--strict')
ref='refs/heads/work/loop-background-candidate-20261017'
existing=git('ls-remote','--heads','origin',ref)
assert not existing or existing.split()[0]==sha
if not existing: print(git('push','origin',sha+':'+ref))
(OUT/'recovery.json').write_text(json.dumps({'commit':sha,'tree':tree,'source_files':len(names),'candidate_ref':ref,'mode_source':'26e2069 exact tree','changed_files':changed},indent=2)+'\n')
(OUT/'after.txt').write_text(git('ls-remote','--heads','origin')+'\n')
print('Recovered byte-identical candidate',sha,'files',len(names),flush=True)
(P/'artifacts').mkdir(exist_ok=True)
for mode in ('-Onone','-O'):
    args=['swiftc',mode,'-swift-version','5','-strict-concurrency=complete','-warnings-as-errors','-parse-as-library']
    args += ['Socks5/BackgroundKeepAlive/'+x+'.swift' for x in ('LoopAudioService','PlaybackProgressMonitor','RecoveryExecutionLease')]
    args += ['Tests/Background/LoopAudioServiceTests.swift','-o',str(OUT/'service-tests')]
    subprocess.run(args,cwd=P,check=True,timeout=120)
    with (OUT/('service'+mode+'.log')).open('w') as f:
        for case in ('normal','finite-failure','pending-off-on','pending-reset','pending-owner','pending-deactivation','pending-inspection','storm','stopped-player','duplicate-completion'):
            subprocess.run([str(OUT/'service-tests'),case],cwd=P,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=30)
subprocess.run(['python3','Tests/Background/check_async_ui.py'],cwd=P,check=True,timeout=1200)
