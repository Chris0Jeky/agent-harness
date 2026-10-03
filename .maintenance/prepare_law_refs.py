"""Apply one reviewed citation patch; verify it and store blobs, never move refs."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

BASE = '86139e66112fda07aec5ecfc86f392ab17fc4a56'
PATCH = '9f2acd1e50bf96aeff23eb2304cc81de2e9a707e57841e30c36ad4e0a76e898f'
FILES = {'SPECS.md': 'da8c8ff1c97e0dd8363735513926e9154edec269', 'scripts/merge_gate_model.py': 'c8a8e1feeff2cf1294bf7206c20ef1b4f924505f', 'plans/ACTIVE.md': '425ba10b07107a0126cfdc99bcaec981128accfb', 'docs/maintenance/LAW_REFERENCE_MIGRATION.md': '0c174980db09a4d170b38e8386b90ee72611898c'}
OUT = Path('.maintenance-output')

def semantic(data):
    tree = ast.parse(data)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            node.body.pop(0)
    return ast.dump(tree, include_attributes=False)

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def build():
    OUT.mkdir(exist_ok=True)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD^'], text=True).strip() == BASE
    patch = Path('.maintenance/law-transition.patch').read_bytes()
    assert hashlib.sha256(patch).hexdigest() == PATCH, 'reviewed patch mismatch'
    old_model = Path('scripts/merge_gate_model.py').read_bytes()
    unchanged = {p: Path(p).read_bytes() for p in ('BOOK.md', 'templates/hooks/dispatch.py', 'docs/extraction/public-v0-manifest.json')}
    subprocess.run(['git', 'apply', '--index', '.maintenance/law-transition.patch'], check=True)
    assert set(subprocess.check_output(['git','diff','--cached','--name-only'],text=True).splitlines()) == set(FILES)
    for path, expected in FILES.items():
        assert blob(Path(path).read_bytes()) == expected, path
    assert semantic(old_model) == semantic(Path('scripts/merge_gate_model.py').read_bytes())
    assert all(Path(p).read_bytes() == data for p, data in unchanged.items())
    subprocess.run([sys.executable, '-m', 'py_compile', 'scripts/merge_gate_model.py'], check=True)
    subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
    result = subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-p','test_merge_gate_model.py','-v'],capture_output=True,text=True,timeout=300)
    (OUT/'model-tests.log').write_text(result.stdout + result.stderr)
    print(result.stdout + result.stderr)
    assert result.returncode == 0, 'model controls failed'
    (OUT/'candidate.patch').write_bytes(patch)
    manifest = {'base':BASE,'patch_sha256':PATCH,'files':{}}
    for path, expected in FILES.items():
        data = Path(path).read_bytes(); dest = OUT/'files'/path; dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        manifest['files'][path] = {'git_blob':expected,'sha256':hashlib.sha256(data).hexdigest()}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))

def publish():
    manifest = json.loads((OUT/'manifest.json').read_text())
    assert manifest['base'] == BASE and set(manifest['files']) == set(FILES)
    for path, expected in FILES.items():
        data = (OUT/'files'/path).read_bytes(); assert blob(data) == expected
        request = urllib.request.Request('https://api.github.com/repos/Chris0Jeky/agent-harness/git/blobs',data=json.dumps({'content':base64.b64encode(data).decode(),'encoding':'base64'}).encode(),headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(request,timeout=30) as response: actual=json.load(response)['sha']
        assert actual == expected
        print(path,actual)

if __name__ == '__main__':
    {'build':build,'publish':publish}[sys.argv[1]]()
