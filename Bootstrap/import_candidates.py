"""Import exact Git objects and create only the explicitly declared temporary CI refs."""
import base64,hashlib,json,os,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPO='AAAHN-AAAHN/heiher-socks5-ios'
assert os.environ['GITHUB_REPOSITORY']==REPO
manifest=json.loads((ROOT/'Bootstrap/candidates.json').read_text())
bundle=ROOT/'Bootstrap/candidates.bundle'
assert hashlib.sha256(bundle.read_bytes()).hexdigest()==manifest['sha256']
def git(*args,env=None):return subprocess.check_output(['git',*args],env=env).decode().strip()
git('bundle','verify',str(bundle));git('bundle','unbundle',str(bundle))
options=[];refs=[]
for entry in manifest['candidates']:
 sha,ref=entry['sha'],entry['ref']
 assert re.fullmatch(r'[0-9a-f]{40}',sha)
 assert re.fullmatch(r'refs/heads/work/udp-echo-(main|udp|statistics|background|server|settings|icon|integrated)-20261028',ref)
 expected=entry.get('previous','')
 assert expected=='' or re.fullmatch(r'[0-9a-f]{40}',expected)
 for bad in ('e5980901a6c0b7a8b12ddc37461e22405f7dbe0e','0a62910f5e444edbf176fe3ccd52363e5b8f869e'):
  assert subprocess.run(['git','merge-base','--is-ancestor',bad,sha]).returncode==1
 options.append('--force-with-lease='+ref+':'+expected);refs.append(sha+':'+ref)
auth=base64.b64encode(('x-access-token:'+os.environ['GH_TOKEN']).encode()).decode()
env=dict(os.environ,GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',GIT_CONFIG_VALUE_0='AUTHORIZATION: basic '+auth)
git('push','--atomic',*options,'origin',*refs,env=env)
output=ROOT/'artifacts/candidate-import';output.mkdir(parents=True,exist_ok=True)
result={'result':'PASS','operating_refs_changed':False,'candidates':manifest['candidates'],'bundle_sha256':manifest['sha256']}
(output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('matrix='+json.dumps({'include':manifest['matrix']},separators=(',',':'))+'\n')
print(json.dumps(result,indent=2))
