#!/usr/bin/env python3
"""Replay real agent shell commands through the deny floor to measure false positives.

WHY THIS EXISTS
---------------
Issue #21 measured floor v1.5.4 refusing 11.91% of 63,668 unique commands replayed
from this machine's own Claude and Codex transcripts. That number is the entire
evidence base for the floor redesign — and the script that produced it was never
checked in, so nobody (including the author) can reproduce or re-run it against a
new floor version. Every subsequent slice therefore has to argue its false-positive
delta from intuition.

This script is that missing instrument. It extracts every shell command the agents
actually ran, replays each one through `dispatch.check()` offline, and reports:

  * block rate per tier, for two `dispatch.py` versions side by side;
  * the two deltas that decide a merge — **newly blocked** (baseline allowed,
    candidate refuses: a regression / new false positive) and **newly allowed**
    (baseline refused, candidate allows: a relaxation needing security review);
  * blocks grouped by deny reason, reproducing issue #21's block-class table.

PRIVACY
-------
The corpus is real work: repository paths, branch names, occasionally a token
pasted into a command. stdout therefore only ever carries reason strings and
`--top N` command samples truncated to `--sample-width` characters. Full command
text is written only to `--json` / `--corpus-cache`, which belong in a scratch
directory outside any repository. Nothing is copied out of the transcript trees.

COVERAGE LIMITS (read before quoting a number)
----------------------------------------------
* Every command is replayed with the same `--project-dir` (this repo by default),
  not the directory it originally ran in. Rules keyed on "inside/outside the
  project" therefore judge a synthetic cwd. Baseline and candidate see the same
  synthetic cwd, so the *deltas* are sound; the absolute rate is an approximation.
* The replay spawns no subprocess and touches no network. `check()` accepts a
  `remote_resolver` and it is stubbed to "private"; it has no comparable hook
  for the `git config --get-regexp remote.*` read behind a refspec-less
  `git push`, so the `command_runner` defaults inside the loaded module are
  rebound to a stub that returns `""` (see `make_module_offline`). Without that,
  every such push spawns two real `git.exe` processes per version, the verdict
  depends on `--project-dir`'s actual git config, and a transient slow spawn on
  one side of the comparison alone can manufacture a phantom delta row. The run
  reports how many reads the stub answered.
* The whole ambient `GIT_*` family plus `EDITOR` / `VISUAL` / `PAGER` /
  `SSH_ASKPASS` is cleared for the duration of the run, because `check()` reads
  all of them from `os.environ` and any one of them turns a verdict into a
  property of the host. This is not hypothetical: a plain `GIT_EDITOR=true` in
  the shell moved a 1.5.3-vs-1.6.0 run's baseline blocked-unique from 11,496 to
  11,739. `HOME` / `USERPROFILE` / `XDG_CONFIG_HOME` are deliberately kept —
  the floor resolves `~` and home-root comparisons through them. The run prints
  the names (never the values) of everything it cleared.
* Only the model's own tool-call records are read (`function_call` /
  `custom_tool_call` for Codex, `tool_use` for Claude). Codex's `event_msg`
  `exec_command_end` records are skipped on purpose: they are the runtime's
  post-execution echo, carrying `["powershell.exe", "-Command", <same text>]`,
  and 6,772 of 6,775 of them cite the `call_id` of a request already counted.
  Including them would double count every command in a second wrapper form.
  `~/.codex/history.jsonl` and `~/.claude/history.jsonl` are user-prompt logs,
  not shell logs, and are not sources.
* There is no per-command watchdog: a pathological command would stall the run
  rather than being counted as a block. None has been observed.

Usage:
    py -3 scripts/replay_corpus.py --baseline <path> --candidate <path> \
        --limit 2000 --json <scratch>/replay.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing
import os
import re
import sys
from collections import Counter
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any, Iterator, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DISPATCH = REPO_ROOT / "templates" / "hooks" / "dispatch.py"
DEFAULT_TIERS = (1, 2, 3, 4)
DECISIONS = ("allow", "ask", "deny", "error")
RUNTIMES = ("codex", "claude")

# `tools.shell_command({command: "..."})` embedded in the JS body of Codex's
# `exec` custom tool. 19k+ of the corpus's shell invocations arrive this way.
# The argument brace is matched separately from the call so that a non-object
# argument (`tools.shell_command(opts)`) is *counted* rather than ignored.
EMBEDDED_CALL_RE = re.compile(r"tools\s*\.\s*shell_command\s*\(")
EMBEDDED_OPEN_BRACE_RE = re.compile(r"\s*\{")
EMBEDDED_KEY_RE = re.compile(r"""\s*(?:"command"|'command'|command)\s*:\s*""")
# What may legally follow a complete `command:` literal inside the object.
# Anything else (`+`, a template tag, a method call) means the literal was only
# one fragment of a larger expression.
EMBEDDED_TAIL_RE = re.compile(r"\s*[,}]")
JS_SIMPLE_ESCAPES = {
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
JS_HEX_RE = re.compile(r"[0-9A-Fa-f]+")
JS_LINE_TERMINATORS = "\n\r\u2028\u2029"

# Ambient variables `check()` reads straight from `os.environ`, so leaving any
# of them set makes a verdict a property of the host, not of the command.
HOST_ENV_PREFIX = "GIT_"
HOST_ENV_NAMES = frozenset({"EDITOR", "VISUAL", "PAGER", "SSH_ASKPASS"})
# Never cleared. The floor resolves `~`, home roots and `$HOME`-style references
# through these; removing them would not remove host dependence, it would make
# every path verdict wrong instead.
HOST_ENV_KEEP = frozenset(
    {"HOME", "HOMEDRIVE", "HOMEPATH", "USERPROFILE", "XDG_CONFIG_HOME"}
)


# --------------------------------------------------------------------------- #
# Corpus extraction
# --------------------------------------------------------------------------- #


def js_code_point(digits: str, width: int | None = None) -> str | None:
    """Decode one hex escape payload, or None when it is not representable.

    `int(..., 16)` accepts surrounding whitespace and a leading sign, so the
    digits are validated explicitly. Lone surrogates are refused rather than
    materialised: `chr(0xD83D)` is a str no encoder will accept, so it would
    raise `UnicodeEncodeError` on the first write hours into a run.
    """
    if width is not None and len(digits) != width:
        return None
    if not JS_HEX_RE.fullmatch(digits):
        return None
    value = int(digits, 16)
    if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
        return None
    return chr(value)


def decode_js_string_literal(text: str, start: int) -> tuple[str, int] | None:
    """Decode the JS string literal at `text[start]`; return (value, end index).

    Returns None when the literal is not decodable as a constant: an
    interpolated template literal, an unterminated literal, or an escape whose
    value cannot be recovered unambiguously. Codex writes the embedded command
    as a plain double-quoted literal in ~93% of calls; the rest are variables or
    interpolations and are counted, not guessed at.
    """
    if start >= len(text):
        return None
    quote = text[start]
    if quote not in ('"', "'", "`"):
        return None
    out: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 1
            if index >= len(text):
                return None
            escape = text[index]
            if escape == "u":
                if text[index + 1 : index + 2] == "{":
                    close = text.find("}", index + 2)
                    if close == -1:
                        return None
                    decoded = js_code_point(text[index + 2 : close])
                    if decoded is None:
                        return None
                    out.append(decoded)
                    index = close + 1
                    continue
                digits = text[index + 1 : index + 5]
                if len(digits) != 4 or not JS_HEX_RE.fullmatch(digits):
                    return None
                value = int(digits, 16)
                index += 5
                if 0xD800 <= value <= 0xDBFF:
                    # A supplementary character is written as a surrogate pair;
                    # combine it. A high surrogate with no low surrogate after
                    # it is not a character at all -> refuse the literal.
                    tail = text[index : index + 6]
                    if not tail.startswith("\\u") or not JS_HEX_RE.fullmatch(tail[2:]):
                        return None
                    low = int(tail[2:], 16)
                    if not 0xDC00 <= low <= 0xDFFF:
                        return None
                    out.append(chr(0x10000 + ((value - 0xD800) << 10) + (low - 0xDC00)))
                    index += 6
                    continue
                if 0xDC00 <= value <= 0xDFFF:
                    return None
                out.append(chr(value))
                continue
            if escape == "x":
                decoded = js_code_point(text[index + 1 : index + 3], width=2)
                if decoded is None:
                    return None
                out.append(decoded)
                index += 3
                continue
            if escape in JS_LINE_TERMINATORS:
                # LineContinuation: the terminator is elided, not emitted.
                # Emitting a newline here would manufacture a shell statement
                # separator that the agent never wrote -- exactly the class of
                # thing this corpus is used to measure.
                index += (
                    2 if escape == "\r" and text[index + 1 : index + 2] == "\n" else 1
                )
                continue
            if escape in "01234567":
                if escape == "0" and not text[index + 1 : index + 2].isdigit():
                    out.append("\0")
                    index += 1
                    continue
                # Legacy octal (`\012`): decoding it here would disagree with
                # a strict-mode runtime that rejects the literal outright.
                return None
            out.append(JS_SIMPLE_ESCAPES.get(escape, escape))
            index += 1
            continue
        if char == quote:
            return "".join(out), index + 1
        if quote == "`" and char == "$" and text[index : index + 2] == "${":
            return None  # interpolated: the real command is not in the log
        if quote != "`" and char == "\n":
            return None  # unterminated single-line literal
        out.append(char)
        index += 1
    return None


def extract_embedded_commands(source: str, stats: Counter[str]) -> list[str]:
    """Pull literal `tools.shell_command({command: "..."})` bodies out of JS.

    Every call site that cannot be reduced to a single constant string is
    counted in the unparsed ledger and dropped. Fabricating a command is far
    worse than failing to extract one: a counted failure is honest, whereas a
    plausible-but-wrong command enters the corpus as a *success* and its verdict
    is then quoted as evidence about a command no agent ever ran.
    """
    found: list[str] = []
    for match in EMBEDDED_CALL_RE.finditer(source):
        brace = EMBEDDED_OPEN_BRACE_RE.match(source, match.end())
        if brace is None:
            stats["unparsed-codex-embedded-non-object-argument"] += 1
            continue
        key = EMBEDDED_KEY_RE.match(source, brace.end())
        if key is None:
            stats["unparsed-codex-embedded-shorthand-or-reordered"] += 1
            continue
        decoded = decode_js_string_literal(source, key.end())
        if decoded is None:
            stats["unparsed-codex-embedded-non-literal-command"] += 1
            continue
        value, end = decoded
        if EMBEDDED_TAIL_RE.match(source, end) is None:
            # `{command: "@'\n" + script + "\n'@ | python -"}`: the literal is
            # one fragment of a concatenation, so the decoded text is not the
            # command. Without this check the corpus gains `@'\n` as a
            # three-character "success".
            stats["unparsed-codex-embedded-concatenated"] += 1
            continue
        found.append(value)
    return found


def iter_jsonl(path: Path, stats: Counter[str]) -> Iterator[dict[str, Any]]:
    """Yield each JSON object in a transcript, counting what will not parse."""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        stats["unparsed-file-unreadable"] += 1
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                stats["unparsed-line-not-json"] += 1
                continue
            if not isinstance(record, dict):
                stats["unparsed-line-not-object"] += 1
                continue
            yield record


def extract_codex_commands(
    root: Path,
    stats: Counter[str],
    include_embedded: bool = True,
) -> Iterator[str]:
    """Yield every shell command Codex requested, oldest rollout first.

    Two channels carry them: the `shell_command` function call (arguments are a
    JSON string) and the `exec` custom tool, whose input is a JS program that
    calls `tools.shell_command(...)` inline.
    """
    for path in sorted(root.rglob("*.jsonl")):
        stats["extracted-codex-files"] += 1
        for record in iter_jsonl(path, stats):
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            kind = payload.get("type")
            name = payload.get("name")
            if kind == "function_call" and name == "shell_command":
                raw = payload.get("arguments")
                if not isinstance(raw, str):
                    stats["unparsed-codex-arguments-not-string"] += 1
                    continue
                try:
                    arguments = json.loads(raw)
                except ValueError:
                    stats["unparsed-codex-arguments-not-json"] += 1
                    continue
                if not isinstance(arguments, dict):
                    stats["unparsed-codex-arguments-not-object"] += 1
                    continue
                command = arguments.get("command")
                if not isinstance(command, str):
                    stats["unparsed-codex-command-not-string"] += 1
                    continue
                stats["extracted-codex-invocations-function-call"] += 1
                yield command
            elif kind == "custom_tool_call" and name == "exec":
                source = payload.get("input")
                if not isinstance(source, str):
                    stats["unparsed-codex-exec-input-not-string"] += 1
                    continue
                if not include_embedded:
                    stats["extracted-codex-exec-calls-excluded-by-flag"] += 1
                    continue
                for command in extract_embedded_commands(source, stats):
                    stats["extracted-codex-invocations-embedded"] += 1
                    yield command


def extract_claude_commands(root: Path, stats: Counter[str]) -> Iterator[str]:
    """Yield every command Claude's Bash/PowerShell tools were asked to run."""
    for path in sorted(root.rglob("*.jsonl")):
        stats["extracted-claude-files"] += 1
        for record in iter_jsonl(path, stats):
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                continue
            if not isinstance(content, list):
                if content is not None:
                    stats["unparsed-claude-content-not-list"] += 1
                continue
            for block in content:
                if not isinstance(block, dict):
                    stats["unparsed-claude-block-not-object"] += 1
                    continue
                if block.get("type") != "tool_use":
                    continue
                if block.get("name") not in ("Bash", "PowerShell"):
                    continue
                tool_input = block.get("input")
                if not isinstance(tool_input, dict):
                    stats["unparsed-claude-input-not-object"] += 1
                    continue
                command = tool_input.get("command")
                if not isinstance(command, str):
                    stats["unparsed-claude-command-not-string"] += 1
                    continue
                stats["extracted-claude-invocations"] += 1
                yield command


def build_corpus(
    codex_root: Path | None,
    claude_root: Path | None,
    include_embedded: bool = True,
) -> tuple[dict[str, dict[str, int]], Counter[str]]:
    """Return {command: {runtime: invocations}} plus a parse-failure ledger."""
    stats: Counter[str] = Counter()
    corpus: dict[str, dict[str, int]] = {}
    sources: list[tuple[str, Iterator[str]]] = []
    if codex_root is not None and codex_root.is_dir():
        sources.append(
            ("codex", extract_codex_commands(codex_root, stats, include_embedded))
        )
    elif codex_root is not None:
        stats["unparsed-codex-root-missing"] += 1
    if claude_root is not None and claude_root.is_dir():
        sources.append(("claude", extract_claude_commands(claude_root, stats)))
    elif claude_root is not None:
        stats["unparsed-claude-root-missing"] += 1
    for runtime, stream in sources:
        for command in stream:
            entry = corpus.get(command)
            if entry is None:
                entry = {name: 0 for name in RUNTIMES}
                corpus[command] = entry
            entry[runtime] += 1
    return corpus, stats


def save_corpus(path: Path, corpus: dict[str, dict[str, int]]) -> None:
    """Write the corpus as JSONL. Contains raw commands: scratch dirs only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for command, counts in corpus.items():
            row = {"command": command}
            row.update(counts)
            handle.write(json.dumps(row) + "\n")


def load_corpus(path: Path) -> dict[str, dict[str, int]]:
    corpus: dict[str, dict[str, int]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            command = row.get("command")
            if not isinstance(command, str):
                continue
            corpus[command] = {name: int(row.get(name, 0)) for name in RUNTIMES}
    return corpus


def select_commands(
    corpus: dict[str, dict[str, int]],
    limit: int | None,
    max_chars: int,
) -> tuple[list[str], Counter[str]]:
    """Drop over-long commands, then take a deterministic sample of `limit`.

    The sample is the `limit` commands with the smallest SHA-1 digest — uniform
    over the corpus (unlike "first N", which would be biased by scan order) and
    stable across runs, so a smoke run and a full run of the same corpus agree
    on which commands they share.
    """
    notes: Counter[str] = Counter()
    kept = []
    for command in corpus:
        if len(command) > max_chars:
            notes["skipped-over-max-chars"] += 1
            continue
        kept.append(command)
    if limit is not None and limit < len(kept):
        kept.sort(key=lambda text: hashlib.sha1(text.encode("utf-8")).digest())
        kept = kept[:limit]
        notes["sampled"] += len(kept)
    return kept, notes


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #


def load_dispatch(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dispatch module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stub_resolver(
    args: Sequence[str],
    project_dir: str,
    git_globals: Any = None,
    command_runner: Any = None,
    deadline: Any = None,
) -> tuple[bool, str]:
    """Keep the network out of the replay; treat every remote as private."""
    return False, "corpus-replay-stub-private"


# Incremented by `stub_command_runner`; reported so the run can prove how many
# subprocesses it did NOT spawn. Per-process under `spawn`, so it is returned
# with each chunk rather than read from the parent.
_OFFLINE_READS: dict[str, int] = {"count": 0}


def stub_command_runner(
    argv: Sequence[str],
    cwd: str = "",
    timeout: Any = None,
) -> str:
    """Stand in for `dispatch.command_output`: resolve nothing, spawn nothing.

    `""` is exactly what the real `command_output` returns when the subprocess
    fails, and every caller documents that as "unresolved -> not dangerous", so
    the replay's verdict matches a checkout with no `remote.<name>.push`,
    `.mirror` or `.receivepack` configured. That is a fixed, stated premise
    instead of whatever the host's git config happens to say today.
    """
    _OFFLINE_READS["count"] += 1
    return ""


class OfflineSubprocess:
    """Proxy that lets a replayed dispatch module see `subprocess`, not use it.

    Belt and braces behind `make_module_offline`: if a future floor version
    grows a spawn site the default rebinding does not cover, this turns it into
    a loud `error` verdict in the report instead of a silent, host-dependent,
    non-deterministic result.
    """

    _BLOCKED = frozenset(
        {
            "run",
            "Popen",
            "call",
            "check_call",
            "check_output",
            "getoutput",
            "getstatusoutput",
        }
    )

    def __init__(self, real: ModuleType) -> None:
        self._real = real

    def __getattr__(self, name: str) -> Any:
        if name in OfflineSubprocess._BLOCKED:
            raise RuntimeError(
                f"corpus replay is offline but dispatch called subprocess.{name}"
            )
        return getattr(self._real, name)


def make_module_offline(module: ModuleType) -> int:
    """Rebind `command_runner` defaults to the stub; return how many were found.

    `check()` takes no `command_runner` parameter, so it cannot simply be passed
    one the way `remote_resolver` is: it calls
    `configured_bare_push_is_dangerous(cwd, git_globals, deadline=...)` and that
    function's `command_runner` default was bound to the real `command_output`
    object when the module was defined. Assigning `module.command_output`
    afterwards therefore does NOT change it — the already-captured default is
    what runs. The defaults are rewritten in place instead, which is the
    smallest change that makes the offline claim true without touching
    `dispatch.py` (T4-class shared infrastructure) to add an injection point.

    Raises when nothing was rebound: a floor version that no longer matches this
    shape must fail loudly rather than quietly resume spawning `git config`.
    """
    real = getattr(module, "command_output", None)
    if real is None:
        raise RuntimeError(f"{module.__name__} has no command_output to stub")
    patched = 0
    for name in dir(module):
        function = getattr(module, name, None)
        if not isinstance(function, FunctionType):
            continue
        defaults = function.__defaults__
        if defaults:
            code = function.__code__
            names = code.co_varnames[: code.co_argcount]
            first = code.co_argcount - len(defaults)
            replaced = list(defaults)
            changed = False
            for offset, value in enumerate(defaults):
                if names[first + offset] == "command_runner" and value is real:
                    replaced[offset] = stub_command_runner
                    changed = True
            if changed:
                function.__defaults__ = tuple(replaced)
                patched += 1
        keyword_defaults = function.__kwdefaults__
        if keyword_defaults and keyword_defaults.get("command_runner") is real:
            keyword_defaults["command_runner"] = stub_command_runner
            patched += 1
    if not patched:
        raise RuntimeError(
            f"{module.__name__}: no command_runner default bound to command_output; "
            "the replay cannot prove it is offline"
        )
    # Any direct call site, plus a hard stop on every other spawn route.
    module.command_output = stub_command_runner
    if isinstance(getattr(module, "subprocess", None), ModuleType):
        module.subprocess = OfflineSubprocess(module.subprocess)
    return patched


def declared_env_names(modules: Sequence[ModuleType]) -> set[str]:
    """Env-var names a loaded floor version declares that it inspects.

    Harvested from the module's own `_GIT_*_ENVIRONMENT` registries so that a
    future version reading a variable this script has never heard of is still
    neutralised, rather than silently reintroducing host dependence.
    """
    names: set[str] = set()
    for module in modules:
        for attr, value in vars(module).items():
            if "ENVIRONMENT" not in attr.upper():
                continue
            if isinstance(value, (set, frozenset)):
                names |= {item.upper() for item in value if isinstance(item, str)}
    return names - HOST_ENV_KEEP


def clear_host_git_env(modules: Sequence[ModuleType] = ()) -> dict[str, str]:
    """Remove every ambient variable `check()` reads; return it for restoration.

    `check()` reads the live environment in a dozen places, not just the
    `GIT_CONFIG_*` family: `GIT_INDEX_FILE`, the whole `GIT_TRACE*` family,
    `GIT_DIR` / `GIT_WORK_TREE` / `GIT_COMMON_DIR`, the process-launching
    `GIT_ASKPASS` / `GIT_EDITOR` / `GIT_SSH_COMMAND` / ... set, and plain
    `EDITOR` / `VISUAL` / `PAGER` / `SSH_ASKPASS`. Any of them can turn a verdict
    into a property of the machine: with `GIT_EDITOR=true` merely set in the
    shell, a 1.5.3-vs-1.6.0 run denied ~243 commands purely because of the host
    (baseline blocked-unique 11,739 vs 11,496 cleared). The deltas survived that
    time, which was luck, not design.
    """
    declared = declared_env_names(modules)
    removed = {
        name: value
        for name, value in os.environ.items()
        if name.upper().startswith(HOST_ENV_PREFIX)
        or name.upper() in HOST_ENV_NAMES
        or name.upper() in declared
    }
    for name in removed:
        del os.environ[name]
    return removed


def decide(
    module: ModuleType,
    command: str,
    tier: int,
    project_dir: str,
) -> tuple[str, str]:
    """Return (decision, reason); an exception inside `check()` is its own class."""
    try:
        decision, reason = module.check(
            command,
            {"tier": tier, "flags": {}},
            project_dir,
            project_dir,
            remote_resolver=stub_resolver,
        )
    except Exception as error:  # noqa: BLE001 - a crash is a result, not a stop
        return "error", f"{type(error).__name__}: {error}".strip()
    if decision not in DECISIONS:
        return "error", f"unexpected decision {decision!r}"
    return decision, str(reason)


_WORKER: dict[str, Any] = {}


def _worker_init(
    baseline_path: str,
    candidate_path: str,
    tiers: Sequence[int],
    project_dir: str,
) -> None:
    # Cleared before the modules load, then again with what they declare they
    # read. Workers are forked/spawned copies, so the parent's clearing does not
    # reach them under `spawn`; they never restore, they exit.
    clear_host_git_env()
    baseline = load_dispatch("replay_baseline", Path(baseline_path))
    candidate = load_dispatch("replay_candidate", Path(candidate_path))
    clear_host_git_env((baseline, candidate))
    make_module_offline(baseline)
    make_module_offline(candidate)
    _WORKER["baseline"] = baseline
    _WORKER["candidate"] = candidate
    _WORKER["tiers"] = tuple(tiers)
    _WORKER["project_dir"] = project_dir


def _worker_run(
    chunk: list[tuple[int, str]],
) -> tuple[list[tuple[int, list, list]], int]:
    tiers = _WORKER["tiers"]
    project_dir = _WORKER["project_dir"]
    baseline = _WORKER["baseline"]
    candidate = _WORKER["candidate"]
    before = _OFFLINE_READS["count"]
    results = []
    for index, command in chunk:
        base = [decide(baseline, command, tier, project_dir) for tier in tiers]
        cand = [decide(candidate, command, tier, project_dir) for tier in tiers]
        results.append((index, base, cand))
    return results, _OFFLINE_READS["count"] - before


def replay(
    commands: Sequence[str],
    baseline_path: Path,
    candidate_path: Path,
    tiers: Sequence[int],
    project_dir: str,
    jobs: int,
    progress: bool,
) -> tuple[list[list[tuple[str, str]]], list[list[tuple[str, str]]], int]:
    """Return (baseline, candidate) verdicts indexed [command][tier], and the
    number of git-config reads the offline stub answered instead of spawning."""
    total = len(commands)
    baseline_out: list[Any] = [None] * total
    candidate_out: list[Any] = [None] * total
    chunks = [
        [(index, commands[index]) for index in range(start, min(start + 128, total))]
        for start in range(0, total, 128)
    ]
    done = 0
    offline_reads = 0
    if jobs > 1:
        context = multiprocessing.get_context("spawn")
        pool = context.Pool(
            processes=jobs,
            initializer=_worker_init,
            initargs=(
                str(baseline_path),
                str(candidate_path),
                tuple(tiers),
                project_dir,
            ),
        )
        with pool:
            for batch, reads in pool.imap_unordered(_worker_run, chunks, chunksize=1):
                for index, base, cand in batch:
                    baseline_out[index] = base
                    candidate_out[index] = cand
                offline_reads += reads
                done += len(batch)
                if progress:
                    report_progress(done, total)
    else:
        _worker_init(str(baseline_path), str(candidate_path), tiers, project_dir)
        for chunk in chunks:
            batch, reads = _worker_run(chunk)
            for index, base, cand in batch:
                baseline_out[index] = base
                candidate_out[index] = cand
            offline_reads += reads
            done += len(chunk)
            if progress:
                report_progress(done, total)
    return baseline_out, candidate_out, offline_reads


def report_progress(done: int, total: int) -> None:
    sys.stderr.write(f"\r  replayed {done}/{total} commands")
    sys.stderr.flush()
    if done >= total:
        sys.stderr.write("\n")


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #


def invocations(counts: dict[str, int]) -> int:
    return sum(counts.values())


def summarize_tier(
    commands: Sequence[str],
    corpus: dict[str, dict[str, int]],
    verdicts: Sequence[Sequence[tuple[str, str]]],
    tier_index: int,
) -> dict[str, Any]:
    """Block rate plus deny-reason classes for one version at one tier."""
    decisions: Counter[str] = Counter()
    decision_invocations: Counter[str] = Counter()
    by_runtime: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    reason_invocations: Counter[str] = Counter()
    for position, command in enumerate(commands):
        decision, reason = verdicts[position][tier_index]
        counts = corpus[command]
        weight = invocations(counts)
        decisions[decision] += 1
        decision_invocations[decision] += weight
        if decision != "allow":
            reasons[reason] += 1
            reason_invocations[reason] += weight
            for runtime in RUNTIMES:
                if counts.get(runtime):
                    by_runtime[runtime] += 1
    total = len(commands)
    blocked = total - decisions["allow"]
    total_invocations = sum(decision_invocations.values())
    blocked_invocations = total_invocations - decision_invocations["allow"]
    return {
        "unique_commands": total,
        "unique_blocked": blocked,
        "unique_block_rate": (blocked / total) if total else 0.0,
        "invocations": total_invocations,
        "invocations_blocked": blocked_invocations,
        "invocation_block_rate": (
            (blocked_invocations / total_invocations) if total_invocations else 0.0
        ),
        "decisions": dict(decisions),
        "decision_invocations": dict(decision_invocations),
        "blocked_unique_by_runtime": dict(by_runtime),
        "reasons": [
            {
                "reason": reason,
                "unique": count,
                "invocations": reason_invocations[reason],
            }
            for reason, count in reasons.most_common()
        ],
    }


def compare_tier(
    commands: Sequence[str],
    corpus: dict[str, dict[str, int]],
    baseline: Sequence[Sequence[tuple[str, str]]],
    candidate: Sequence[Sequence[tuple[str, str]]],
    tier_index: int,
    top: int,
) -> dict[str, Any]:
    """Newly-blocked / newly-allowed deltas plus the full transition matrix.

    `reclassified` matters when reading the block-class tables side by side: a
    rule whose count grows in the candidate has not necessarily started blocking
    anything new — it may have inherited commands another rule used to claim.
    """
    matrix: Counter[str] = Counter()
    reclassified: Counter[str] = Counter()
    newly_blocked: list[dict[str, Any]] = []
    newly_allowed: list[dict[str, Any]] = []
    for position, command in enumerate(commands):
        base_decision, base_reason = baseline[position][tier_index]
        cand_decision, cand_reason = candidate[position][tier_index]
        matrix[f"{base_decision}->{cand_decision}"] += 1
        if base_decision == cand_decision:
            if base_decision != "allow" and base_reason != cand_reason:
                reclassified[f"{base_reason}  =>  {cand_reason}"] += 1
            continue
        weight = invocations(corpus[command])
        if base_decision == "allow" and cand_decision != "allow":
            newly_blocked.append(
                {
                    "command": command,
                    "invocations": weight,
                    "decision": cand_decision,
                    "reason": cand_reason,
                }
            )
        elif base_decision != "allow" and cand_decision == "allow":
            newly_allowed.append(
                {
                    "command": command,
                    "invocations": weight,
                    "was": base_decision,
                    "reason": base_reason,
                }
            )
    newly_blocked.sort(key=lambda row: (-row["invocations"], row["command"]))
    newly_allowed.sort(key=lambda row: (-row["invocations"], row["command"]))
    return {
        "transitions": dict(matrix),
        "reclassified_unique": sum(reclassified.values()),
        "reclassified_top": reclassified.most_common(top),
        "newly_blocked_unique": len(newly_blocked),
        "newly_blocked_invocations": sum(r["invocations"] for r in newly_blocked),
        "newly_allowed_unique": len(newly_allowed),
        "newly_allowed_invocations": sum(r["invocations"] for r in newly_allowed),
        "newly_blocked_reasons": dict(
            Counter(row["reason"] for row in newly_blocked).most_common()
        ),
        "newly_allowed_reasons": dict(
            Counter(row["reason"] for row in newly_allowed).most_common()
        ),
        "newly_blocked_top": newly_blocked[:top],
        "newly_allowed_top": newly_allowed[:top],
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def clip(text: str, width: int) -> str:
    """One-line, width-bounded rendering: stdout never carries a whole command.

    Commands really do contain emoji, and a Windows console is cp1252, so the
    text is forced through the stream's own encoding first: a report that dies
    with `UnicodeEncodeError` after an hour of replay loses the whole run.
    """
    flat = " ".join(text.split())
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        flat = flat.encode(encoding, "replace").decode(encoding, "replace")
    except (LookupError, UnicodeError):  # pragma: no cover - exotic stream
        flat = flat.encode("ascii", "replace").decode("ascii")
    if len(flat) <= width:
        return flat
    return flat[: width - 3] + "..."


def print_report(result: dict[str, Any], top: int, width: int) -> None:
    corpus = result["corpus"]
    baseline = result["baseline"]
    candidate = result["candidate"]
    print("=" * 78)
    print("deny-floor corpus replay")
    print("=" * 78)
    print(f"baseline  : floor {baseline['version']}  {baseline['path']}")
    print(f"candidate : floor {candidate['version']}  {candidate['path']}")
    print(f"project   : {result['project_dir']}")
    cleared = result["run"].get("cleared_host_env") or []
    print(
        "host env  : cleared "
        + (", ".join(cleared) if cleared else "(nothing relevant was set)")
    )
    print(
        f"offline   : {result['run'].get('offline_git_config_reads', 0)} git-config "
        "reads answered by the stub (0 subprocesses spawned)"
    )
    print()
    print("corpus")
    print("-" * 78)
    print(
        f"  unique commands extracted : {corpus['unique_total']}"
        f"  ({corpus['invocations_total']} invocations)"
    )
    for runtime in RUNTIMES:
        print(
            f"    {runtime:<7}: {corpus['unique_by_runtime'][runtime]:>7} unique"
            f"  {corpus['invocations_by_runtime'][runtime]:>7} invocations"
        )
    print(f"    shared : {corpus['unique_shared']:>7} unique (seen in both runtimes)")
    print(f"  replayed                  : {corpus['unique_replayed']}")
    if corpus["notes"]:
        for key, value in sorted(corpus["notes"].items()):
            print(f"    note {key}: {value}")
    print(f"  source                    : {corpus['source']}")
    print("  extraction ledger:")
    for key, value in sorted(corpus["extracted"].items()):
        print(f"    {key[len('extracted-'):]}: {value}")
    print("  entries that could NOT be parsed / extracted:")
    unparsed = corpus["unparsed"]
    if not unparsed:
        print(
            "    (none)"
            if corpus["source"] == "transcript-scan"
            else "    (not measured: this run reused a cached corpus)"
        )
    for key, value in sorted(unparsed.items()):
        print(f"    {key[len('unparsed-'):]}: {value}")
    print()
    print("block rate by tier (unique commands)")
    print("-" * 78)
    header = (
        f"  {'tier':<5}{'baseline':>18}{'candidate':>18}"
        f"{'new blocks':>13}{'new allows':>13}"
    )
    print(header)
    for tier_key in result["tier_order"]:
        base = result["tiers"][tier_key]["baseline"]
        cand = result["tiers"][tier_key]["candidate"]
        delta = result["tiers"][tier_key]["delta"]
        print(
            f"  T{tier_key:<4}"
            f"{base['unique_blocked']:>8} {base['unique_block_rate'] * 100:>8.2f}%"
            f"{cand['unique_blocked']:>8} {cand['unique_block_rate'] * 100:>8.2f}%"
            f"{delta['newly_blocked_unique']:>13}{delta['newly_allowed_unique']:>13}"
        )
    print()
    for tier_key in result["tier_order"]:
        tier = result["tiers"][tier_key]
        print("=" * 78)
        print(f"tier {tier_key}")
        print("-" * 78)
        for label in ("baseline", "candidate"):
            summary = tier[label]
            decisions = summary["decisions"]
            print(
                f"  {label:<10} deny={decisions.get('deny', 0)} "
                f"ask={decisions.get('ask', 0)} "
                f"error={decisions.get('error', 0)} "
                f"allow={decisions.get('allow', 0)}  "
                f"blocked invocations={summary['invocations_blocked']}"
                f" / {summary['invocations']}"
                f" ({summary['invocation_block_rate'] * 100:.2f}%)"
            )
            runtimes = summary["blocked_unique_by_runtime"]
            print(
                "             blocked unique by runtime: "
                + ", ".join(f"{name}={runtimes.get(name, 0)}" for name in RUNTIMES)
            )
        print()
        print(f"  top block classes ({result['candidate']['version']}, candidate):")
        print(f"    {'unique':>7} {'invocs':>7}  reason")
        for row in tier["candidate"]["reasons"][:top]:
            print(
                f"    {row['unique']:>7} {row['invocations']:>7}  "
                f"{clip(row['reason'], width)}"
            )
        print()
        print(f"  top block classes ({result['baseline']['version']}, baseline):")
        print(f"    {'unique':>7} {'invocs':>7}  reason")
        for row in tier["baseline"]["reasons"][:top]:
            print(
                f"    {row['unique']:>7} {row['invocations']:>7}  "
                f"{clip(row['reason'], width)}"
            )
        delta = tier["delta"]
        print()
        print(
            f"  NEWLY BLOCKED (baseline allow -> candidate block): "
            f"{delta['newly_blocked_unique']} unique / "
            f"{delta['newly_blocked_invocations']} invocations"
        )
        for row in delta["newly_blocked_top"]:
            print(
                f"    [{row['invocations']:>4}x {row['decision']}] "
                f"{clip(row['command'], width)}"
            )
            print(f"           reason: {clip(row['reason'], width)}")
        print(
            f"  NEWLY ALLOWED (baseline block -> candidate allow): "
            f"{delta['newly_allowed_unique']} unique / "
            f"{delta['newly_allowed_invocations']} invocations"
        )
        for row in delta["newly_allowed_top"]:
            print(
                f"    [{row['invocations']:>4}x was {row['was']}] "
                f"{clip(row['command'], width)}"
            )
            print(f"           was: {clip(row['reason'], width)}")
        other = {
            key: value
            for key, value in delta["transitions"].items()
            if key.split("->")[0] != key.split("->")[1]
            and not (key.startswith("allow->") or key.endswith("->allow"))
        }
        if other:
            print(f"  other transitions: {other}")
        if delta["reclassified_unique"]:
            print(
                f"  RECLASSIFIED (still blocked, different rule): "
                f"{delta['reclassified_unique']} unique"
            )
            for pair, count in delta["reclassified_top"]:
                print(f"    {count:>6}  {clip(pair, width)}")
        print()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def default_codex_root() -> Path:
    home = os.environ.get("CODEX_HOME")
    base = Path(home) if home else Path.home() / ".codex"
    return base / "sessions"


def default_claude_root() -> Path:
    return Path.home() / ".claude" / "projects"


def module_version(module: ModuleType) -> str:
    return str(getattr(module, "FLOOR_VERSION", "unknown"))


def file_sha256(path: Path) -> str:
    """Pin exactly which bytes produced a number, for later reproduction."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay real agent shell commands through two dispatch.py versions "
            "and report block rates, deltas and deny-reason classes."
        )
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_DISPATCH,
        help="dispatch.py to treat as the current floor (default: this repo's)",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=DEFAULT_DISPATCH,
        help="dispatch.py to treat as the proposed floor",
    )
    parser.add_argument(
        "--tier",
        type=int,
        action="append",
        dest="tiers",
        choices=[0, 1, 2, 3, 4],
        help="tier to replay (repeatable; default 1 2 3 4)",
    )
    parser.add_argument("--limit", type=int, help="replay a deterministic sample only")
    parser.add_argument(
        "--max-command-chars",
        type=int,
        default=20000,
        help="skip commands longer than this (default 20000, as in issue #21)",
    )
    parser.add_argument("--top", type=int, default=15, help="rows per table")
    parser.add_argument(
        "--sample-width",
        type=int,
        default=160,
        help="stdout truncation width for command/reason samples",
    )
    parser.add_argument(
        "--json",
        type=Path,
        dest="json_path",
        help="write the full result (including untruncated commands) here",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="worker processes (default 1; each loads both dispatch modules)",
    )
    parser.add_argument("--codex-root", type=Path, default=default_codex_root())
    parser.add_argument("--claude-root", type=Path, default=default_claude_root())
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=REPO_ROOT,
        help="project/cwd every command is judged against (see module docstring)",
    )
    parser.add_argument(
        "--corpus-cache",
        type=Path,
        help="write the extracted corpus here (raw commands: scratch dirs only)",
    )
    parser.add_argument(
        "--from-corpus",
        type=Path,
        help="load a previously written corpus instead of rescanning transcripts",
    )
    parser.add_argument(
        "--no-embedded",
        action="store_true",
        help="ignore commands embedded in Codex `exec` JS (issue #21 parity)",
    )
    parser.add_argument("--quiet", action="store_true", help="no progress on stderr")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tiers = sorted(set(args.tiers)) if args.tiers else list(DEFAULT_TIERS)
    progress = not args.quiet

    if args.from_corpus:
        corpus = load_corpus(args.from_corpus)
        stats: Counter[str] = Counter(
            {"extracted-loaded-from-corpus-file": len(corpus)}
        )
    else:
        if progress:
            sys.stderr.write("scanning transcripts...\n")
        corpus, stats = build_corpus(
            args.codex_root, args.claude_root, not args.no_embedded
        )
    if not corpus:
        sys.stderr.write("no commands extracted; nothing to replay\n")
        return 1
    if args.corpus_cache:
        save_corpus(args.corpus_cache, corpus)

    unique_by_runtime = {name: 0 for name in RUNTIMES}
    invocations_by_runtime = {name: 0 for name in RUNTIMES}
    shared = 0
    for counts in corpus.values():
        present = 0
        for name in RUNTIMES:
            if counts.get(name):
                unique_by_runtime[name] += 1
                present += 1
            invocations_by_runtime[name] += counts.get(name, 0)
        if present > 1:
            shared += 1

    commands, notes = select_commands(corpus, args.limit, args.max_command_chars)
    if not commands:
        sys.stderr.write("every command was filtered out; nothing to replay\n")
        return 1

    baseline_module = load_dispatch("replay_baseline_probe", args.baseline)
    candidate_module = load_dispatch("replay_candidate_probe", args.candidate)
    baseline_version = module_version(baseline_module)
    candidate_version = module_version(candidate_module)

    injected = clear_host_git_env((baseline_module, candidate_module))
    if injected and progress:
        sys.stderr.write(
            "cleared host environment that would otherwise change verdicts: "
            + ", ".join(sorted(injected))
            + "\n"
        )
    try:
        baseline_verdicts, candidate_verdicts, offline_reads = replay(
            commands,
            args.baseline,
            args.candidate,
            tiers,
            str(args.project_dir),
            max(1, args.jobs),
            progress,
        )
    finally:
        os.environ.update(injected)

    result: dict[str, Any] = {
        "baseline": {
            "path": str(args.baseline),
            "version": baseline_version,
            "sha256": file_sha256(args.baseline),
        },
        "candidate": {
            "path": str(args.candidate),
            "version": candidate_version,
            "sha256": file_sha256(args.candidate),
        },
        "project_dir": str(args.project_dir),
        "tier_order": tiers,
        "run": {
            "limit": args.limit,
            "max_command_chars": args.max_command_chars,
            "jobs": max(1, args.jobs),
            "embedded_codex_exec_included": not args.no_embedded,
            "offline_git_config_reads": offline_reads,
            "cleared_host_env": sorted(injected),
        },
        "corpus": {
            "source": (
                f"cached-corpus {args.from_corpus}"
                if args.from_corpus
                else "transcript-scan"
            ),
            "unique_total": len(corpus),
            "invocations_total": sum(invocations(c) for c in corpus.values()),
            "unique_by_runtime": unique_by_runtime,
            "invocations_by_runtime": invocations_by_runtime,
            "unique_shared": shared,
            "unique_replayed": len(commands),
            "notes": dict(notes),
            "extracted": {
                key: value
                for key, value in stats.items()
                if key.startswith("extracted-")
            },
            "unparsed": {
                key: value
                for key, value in stats.items()
                if key.startswith("unparsed-")
            },
        },
        "tiers": {},
    }
    for tier_index, tier in enumerate(tiers):
        result["tiers"][tier] = {
            "baseline": summarize_tier(commands, corpus, baseline_verdicts, tier_index),
            "candidate": summarize_tier(
                commands, corpus, candidate_verdicts, tier_index
            ),
            "delta": compare_tier(
                commands,
                corpus,
                baseline_verdicts,
                candidate_verdicts,
                tier_index,
                args.top,
            ),
        }
    print_report(result, args.top, args.sample_width)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        sys.stderr.write(
            f"wrote {args.json_path} (contains untruncated command text)\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
