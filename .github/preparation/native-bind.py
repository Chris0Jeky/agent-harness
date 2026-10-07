"""Disposable native Linux proof, run only in a private mount namespace."""
import importlib.util
import io
import pathlib
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


baseline = load('baseline_harness', sys.argv[1])
candidate = load('candidate_harness', sys.argv[2])
with tempfile.TemporaryDirectory(prefix='harness-bind-proof-') as raw:
    root = pathlib.Path(raw).resolve()
    left, right = root / 'codex-skills/alpha', root / 'claude/skills/beta'
    left.mkdir(parents=True)
    right.mkdir(parents=True)
    (left / 'SKILL.md').write_text('previous', encoding='utf-8')
    for relative in ('codex/skills/alpha', 'skills/beta'):
        source = root / 'config' / relative
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text(relative, encoding='utf-8')
    subprocess.run(['mount', '--bind', str(left), str(right)], check=True, timeout=10)
    try:
        assert left.samefile(right) and not left.parent.samefile(right.parent)
        baseline.preflight_selected_skill_roots([left, right], None, [], 'native')
        print('BASELINE: actual bind-mounted target collision was missed', flush=True)
        before = candidate.tree_digest(root)
        args = SimpleNamespace(config_root=str(root/'config'), codex_home=str(root/'codex'), claude_home=str(root/'claude'), skills_home=str(root/'codex-skills'), only=['skill:alpha','claude-skill:beta'], apply=False)
        for apply in (False, True):
            args.apply = apply
            with patch.object(candidate, 'reserve_backup_root') as reserve, patch.object(candidate.shutil, 'copytree') as copy:
                try:
                    with redirect_stdout(io.StringIO()):
                        candidate.sync_global(args)
                except candidate.HarnessError as error:
                    assert 'selected skill roots collide' in str(error), error
                else:
                    raise AssertionError('aliased destinations were admitted')
                reserve.assert_not_called()
                copy.assert_not_called()
            assert candidate.tree_digest(root) == before
            print('CANDIDATE: native collision refused before backup/copy, apply=', apply, flush=True)
    finally:
        subprocess.run(['umount', str(right)], check=True, timeout=10)
print('Native fixture unmounted and removed.', flush=True)
