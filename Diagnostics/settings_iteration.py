from pathlib import Path
# Reuse the exact SDK/native validation driver. Only the requested local patch
# preamble changes; all test cases, native inputs and deadlines remain intact.
path=Path('Diagnostics/settings_check.py')
s=path.read_text()
a=s.index("p=P/'Socks5/Settings/SettingsStore.swift';s=p.read_text()")
b=s.index("head=git('rev-parse','HEAD')",a)
s=s[:a]+'''p=P/'Tests/Settings/AsyncStorageTests.swift'
v=p.read_text()
old='@MainActor static func make('
assert v.count(old)==1
p.write_text(v.replace(old,'@MainActor private static func make('))
git('add','Tests/Settings/AsyncStorageTests.swift')
env=dict(os.environ,GIT_AUTHOR_NAME='AAAHN-AAAHN',GIT_COMMITTER_NAME='AAAHN-AAAHN',GIT_AUTHOR_EMAIL='101960409+AAAHN-AAAHN@users.noreply.github.com',GIT_COMMITTER_EMAIL='101960409+AAAHN-AAAHN@users.noreply.github.com')
subprocess.run(['git','commit','-m','test(settings): scope the private disk-fixture constructor'],cwd=P,env=env,check=True,timeout=120)
assert git('ls-remote','--heads','origin','refs/heads/'+branch).split()[0]==sha
print(git('push','--force-with-lease=refs/heads/'+branch+':'+sha,'origin','HEAD:refs/heads/'+branch))
'''+s[b:]
exec(compile(s,str(path),'exec'))
