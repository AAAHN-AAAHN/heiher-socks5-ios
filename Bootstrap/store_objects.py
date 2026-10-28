#!/usr/bin/env python3
"""Store verified, exact Git objects. This program cannot change remote refs."""
import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from import_candidates import REPOSITORY, full_sha, require

ROOT = Path(__file__).resolve().parents[1]
MODES = {'100644': 'blob', '100755': 'blob', '120000': 'blob',
         '040000': 'tree', '160000': 'commit'}


def git(*args, data=None):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], input=data)


def identity(line):
    match = re.fullmatch(r'(.*) <([^>]*)> (-?\d+) ([+-])(\d{2})(\d{2})', line)
    require(match is not None, 'Unsupported Git identity format')
    name, email, seconds, sign, hours, minutes = match.groups()
    require(int(minutes) < 60, 'Invalid Git timezone')
    offset = (int(hours) * 60 + int(minutes)) * (1 if sign == '+' else -1)
    date = datetime.fromtimestamp(int(seconds), timezone(timedelta(minutes=offset)))
    # Reject any representation that the JSON GitData API cannot preserve.
    require(f'{name} <{email}> {int(date.timestamp())} {date:%z}' == line,
            'Git identity does not round-trip exactly')
    return {'name': name, 'email': email, 'date': date.isoformat(timespec='seconds')}


def object_payload(kind, raw):
    if kind == 'blob':
        return {'content': base64.b64encode(raw).decode('ascii'), 'encoding': 'base64'}, []
    if kind == 'tree':
        entries, dependencies, offset = [], [], 0
        while offset < len(raw):
            end = raw.index(b'\0', offset)
            mode, name = raw[offset:end].split(b' ', 1)
            mode = mode.decode('ascii').zfill(6)
            require(mode in MODES and name not in (b'', b'.', b'..') and b'/' not in name,
                    'Unsupported Git tree entry')
            child = raw[end + 1:end + 21].hex()
            require(full_sha(child), 'Truncated Git tree entry')
            entry = dict(path=name.decode('utf-8'), mode=mode, type=MODES[mode], sha=child)
            entries.append(entry)
            if mode != '160000':
                dependencies.append(child)
            offset = end + 21
        require(offset == len(raw), 'Invalid Git tree length')
        rebuilt = b''.join((entry['mode'].lstrip('0') + ' ' + entry['path']).encode('utf-8') +
                           b'\0' + bytes.fromhex(entry['sha']) for entry in entries)
        require(rebuilt == raw, 'Git tree does not round-trip exactly')
        return {'tree': entries}, dependencies
    require(kind == 'commit', 'Unsupported Git object type: ' + kind)
    headers, message = raw.split(b'\n\n', 1)
    value = {'message': message.decode('utf-8'), 'parents': []}
    original = {}
    for line in headers.decode('utf-8').split('\n'):
        key, body = line.split(' ', 1)
        if key == 'parent':
            require(full_sha(body), 'Invalid parent identity')
            value['parents'].append(body)
        else:
            require(key in ('tree', 'author', 'committer') and key not in original,
                    'Unsupported or duplicate commit header: ' + key)
            original[key] = body
            value[key] = identity(body) if key != 'tree' else body
    require(set(original) == {'tree', 'author', 'committer'} and full_sha(value['tree']),
            'Incomplete commit identity')
    rebuilt = ('tree ' + value['tree'] + '\n' +
               ''.join('parent ' + parent + '\n' for parent in value['parents']) +
               'author ' + original['author'] + '\ncommitter ' + original['committer'] +
               '\n\n' + value['message']).encode('utf-8')
    require(rebuilt == raw, 'Commit headers or message do not round-trip exactly')
    return value, [value['tree'], *value['parents']]


def prerequisites(bundle):
    result = []
    with bundle.open('rb') as stream:
        require(stream.readline() == b'# v2 git bundle\n', 'Expected an exact version-2 Git bundle')
        for line in stream:
            if line == b'\n':
                break
            if line.startswith(b'-'):
                sha = line[1:41].decode('ascii')
                require(full_sha(sha) and line[41:42] == b' ', 'Invalid bundle prerequisite')
                result.append(sha)
        else:
            raise SystemExit('Incomplete Git bundle header')
    require(len(result) == len(set(result)), 'Duplicate bundle prerequisite')
    return result


def plan_objects(heads, excluded):
    objects = git('rev-list', '--objects', '--no-object-names', *heads,
                  *('^' + sha for sha in excluded)).decode('ascii').splitlines()
    if not objects:
        return {}
    types = git('cat-file', '--batch-check=%(objectname) %(objecttype)',
                data=('\n'.join(objects) + '\n').encode('ascii')).decode('ascii').splitlines()
    plan = {}
    for line in types:
        sha, kind = line.split(' ')
        require(full_sha(sha) and kind in ('blob', 'tree', 'commit'), 'Invalid object closure')
        raw = git('cat-file', kind, sha)
        require(hashlib.sha1(f'{kind} {len(raw)}\0'.encode('ascii') + raw).hexdigest() == sha,
                'Local object identity differs: ' + sha)
        payload, dependencies = object_payload(kind, raw)
        plan[sha] = (kind, payload, dependencies)
    require(set(plan) == set(objects), 'Incomplete object plan')
    return plan


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, url):
        return None


class GitData:
    def __init__(self, token):
        require(bool(token), 'GH_TOKEN is required for object storage')
        self.token = token
        self.opener = build_opener(NoRedirect)

    def __call__(self, method, path, value=None):
        permitted = ((method == 'GET' and re.fullmatch(r'git/commits/[0-9a-f]{40}', path)) or
                     (method == 'POST' and path in ('git/blobs', 'git/trees', 'git/commits')))
        require(permitted, 'Object-only API endpoint required')
        request = Request('https://api.github.com/repos/' + REPOSITORY + '/' + path,
                          data=None if value is None else json.dumps(value).encode('utf-8'),
                          method=method, headers={
                              'Authorization': 'Bearer ' + self.token,
                              'Accept': 'application/vnd.github+json',
                              'X-GitHub-Api-Version': '2022-11-28',
                              'Content-Type': 'application/json'})
        for attempt in range(4):
            try:
                with self.opener.open(request, timeout=60) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code not in (429, 502, 503, 504) or attempt == 3:
                    detail = error.read().decode('utf-8', errors='replace')
                    raise SystemExit(f'GitData {method} {path} failed: HTTP {error.code}: {detail}') from None
                delay = error.headers.get('Retry-After', '10')
                time.sleep(min(30, int(delay)) if delay.isdecimal() else 10)


def store_objects(plan, heads, call, stored):
    done = set(stored)

    def store(sha):
        if sha not in plan or sha in done:
            return
        kind, payload, dependencies = plan[sha]
        for dependency in dependencies:
            store(dependency)
        result = call('POST', 'git/' + {'blob': 'blobs', 'tree': 'trees', 'commit': 'commits'}[kind], payload)
        require(result.get('sha') == sha, 'GitData object identity differs: ' + kind + ' ' + sha)
        stored.append(sha)
        done.add(sha)
        print('Stored', kind, sha, flush=True)

    for sha in heads:
        store(sha)
    require(set(stored) == set(plan), 'Some planned objects were not stored')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true',
                        help='Validate every payload locally without credentials or remote calls')
    options = parser.parse_args()
    # Reuse the complete read-only gate: exact helper, bundle, prerequisites,
    # declared heads, unchanged refs and forbidden Ping/ICMP ancestry checks.
    subprocess.run([sys.executable, str(ROOT / 'Bootstrap/import_candidates.py')], check=True)
    manifest = json.loads((ROOT / 'Bootstrap/candidates.json').read_bytes())
    heads = [entry['sha'] for entry in manifest['candidates'] + manifest.get('support', [])]
    excluded = prerequisites(ROOT / 'Bootstrap/candidates.bundle')
    plan = plan_objects(heads, excluded)
    output = ROOT / 'artifacts/candidate-objects'
    output.mkdir(parents=True, exist_ok=True)
    stored = []
    result = dict(result='FAIL', check_only=options.check_only,
                  helper_commit=git('rev-parse', 'HEAD').decode('ascii').strip(),
                  bundle_sha256=manifest['sha256'], candidates=manifest['candidates'],
                  support=manifest.get('support', []), prerequisites=excluded,
                  planned_objects=len(plan), planned_types=dict(Counter(item[0] for item in plan.values())),
                  stored=stored, branch_updates=False, tag_updates=False,
                  run_id=os.environ.get('GITHUB_RUN_ID'))
    try:
        if not options.check_only:
            call = GitData(os.environ.get('GH_TOKEN'))
            # Confirm every omitted prerequisite on GitHub before any object write.
            for sha in excluded:
                require(call('GET', 'git/commits/' + sha).get('sha') == sha,
                        'Remote prerequisite is unavailable: ' + sha)
            store_objects(plan, heads, call, stored)
        result['result'] = 'PASS'
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
