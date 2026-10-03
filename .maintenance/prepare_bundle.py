"""Prepare two reviewed bundle diagnostic blobs; never move refs or open PRs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import unittest

FILES = ['harness.py', 'tests/test_bundle_quarantine_diagnostics.py']

def blob(data):
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()

def build():
    path = Path('harness.py')
    data = path.read_bytes()
    assert blob(data) == 'cfd4e27fd488830eca6ecca838cfe718e5cc0c97'
    old = '''                    raise HarnessError(
                        f"{problem}; the unverified bytes are still live because they "
                        f"could not be quarantined: {exc}"
                    ) from exc'''
    new = '''                    previous = str(backup) if backup is not None else "none (previously absent)"
                    raise HarnessError(
                        f"{problem}; could not quarantine the target: {exc}; "
                        f"current live state is unverified; previous target backup: {previous}"
                    ) from exc'''
    text = data.decode('utf-8')
    assert text.count(old) == 1
    result = text.replace(old, new).encode('utf-8')
    assert blob(result) == '1c186049a592bed1c072fb104b9ebd7040100487'
    path.write_bytes(result)
    subprocess.run([sys.executable, '-m', 'black', *FILES], check=True)
    subprocess.run([sys.executable, '-m', 'ruff', 'check', *FILES], check=True)
    subprocess.run([sys.executable, '-m', 'py_compile', *FILES], check=True)
    sys.path[:0] = [str(Path.cwd()), str(Path.cwd()/'tests')]
    import test_harness
    suite = unittest.defaultTestLoader.loadTestsFromName('test_bundle_quarantine_diagnostics')
    for name in unittest.defaultTestLoader.getTestCaseNames(test_harness.HarnessTests):
        if name.startswith('test_sync_global_bundle'):
            suite.addTest(test_harness.HarnessTests(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    assert result.wasSuccessful()
    subprocess.run(['git','diff','--check'], check=True)
    subprocess.run(['git','diff','--','harness.py'], check=True)
    changed = subprocess.check_output(['git','diff','--name-only'], text=True).splitlines()
    assert set(changed) <= set(FILES)
    receipt = {p:blob(Path(p).read_bytes()) for p in FILES}
    Path('.maintenance/prepared.json').write_text(json.dumps(receipt))
    print('PREPARED',json.dumps(receipt,sort_keys=True))

def publish():
    assert os.environ['GITHUB_REPOSITORY'] == 'Chris0Jeky/agent-harness'
    receipt = json.loads(Path('.maintenance/prepared.json').read_text())
    assert set(receipt) == set(FILES)
    for path, expected in receipt.items():
        data = Path(path).read_bytes()
        assert blob(data) == expected
        payload = json.dumps({'encoding':'base64','content':base64.b64encode(data).decode()}).encode()
        request = urllib.request.Request('https://api.github.com/repos/Chris0Jeky/agent-harness/git/blobs',data=payload,method='POST',headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Content-Type':'application/json','Accept':'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        assert result['sha'] == expected
        print('BLOB',path,expected,flush=True)

if __name__ == '__main__':
    {'build':build,'publish':publish}[sys.argv[1]]()
