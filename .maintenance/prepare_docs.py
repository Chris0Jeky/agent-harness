"""One-time hash-bound documentation construction; never writes refs or PRs."""
from pathlib import Path
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

EXPECTED = {'BLUEPRINT.md':'da7579759e8d9f3472778865709a60cfc4140ec4','BOOK.md':'95949b1a542117b37deeb1bfbc95f53de9b7dd2f','SPECS.md':'b27767656197d724a3bb1c4ae61bababc69c54c7','FLOOR_LIMITATIONS.md':'fe85bbf4440076a0daedae501b151801e0fe2a4f','README.md':'35b27f282060f30f34ae84fb534b4f7a6084bad7','CLAUDE.md':'ee4be02216f271862b8c59f40b4dc088a131135b','MIGRATION_PROMPT.md':'48616b2760eefaf83a58c53c109363db9c29bf19'}
OUTPUT = {'BLUEPRINT.md':'614f130e28bf7a4e61e9f354b7f32c5ec1c4c39','BOOK.md':'959d87d6def95b56b9b07605d5c0399039473964','SPECS.md':'8f503f7e4d359cb2d53f12560aa2b8c2c714b50','FLOOR_LIMITATIONS.md':'f029f53c8d1502e7e90d954a6ecf6c6d232e9a0','README.md':'c4d36885b767292ec9af3b8c9a474e730382fa97','CLAUDE.md':'74c33c8b0f42dc47c7b3b8e2eb4603045c302e7','MIGRATION_PROMPT.md':'47257567bc777750704a4293c95d5a683582b1a6'}
REPO = 'Chris0Jeky/agent-harness'

def blob(data):
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()

def replace_once(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)

def build():
    text = {}
    for name, sha in EXPECTED.items():
        data = Path(name).read_bytes()
        assert blob(data) == sha, name
        text[name] = data.decode('utf-8')
    bp = text['BLUEPRINT.md']
    start = bp.index('11. **Every loop terminates.**')
    end = bp.index('\n---\n', start)
    old_principle_tail = bp[start:end].strip()
    old_floor = bp[bp.index('**FEATURE-FROZEN (2026-07-26'):bp.index('\n---\n', bp.index('**FEATURE-FROZEN (2026-07-26'))].strip()
    old_migration = bp[bp.index('## 8. Estate migration map'):bp.index('\n---\n', bp.index('## 8. Estate migration map'))].strip()
    new_tail = '''11. **Every loop terminates.** Review and termination are defined by global laws 2 and 11,
    not a separate local round count. See [SPECS §1](./SPECS.md#1-global-laws--pointer-not-a-mirror)
    for the canonical source and `review-and-ship` for the operational procedure.
12. **Mission first.** Global law 12 defines mission scope; global law 11 defines termination.
    No new gates whose subject is other gates or doc consistency. The existing grandfathered
    set remains: already-built gates, §3 stale-map stamps, the T3 docs-stamp/budget lane,
    §7 vendor parity-diffs and SPECS §7 stop-hook states. The Gardener may propose retiring
    gates whose upkeep exceeds what they catch. Closeouts retain the finished / parked /
    rounds-used scoreboard described in §9; this is not a new review gate.
'''
    bp = bp[:start] + new_tail + bp[end:]
    section_start = bp.index('## 0. The Twelve Laws (cross-cutting, all tiers)')
    section_end = bp.index('\n---\n', section_start)
    section = bp[section_start:section_end]
    new_section = '''## 0. Design principles P1-P12 (cross-cutting, all tiers)

`P1` through `P12` name this blueprint's design principles, not another global law set.
Global laws are canonical in claude-config; [SPECS §1](./SPECS.md#1-global-laws--pointer-not-a-mirror)
identifies their source. Use `P<N>` or `global law <N>` explicitly in operational text.
Historical records using `BLUEPRINT law N` retain their original numbering as `PN`;
those records are not new operational instructions.

'''
    blocks = list(re.finditer(r'(?m)^(\d+)\. \*\*([^\n]+?)\.\*\* (.*?)(?=^\d+\. \*\*|\Z)', section, re.S))
    assert [int(m[1]) for m in blocks] == list(range(1, 13))
    for m in blocks:
        content = re.sub(r'(?m)^ {3,4}', '', m[3]).strip()
        new_section += f'### P{m[1]}. {m[2]}\n\n{content}\n\n'
    bp = bp[:section_start] + new_section.rstrip() + '\n' + bp[section_end:]
    bp = replace_once(bp, 'Last Updated: 2026-07-26', 'Last Updated: 2026-10-03')
    bp = replace_once(bp, '## 2. The Floor (the only thing that never varies)', '## 2. The floor: analyzer contract, posture and wiring')
    bp = replace_once(bp, 'with identical policy\nat every tier and explicit runtime adapters, protecting only the IRREVERSIBLE — wherever it is\nwired.', 'with a shared analyzer\nand explicit runtime adapters. Effective rendering depends on posture, tier and overlays;\nwiring is declared separately. The invariant is the bounded analyzer contract, not an\nidentical runtime refusal at every tier. The floor addresses the IRREVERSIBLE wherever it is\nwired.')
    new_floor = '''### Current posture and feature freeze

The default below T4/`wave_mode` for a non-sensitive repository is `floor_posture: core`.
Destructive deletes outside the project, secret-file mutation, downloaded program text run
directly and privilege elevation remain double-checks (`FLOOR_ACK`); force-push, ref deletion,
git-config execution, work-loss and launcher verdicts proceed. A `sensitive_data` repository
never runs `core`: a declared `core` renders as `guide`. T4, `wave_mode` and the default
sensitive posture retain walls; an eligible repository can declare `guide` or `wall`.
SPECS §5.4 defines precedence and rendering, including guide's opacity handling. The analyzer
and SPECS §6 charter matrix are unchanged. A repository declaring `floor_wiring: none` has
no client-floor runtime claim.

**FEATURE-FROZEN.** Only false-positive fixes that blocked real work, the ratified #21 slice
sequence, and repairs to a SPECS §6 charter regression as literally written may change
`dispatch.py`. A newly discovered bypass family is recorded in
[FLOOR_LIMITATIONS.md](./FLOOR_LIMITATIONS.md), not implemented. The owner-authorized
Developer Lens exact-route publication contract is the separately ratified, bounded
exception; it does not reopen general parser work. Permitted source fixes may merge and bump
`FLOOR_VERSION`, but no new version is deployed until the currently deployed one is re-trusted
and canaried. Current operator gates live in [HUMAN_TODO.md](./HUMAN_TODO.md); a source merge
is not permission to run `sync-global --apply` or refresh consumer markers.

The dated measurements and decisions behind these rules are preserved verbatim in
[BOOK's historical appendix](./BOOK.md#historical-blueprint-records-preserved-2026-10-03).
They are provenance, not a report of current installations or a second active plan.
'''
    bp = replace_once(bp, old_floor, new_floor.rstrip())
    new_migration = '''## 8. Estate migration routing

The original July estate migration sequence is preserved in
[BOOK's historical appendix](./BOOK.md#historical-blueprint-records-preserved-2026-10-03).
It is a historical plan, not current instructions to mutate those repositories, and moving it
here does not mark any step complete.

For current work, inspect the target repository's declared authority and live issue/PR state.
Use the existing tracker rather than creating a parallel plan (P9). This repository's
[ROADMAP.md](./ROADMAP.md) and [plans/ACTIVE.md](./plans/ACTIVE.md) carry current work routing;
[HUMAN_TODO.md](./HUMAN_TODO.md) carries operator-only gates. Executable CLI behavior is in
[README.md](./README.md) and SPECS §9. No estate-wide migration or runtime activation is
implied by these pointers.
'''
    bp = replace_once(bp, old_migration, new_migration.rstrip())
    for old, new in {
        "(law 2's independent review)":"(global law 2's independent review)",
        '(law 9 starts here)':'(P9 starts here)',
        'then ship or park (law 11)':'then ship or park (global law 11; P11)',
        "law 11's ceiling binds here too":"global law 11's ceiling binds here too",
        "removal (law\n7's":"removal (global law\n7's",
        'tripwire by law 5':'tripwire by P5',
        'pipeline — law 11 in executable form':'pipeline — global laws 2 and 11 in executable form',
        'CLAUDE.md (law 5 + the Working-style section)':'CLAUDE.md (global law 5 + the Working-style section)',
        'comment loop (law 11)':'comment loop (global law 11; P11)',
        'the twelve laws, tier ladder':'the twelve global laws, tier ladder',
        'Law 12 quarantines meta-work':'Global law 12 and P12 quarantine meta-work',
        'The law-12 scoreboard':'The P12 scoreboard',
    }.items():
        bp = replace_once(bp, old, new)
    text['BLUEPRINT.md'] = bp
    spec = replace_once(text['SPECS.md'], 'Last Updated: 2026-07-26', 'Last Updated: 2026-10-03')
    spec = replace_once(spec, '''from laws 2f/2g, and the drift misled a review (issue #358), so law 8 pruned it. A "global law N"
or "CLAUDE.md law N" pointer means law N of that file; a bare "law N" in BLUEPRINT.md means
BLUEPRINT §0's own twelve laws, which are numbered differently.''', '''from global laws 2f/2g, and the drift misled a review (issue #358), so global law 8 pruned it.
A `global law N` or `CLAUDE.md law N` pointer means law N of that canonical file.
BLUEPRINT §0 uses the separate design-principle namespace `P1` through `P12`.
Operational references must name the namespace; there is no default meaning for a bare
`law N`. Historical `BLUEPRINT law N` citations mean the correspondingly numbered `PN`.
Review and termination remain canonical in global laws 2 and 11; P11 points there rather
than defining another review-round count.''')
    for old, new in {
        '(law 9; `dispatch.load_tier`':'(global law 9; `dispatch.load_tier`',
        "; law 7's `$WT_PROJECT_DIR/<name>`":"; global law 7's `$WT_PROJECT_DIR/<name>`",
        'why law 7 mandates':'why global law 7 mandates',
        'BLUEPRINT law 12':'BLUEPRINT P12',
        'that has a home (law 2)':'that has a home (BLUEPRINT P2)',
        'Global CLAUDE.md (law 5 + Working style)':'Global CLAUDE.md (global law 5 + Working style)',
        'plus BLUEPRINT law 11':'plus BLUEPRINT P11',
        'law it executes — one review round':'contract it executes — one review round',
        'law 2g; a manual':'global law 2g; a manual',
        'step, law 2f)':'step, global law 2f)',
    }.items():
        spec = replace_once(spec, old, new)
    text['SPECS.md'] = spec
    floor = text['FLOOR_LIMITATIONS.md']
    for old, new in {'BLUEPRINT law 5':'BLUEPRINT P5','(laws 3/4)':'(BLUEPRINT P3/P4)',"leans on law 7's":"leans on global law 7's"}.items():
        floor = replace_once(floor, old, new)
    text['FLOOR_LIMITATIONS.md'] = floor
    book = text['BOOK.md'] + '''\n\n---

## Historical blueprint records (preserved 2026-10-03)

The following blocks are copied verbatim from BLUEPRINT at main commit
`4bef9337a4d03dba329c07d007c650f628e0785a` during the #389 structure cleanup.
They preserve dated rationale and the original migration proposal. Their statements about
installed state, issue state, future work and timing are historical, not fresh verification.
Their imperative wording is quoted source material, not authorization to execute it now.
For current rules use [BLUEPRINT](./BLUEPRINT.md), the canonical global laws identified in
[SPECS §1](./SPECS.md#1-global-laws--pointer-not-a-mirror), and the current tracker/operator gates.
Old BLUEPRINT-law numbers map to the P1-P12 design-principle namespace; global-law numbering
is unchanged. No migration step is accepted or completed by this move.

### Original review and mission rationale

```text
''' + old_principle_tail + '''\n```

### Dated floor decisions and measurements

```text
''' + old_floor + '''\n```

### Original estate migration proposal

```text
''' + old_migration + '''\n```
'''
    text['BOOK.md'] = book
    text['README.md'] = replace_once(text['README.md'], 'The law: tier ladder (T0 tombstone → T4 live wire), the twelve laws, regions, the Gardener loop, model/effort routing, estate migration map', 'The policy: tier ladder (T0 tombstone → T4 live wire), design principles P1-P12, regions, the Gardener loop, model/effort routing, current migration pointers')
    text['CLAUDE.md'] = replace_once(text['CLAUDE.md'], 'the twelve laws', 'design principles P1-P12')
    pm = replace_once(text['MIGRATION_PROMPT.md'], 'Last Updated: 2026-07-26', 'Last Updated: 2026-10-03')
    for old, new in {
        'the tier ladder and twelve laws':'the tier ladder and design principles P1-P12',
        'BLUEPRINT laws 2/3/4':'BLUEPRINT principles P2/P3/P4',
        'bounded per BLUEPRINT law 11 — one review round + one fix round':'bounded per global laws 2 and 11; BLUEPRINT P11 points to that contract',
    }.items():
        pm = replace_once(pm, old, new)
    text['MIGRATION_PROMPT.md'] = pm
    assert len(re.findall(r'^### P\d+\.', bp, re.M)) == 12
    assert 'The Twelve Laws' not in bp
    assert 'No new gates whose subject is other gates or doc consistency.' in bp
    for historical in (old_principle_tail, old_floor, old_migration):
        assert book.count(historical) == 1
        assert historical not in bp
    for name, value in text.items():
        data = value.encode('utf-8')
        assert blob(data) == OUTPUT[name], (name, blob(data))
        Path(name).write_bytes(data)
    subprocess.run(['git', 'diff', '--check'], check=True)
    assert set(subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines()) == set(OUTPUT)
    print('PASS: exact source/candidate hashes; twelve principles; three verbatim history blocks; no-new-gate clause; seven-file scope; diff check')


def request(url, data=None):
    headers = {'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=40)

def publish():
    assert os.environ['GITHUB_REPOSITORY'] == REPO
    for name, sha in OUTPUT.items():
        data = Path(name).read_bytes()
        assert blob(data) == sha
        payload = json.dumps({'encoding':'base64','content':base64.b64encode(data).decode()}).encode()
        with request(f'https://api.github.com/repos/{REPO}/git/blobs', payload) as response:
            result = json.load(response)
        assert result['sha'] == sha
        print('BLOB', name, sha, flush=True)

def diagnostics():
    for job in (111101788848, 111104156577):
        with request(f'https://api.github.com/repos/{REPO}/actions/jobs/{job}/logs') as response:
            data = response.read(8_000_000)
        lines = data.decode('utf-8', errors='replace').splitlines()
        selected = set()
        for i, line in enumerate(lines):
            if any(marker in line for marker in ('FAIL:', 'ERROR:', 'Traceback (', 'AssertionError:', 'FAILED (', 'Ran ', 'git log -1')):
                selected.update(range(max(0, i-1), min(len(lines), i+9)))
        print(f'JOB {job}; log_sha256={hashlib.sha256(data).hexdigest()}; total_lines={len(lines)}')
        for i in sorted(selected):
            print(f'{i+1}: {lines[i]}')

if __name__ == '__main__':
    {'build':build,'publish':publish,'diagnostics':diagnostics}[sys.argv[1]]()
