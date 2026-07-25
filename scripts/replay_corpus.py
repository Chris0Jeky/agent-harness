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

EXIT CODES
----------
0 clean; 1 nothing to replay; 2 at least one command made `check()` raise in
one of the two versions; 3 the replay *itself* failed. 2 is not cosmetic: an
exception becomes an `error` decision, `error` counts as blocked, and the two
allow-edge buckets then move in opposite unsafe directions — NEWLY ALLOWED is
inflated and NEWLY BLOCKED is suppressed to zero. `--allow-errors` downgrades it
to a report for a deliberate crash census.

3 is the separate, more fundamental failure and has no opt-out: the instrument
could not obtain a verdict, so there is nothing to census. Those commands get
the `toolfail` pseudo-decision, which is in no rate and in no delta bucket.

TOOL-SIDE FAILURE MUST NEVER READ AS POLICY
-------------------------------------------
Issue #39 reported floor 1.2.0 "blocking 100% of the corpus". It blocked
nothing: 1.2.0's `check()` is `(command, tier_cfg, project_dir)` and this script
called the current five-argument form, so every command raised `TypeError`, and
an exception counts as blocked. The verdict-shaped output of a broken tool was
read as a policy measurement.

The invocation is therefore derived from each loaded module's own
`inspect.signature` (`build_check_caller`) and bound per version, so a baseline
several minor versions old replays with the arguments it declares. If no binding
exists the run aborts with exit 3 before replaying anything, rather than
counting a per-command `TypeError`.

The rest of that audit, and what each failure is now counted as:

* `check()` raised -> `error` decision (still blocked), `EXIT_ERRORS_PRESENT`.
  Pre-existing; unchanged.
* the offline guard fired (`OfflineSubprocess`, a floor version spawning a
  subprocess the stub does not cover) -> `toolfail`, exit 3. It used to be an
  `error`, i.e. a block.
* a chunk came back with no verdict under `--jobs > 1` -> the run aborts with
  exit 3 instead of failing inside `summarize_tier` on a `None`.
* an unreadable transcript file, a mid-file read error, or a transcript tree
  that cannot be walked -> counted in the extraction ledger under
  `file-unreadable` / `file-read-error` / `transcript-tree-unwalkable` and
  printed, instead of silently shortening the corpus.
* there is still no per-command watchdog, so a timeout cannot be counted as a
  block — nothing times out. The floor's own `_remote_deadline` fail-opens to
  `""` ("unresolved -> not dangerous"), and the replay stubs every reader it
  guards anyway, so it cannot produce a deny either.

PRIVACY
-------
The corpus is real work: repository paths, branch names, occasionally a token
pasted into a command. stdout therefore only ever carries reason strings and
`--top N` command samples truncated to `--sample-width` characters. Full command
text is written only to `--json` / `--corpus-cache`, which belong in a scratch
directory outside any repository. Nothing is copied out of the transcript trees.

That makes `--json` the only place a reviewer can audit the whole of a delta,
so every bucket is written there untruncated as `<bucket>_all` (`--top` stays a
stdout display limit). A gate that reports "1,674 newly allowed commands need
security review" has to be able to produce all 1,674.

"Reason strings" is not automatically safe: several deny reasons interpolate
command-derived text — `Redirecting output into a secret-looking file ({path})`,
`Mutating a secret-looking file ({path})`, `{head} can launch an uninspected
child command`, `rm -rf outside the project: {path}` — so an unfiltered class
table preferentially prints the names of the `.env` / `id_rsa` / `*.pem` /
`credentials.json` files in real transcripts. `normalize_reason` replaces those
interpolations with placeholders before grouping, which also fixes a real
accounting bug: grouped by the raw string, the secret-file class fragments into
one row per path and the table understates it. Deltas are unaffected either way.

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
* A run measures one overlay combination. `tier.json` carries flags as well as a
  tier (`sensitive_data`, `wave_mode`, `dormant_production`,
  `relaxed_work_loss_guards`) and the floor keys real branches on them —
  `strict = tier >= 4 or wave_mode` turns the work-loss guards into denies, and
  `sensitive_data` adds the public-remote push denies. With no `--flag`, every
  row describes a repo whose flags are all false, which is not what
  `hq-private` (`sensitive_data`) or `wealthlens-hq`
  (`relaxed_work_loss_guards`) run. Measured at T2 on this corpus,
  `git reset --hard HEAD~1`, `git push` and `git checkout -- .` are allow with
  no flags and deny under `wave_mode`. Pass `--flag` per overlay the gated repo
  declares; the active set is printed in the header, labels every tier row, and
  is recorded in the JSON `run` block.
* Only the model's own tool-call records are read (`function_call` /
  `custom_tool_call` for Codex, `tool_use` for Claude). Codex's `event_msg`
  `exec_command_end` records are skipped on purpose: they are the runtime's
  post-execution echo, carrying `["powershell.exe", "-Command", <same text>]`,
  and 6,772 of 6,775 of them cite the `call_id` of a request already counted.
  Including them would double count every command in a second wrapper form.
  `~/.codex/history.jsonl` and `~/.claude/history.jsonl` are user-prompt logs,
  not shell logs, and are not sources.
* There is no per-command watchdog: a pathological command would stall the run
  rather than being counted as a block. None has been observed. This is the
  deliberate direction — a stalled run is visible, a command counted as blocked
  because it was slow is not.
* Commands longer than `--max-command-chars` are dropped before replay and are
  in no rate reported anywhere. Long commands skew blocked (nested
  scriptblocks, heredocs, dynamic tokens), so the exclusion biases the absolute
  rate downward — the unsafe direction for a gate. 4 of 80,891 unique commands
  on the current corpus, so immaterial today; the count is printed with the
  block-rate table rather than only in the corpus notes.

Usage:
    py -3 scripts/replay_corpus.py --baseline <path> --candidate <path> \
        --limit 2000 --json <scratch>/replay.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import multiprocessing
import os
import re
import sys
from collections import Counter
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any, Callable, Iterator, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DISPATCH = REPO_ROOT / "templates" / "hooks" / "dispatch.py"
DEFAULT_TIERS = (1, 2, 3, 4)
DECISIONS = ("allow", "ask", "deny", "error")
# Not a decision any floor can return: the replay harness itself failed to obtain
# a verdict for this command (its offline guard fired, or the loaded module's
# `check()` could not be invoked). Kept out of `DECISIONS` so a floor returning
# the literal string is still rejected as unexpected, and kept out of every rate
# so a broken instrument can never read as a strict policy.
TOOLFAIL = "toolfail"
RUNTIMES = ("codex", "claude")
# Tier overlays a repo may declare in `tier.json` (SPECS §2). The floor branches
# on these, so a row measured without them describes a repo none of the estate
# actually is. `choices` on `--flag` rejects a typo instead of quietly measuring
# the no-overlay case under an overlay's name.
OVERLAY_FLAGS = (
    "sensitive_data",
    "wave_mode",
    "dormant_production",
    "relaxed_work_loss_guards",
)
# Exit code when a replayed version raised inside `check()`. Distinct from 1
# ("nothing to replay") so a caller can tell an unusable corpus from an
# unusable comparison.
EXIT_ERRORS_PRESENT = 2
# Exit code when the *instrument* failed on at least one command: the offline
# guard fired, or `check()` could not be invoked. Distinct from 2, which reports
# a floor that crashed on its own terms. Not suppressible by `--allow-errors`:
# `--allow-errors` exists to census floor crashes, and a malfunctioning harness
# is not a census of anything.
EXIT_TOOL_FAILURE = 3

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

# Codex function calls that carry a shell command. `shell` is the pre-2026
# spelling and passes an argv list instead of a command string.
CODEX_SHELL_CALL_NAMES = frozenset({"shell_command", "shell"})
POSIX_SHELL_NAMES = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})
POWERSHELL_NAMES = frozenset({"powershell", "pwsh"})
CMD_SHELL_NAMES = frozenset({"cmd"})
POSIX_SHELL_FLAG_RE = re.compile(r"-[a-z]*c", re.IGNORECASE)
EXECUTABLE_SUFFIX_RE = re.compile(r"\.(?:exe|cmd|bat|com)$", re.IGNORECASE)
# Tokens that need no quoting in any shell, so joining them cannot invent syntax.
PLAIN_ARGV_TOKEN_RE = re.compile(r"[A-Za-z0-9_@%+=:,./-]+")


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


def argv_basename(token: str) -> str:
    """`C:\\Windows\\powershell.exe` -> `powershell`."""
    tail = token.replace("\\", "/").rsplit("/", 1)[-1]
    return EXECUTABLE_SUFFIX_RE.sub("", tail).lower()


def command_from_argv(argv: Sequence[Any]) -> str | None:
    """Recover the command line behind a legacy Codex `shell` argv, or None.

    The pre-`shell_command` function call carries an argv list --
    `["powershell.exe", "-NoLogo", "-Command", "<script>"]` -- rather than a
    command string. `check()` inspects a shell command line, so the faithful
    replay subject is the script the wrapper hands to the shell; that is the
    same reading the module docstring already applies to `exec_command_end`.

    An argv that is not a recognised wrapper is joined only when every token is
    unambiguous without quoting (`["git", "status"]`). Anything else returns
    None and is counted by the caller: a mis-quoted join would invent a command
    line that no shell ever saw.
    """
    tokens = [token for token in argv if isinstance(token, str)]
    if not tokens or len(tokens) != len(argv):
        return None
    base = argv_basename(tokens[0])
    for index in range(1, len(tokens)):
        flag = tokens[index].lower()
        rest = tokens[index + 1 :]
        if base in POSIX_SHELL_NAMES and POSIX_SHELL_FLAG_RE.fullmatch(flag):
            # Operands after the script become $0/$1..., not part of it.
            return rest[0] if rest else None
        if base in POWERSHELL_NAMES and len(flag) > 1 and "-command".startswith(flag):
            # PowerShell joins everything after -Command with single spaces.
            return " ".join(rest) if rest else None
        if base in CMD_SHELL_NAMES and flag in {"/c", "/k"}:
            return " ".join(rest) if rest else None
    if all(PLAIN_ARGV_TOKEN_RE.fullmatch(token) for token in tokens):
        return " ".join(tokens)
    return None


def iter_transcripts(root: Path, stats: Counter[str]) -> list[Path]:
    """List a transcript tree's `*.jsonl`, counting a walk that cannot complete.

    `Path.rglob` raises straight out of the generator on an unreadable directory
    (a locked profile subtree, a stale junction), which would silently truncate
    the corpus mid-walk if it were consumed lazily inside a `for`. Materialising
    it here turns that into one counted, reported ledger entry instead of a
    corpus whose size depends on which directories happened to be readable.
    """
    try:
        return sorted(root.rglob("*.jsonl"))
    except OSError:
        stats["unparsed-transcript-tree-unwalkable"] += 1
        return []


def iter_jsonl(path: Path, stats: Counter[str]) -> Iterator[dict[str, Any]]:
    """Yield each JSON object in a transcript, counting what will not parse."""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        stats["unparsed-file-unreadable"] += 1
        return
    with handle:
        while True:
            # `for line in handle` would let a mid-file read error escape as an
            # uncaught OSError, killing a multi-hour run; and swallowing it
            # without a count would silently shorten the corpus. Neither is a
            # measurement, so the truncation is counted and reported.
            try:
                line = next(handle, None)
            except (OSError, UnicodeError):
                stats["unparsed-file-read-error"] += 1
                return
            if line is None:
                return
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

    Three channels carry them: the `shell_command` function call (arguments are
    a JSON string), the older `shell` function call (same wrapper, but
    `arguments.command` is an argv *list*), and the `exec` custom tool, whose
    input is a JS program that calls `tools.shell_command(...)` inline.
    A full inventory of this machine's transcripts finds no fourth channel:
    every other `function_call` / `custom_tool_call` name is an MCP or planning
    tool, and no `js_repl` body contains a `tools.shell_command(` call.
    """
    for path in iter_transcripts(root, stats):
        stats["extracted-codex-files"] += 1
        for record in iter_jsonl(path, stats):
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            kind = payload.get("type")
            name = payload.get("name")
            if kind == "function_call" and name in CODEX_SHELL_CALL_NAMES:
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
                if isinstance(command, list):
                    recovered = command_from_argv(command)
                    if recovered is None:
                        stats["unparsed-codex-legacy-shell-argv-not-recoverable"] += 1
                        continue
                    stats["extracted-codex-invocations-legacy-shell"] += 1
                    yield recovered
                    continue
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
    for path in iter_transcripts(root, stats):
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


class ReplayHarnessError(RuntimeError):
    """The instrument failed, so this command has no verdict.

    Never a policy result. Anything raised as one of these is bucketed as
    `toolfail`, excluded from every rate, and aborts the run — as opposed to a
    plain exception out of `check()`, which is the *floor* crashing and is
    reported as an `error` decision (see `EXIT_ERRORS_PRESENT`).
    """


class CheckSignatureError(ReplayHarnessError):
    """A loaded floor's `check()` cannot be invoked by this replay at all."""


# Every argument the replay knows how to supply, and the parameter names a
# floor version has used for it. Floors older than the `remote_resolver`
# parameter take `(command, tier_cfg, project_dir)` and nothing else (issue
# #39); the current one takes eleven parameters. Binding by *role* rather than
# by a fixed arity is what lets one instrument measure both.
CHECK_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "command": ("command", "command_line", "cmd"),
    "tier_cfg": ("tier_cfg", "tier_config", "cfg", "config"),
    "project_dir": ("project_dir", "project_root", "project"),
    "command_cwd": ("command_cwd", "cwd"),
    "remote_resolver": ("remote_resolver",),
}
CHECK_ROLE_BY_NAME = {
    name: role for role, names in CHECK_ROLE_ALIASES.items() for name in names
}
# Without these three there is no meaningful replay subject; the rest are
# supplied only when the loaded version declares them.
CHECK_REQUIRED_ROLES = ("command", "tier_cfg", "project_dir")


def plan_check_call(
    signature: inspect.Signature,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Decide how to call one floor's `check()`; raise if it cannot be called.

    Returns `(positional_roles, keyword_bindings)`. The rule is deliberately
    conservative in the loud direction: a parameter the replay does not know how
    to supply is left to its default, and if it *has* no default the plan is
    refused outright rather than guessed at. A wrong guess would be recorded as
    a per-command exception, and `decide()` turns an exception into a blocked
    verdict — which is precisely how "floor 1.2.0 blocks 100%" was manufactured.
    """
    positional: list[str] = []
    keyword: list[tuple[str, str]] = []
    filled: set[str] = set()
    # Set once a parameter is skipped: everything after it must be passed by
    # keyword, and a positional-only parameter after it cannot be passed at all.
    positional_closed = False
    for name, param in signature.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        role = CHECK_ROLE_BY_NAME.get(name)
        if role is None or role in filled:
            if param.default is param.empty:
                raise CheckSignatureError(
                    f"check() requires a parameter the replay cannot supply: {name!r}"
                )
            if param.kind is not param.KEYWORD_ONLY:
                positional_closed = True
            continue
        if param.kind is param.POSITIONAL_ONLY:
            if positional_closed:
                raise CheckSignatureError(
                    f"check() takes {name!r} positionally after a parameter the "
                    "replay cannot supply, so it cannot be bound"
                )
            positional.append(role)
        elif param.kind is param.POSITIONAL_OR_KEYWORD and not positional_closed:
            positional.append(role)
        else:
            keyword.append((name, role))
        filled.add(role)
    missing = [role for role in CHECK_REQUIRED_ROLES if role not in filled]
    if missing:
        raise CheckSignatureError(
            "check() declares no parameter for " + ", ".join(missing)
        )
    return positional, keyword


def build_check_caller(module: ModuleType) -> Callable[[str, dict, str], Any]:
    """Return `(command, tier_cfg, project_dir) -> check(...)` for this module.

    The call shape is derived from the module's own `inspect.signature`, so a
    baseline several minor versions old replays with the arguments *it* declares
    instead of the arguments today's floor declares. Raises `CheckSignatureError`
    when no binding exists; the caller aborts the run rather than letting every
    command read as blocked.
    """
    check = getattr(module, "check", None)
    if not callable(check):
        raise CheckSignatureError(f"{module.__name__} has no callable check()")
    try:
        signature = inspect.signature(check)
    except (TypeError, ValueError) as error:  # pragma: no cover - exotic callable
        raise CheckSignatureError(
            f"{module.__name__}: check() signature is not introspectable: {error}"
        ) from error
    positional, keyword = plan_check_call(signature)

    def call(command: str, tier_cfg: dict, project_dir: str) -> Any:
        values = {
            "command": command,
            "tier_cfg": tier_cfg,
            "project_dir": project_dir,
            "command_cwd": project_dir,
            "remote_resolver": stub_resolver,
        }
        return check(
            *(values[role] for role in positional),
            **{name: values[role] for name, role in keyword},
        )

    # Prove the plan binds before an hour of replay depends on it. A signature
    # that survives `plan_check_call` but not `bind` would otherwise raise once
    # per command and be counted as a block.
    try:
        signature.bind(
            *(f"<{role}>" for role in positional),
            **{name: f"<{role}>" for name, role in keyword},
        )
    except TypeError as error:
        raise CheckSignatureError(
            f"{module.__name__}: check() cannot be bound by the replay: {error}"
        ) from error
    call.replay_bound_parameters = [  # type: ignore[attr-defined]
        *positional,
        *(f"{name}={role}" for name, role in keyword),
    ]
    return call


_CHECK_CALLERS: dict[Any, Callable[[str, dict, str], Any]] = {}


def check_caller(module: ModuleType) -> Callable[[str, dict, str], Any]:
    """Memoised `build_check_caller`; `inspect.signature` is not free per call."""
    check = getattr(module, "check", None)
    try:
        cached = _CHECK_CALLERS.get(check)
    except TypeError:  # pragma: no cover - unhashable callable
        return build_check_caller(module)
    if cached is None:
        cached = build_check_caller(module)
        _CHECK_CALLERS[check] = cached
    return cached


def describe_check_signature(module: ModuleType) -> list[str]:
    """The argument roles this replay binds on a module, for the JSON record."""
    return list(getattr(check_caller(module), "replay_bound_parameters", []))


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
            raise ReplayHarnessError(
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
    flags: dict[str, bool] | None = None,
) -> tuple[str, str]:
    """Return (decision, reason); an exception inside `check()` is its own class.

    `flags` is the tier-overlay set (`wave_mode`, `sensitive_data`, ...) exactly
    as `tier.json` would declare it. A fresh dict is handed to every call so a
    floor version that normalises its config in place cannot leak state from one
    command into the next.

    Three outcomes, kept apart on purpose:

    * a decision the floor returned -> that decision;
    * an exception out of `check()` -> `error`, i.e. *the floor crashed*. It
      still counts as blocked (`EXIT_ERRORS_PRESENT` aborts the run so the
      corrupted deltas are never quoted);
    * a `ReplayHarnessError` -> `toolfail`, i.e. *this script* failed. It is in
      no rate and in no allow-edge bucket, because a broken instrument reading
      as a strict floor is exactly the artifact issue #39 mistook for policy.

    The call itself is shaped from the module's own signature, so a baseline
    predating `command_cwd` / `remote_resolver` is invoked with the arguments it
    declares rather than raising `TypeError` on every single command.
    """
    caller = check_caller(module)
    try:
        decision, reason = caller(
            command,
            {"tier": tier, "flags": dict(flags or {})},
            project_dir,
        )
    except ReplayHarnessError as error:
        return TOOLFAIL, f"{type(error).__name__}: {error}".strip()
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
    flags: dict[str, bool] | None = None,
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
    # Fail here, once, rather than once per command: an unbindable `check()`
    # raised per command would be caught by `decide()` and counted, and the run
    # would print a plausible-looking 100% block rate for the unusable version.
    check_caller(baseline)
    check_caller(candidate)
    _WORKER["baseline"] = baseline
    _WORKER["candidate"] = candidate
    _WORKER["tiers"] = tuple(tiers)
    _WORKER["project_dir"] = project_dir
    _WORKER["flags"] = dict(flags or {})


def _worker_run(
    chunk: list[tuple[int, str]],
) -> tuple[list[tuple[int, list, list]], int]:
    tiers = _WORKER["tiers"]
    project_dir = _WORKER["project_dir"]
    flags = _WORKER["flags"]
    baseline = _WORKER["baseline"]
    candidate = _WORKER["candidate"]
    before = _OFFLINE_READS["count"]
    results = []
    for index, command in chunk:
        base = [decide(baseline, command, tier, project_dir, flags) for tier in tiers]
        cand = [decide(candidate, command, tier, project_dir, flags) for tier in tiers]
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
    flags: dict[str, bool] | None = None,
) -> tuple[list[list[tuple[str, str]]], list[list[tuple[str, str]]], int]:
    """Return (baseline, candidate) verdicts indexed [command][tier], and the
    number of git-config reads the offline stub answered instead of spawning."""
    overlay = dict(flags or {})
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
                overlay,
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
        _worker_init(
            str(baseline_path), str(candidate_path), tiers, project_dir, overlay
        )
        for chunk in chunks:
            batch, reads = _worker_run(chunk)
            for index, base, cand in batch:
                baseline_out[index] = base
                candidate_out[index] = cand
            offline_reads += reads
            done += len(chunk)
            if progress:
                report_progress(done, total)
    assert_every_command_replayed(baseline_out, candidate_out)
    return baseline_out, candidate_out, offline_reads


def assert_every_command_replayed(
    baseline_out: Sequence[Any], candidate_out: Sequence[Any]
) -> None:
    """Refuse to report on a replay that did not cover every command.

    A chunk that never came back — a worker killed by the OOM killer, a pool
    that lost a result — leaves `None` in these lists, and the run would then
    die deep inside `summarize_tier` with a message about unpacking a
    non-iterable. Worse, a future refactor that defaulted the gap to a verdict
    would report a partial replay as a measurement.
    """
    unfilled = sum(
        1
        for base, cand in zip(baseline_out, candidate_out)
        if base is None or cand is None
    )
    if unfilled:
        raise ReplayHarnessError(
            f"{unfilled} of {len(baseline_out)} commands came back with no "
            "verdict; the replay is incomplete and its numbers are not usable"
        )


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


# Deny reasons that interpolate command-derived text. Grouping on the raw string
# both leaks and miscounts: the secret-file class becomes one row per filename,
# so the class table understates it while printing the name of every `.env`,
# `id_rsa`, `*.pem` and `credentials.json` the corpus ever touched.
REASON_NORMALIZERS = (
    (
        re.compile(r"(?s)^(.*secret-looking file )\(.*\)( is floor-blocked.*)$"),
        r"\1(<path>)\2",
    ),
    (re.compile(r"(?s)^(Cannot safely resolve .*? target): .*$"), r"\1: <path>"),
    (re.compile(r"(?s)^(.*? outside the project): .*$"), r"\1: <path>"),
    (
        re.compile(r"(?s)^.*(: refusing a filesystem/home root\.)$"),
        r"<target>\1",
    ),
    (
        re.compile(r"(?s)^.*?( can launch an uninspected child command.*)$"),
        r"<command>\1",
    ),
    (
        re.compile(r"(?s)^(sensitive_data repo: refusing a push to public remote ).*$"),
        r"\1<remote>.",
    ),
    (
        re.compile(
            r"(?s)^(sensitive_data repo: could not verify push remote privacy )\(.*$"
        ),
        r"\1(<remote>).",
    ),
)
# Second pass, for reasons this script has not enumerated (including future ones
# and `error` verdicts carrying an exception message): mask a token only when it
# looks like a path or URL *and* occurs in the command, so the floor's own
# wording is never touched and grouping stays meaningful.
REASON_PATHISH_RE = re.compile(r"[\\/]|^\.[A-Za-z0-9]")
REASON_TOKEN_TRIM = ".,;:()[]'\"`"


def normalize_reason(reason: str, command: str = "") -> str:
    """Replace command-derived text in a deny reason with a placeholder."""
    text = reason
    for pattern, replacement in REASON_NORMALIZERS:
        text = pattern.sub(replacement, text)
    if not command:
        return text
    masked = []
    for token in text.split(" "):
        stripped = token.strip(REASON_TOKEN_TRIM)
        if (
            len(stripped) >= 4
            and stripped in command
            and REASON_PATHISH_RE.search(stripped)
        ):
            masked.append(token.replace(stripped, "<path>"))
        else:
            masked.append(token)
    return " ".join(masked)


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
    toolfail_reasons: Counter[str] = Counter()
    for position, command in enumerate(commands):
        decision, reason = verdicts[position][tier_index]
        counts = corpus[command]
        weight = invocations(counts)
        decisions[decision] += 1
        decision_invocations[decision] += weight
        if decision == TOOLFAIL:
            # The instrument failed: no verdict exists, so this command belongs
            # in no rate and in no block class. Its own ledger, its own banner.
            toolfail_reasons[normalize_reason(reason, command)] += 1
            continue
        if decision != "allow":
            grouped = normalize_reason(reason, command)
            reasons[grouped] += 1
            reason_invocations[grouped] += weight
            for runtime in RUNTIMES:
                if counts.get(runtime):
                    by_runtime[runtime] += 1
    total = len(commands)
    # Every rate below is over the commands that actually got a verdict. A
    # harness failure inflating a block rate is the artifact this instrument
    # exists to detect, so it must not be able to produce one.
    measured = total - decisions[TOOLFAIL]
    blocked = measured - decisions["allow"]
    refused = blocked - decisions["ask"]
    total_invocations = sum(decision_invocations.values()) - (
        decision_invocations[TOOLFAIL]
    )
    blocked_invocations = total_invocations - decision_invocations["allow"]
    refused_invocations = blocked_invocations - decision_invocations["ask"]
    return {
        "unique_commands": total,
        "unique_measured": measured,
        "unique_toolfail": decisions[TOOLFAIL],
        "invocations_toolfail": decision_invocations[TOOLFAIL],
        "toolfail_reasons": [
            {"reason": reason, "unique": count}
            for reason, count in toolfail_reasons.most_common()
        ],
        # "blocked" is Codex semantics: respond() converts `ask` to `deny` for
        # Codex, so every non-allow is a refusal there. For Claude an `ask` is a
        # prompt the human answers, so "refused" (deny + error) is the honest
        # Claude number and is reported alongside rather than folded in.
        "unique_blocked": blocked,
        "unique_block_rate": (blocked / measured) if measured else 0.0,
        "unique_refused": refused,
        "unique_refuse_rate": (refused / measured) if measured else 0.0,
        "unique_ask": decisions["ask"],
        "invocations": total_invocations,
        "invocations_blocked": blocked_invocations,
        "invocations_refused": refused_invocations,
        "invocation_block_rate": (
            (blocked_invocations / total_invocations) if total_invocations else 0.0
        ),
        "invocation_refuse_rate": (
            (refused_invocations / total_invocations) if total_invocations else 0.0
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
    """Bucket every decision change; the buckets partition the transitions.

    A changed verdict lands in exactly one of: newly_blocked (allow -> anything
    else), newly_allowed (anything else -> allow), ask_gained (a refusal becomes
    a prompt: a genuine relaxation for Claude, still a deny for Codex),
    ask_lost (a prompt becomes a refusal), or crash_moved (deny <-> error).
    Bucketing only the two allow-edges, as this did, left `deny -> ask` and
    `ask -> deny` in no reported bucket at all.

    A `toolfail` on either side pre-empts all of them: the harness, not the
    floor, failed on that command, so there is no transition. It goes to
    `tool_failed` and the run exits `EXIT_TOOL_FAILURE`.

    `reclassified` is a different axis — same decision, different rule — and
    matters when reading the block-class tables side by side: a rule whose count
    grows in the candidate has not necessarily started blocking anything new, it
    may have inherited commands another rule used to claim.

    Every bucket is emitted twice: `<bucket>_top` is the `--top` slice stdout
    prints, and `<bucket>_all` is the complete list. Only `_top` existed, so a
    reviewer told "1,674 relaxations need security review" could see 15 of them
    and had no supported way to enumerate the rest. `_all` carries raw command
    text and therefore only ever reaches `--json`, which the module docstring
    already restricts to a scratch directory; stdout still prints `_top`.
    """
    matrix: Counter[str] = Counter()
    reclassified: Counter[str] = Counter()
    newly_blocked: list[dict[str, Any]] = []
    newly_allowed: list[dict[str, Any]] = []
    ask_gained: list[dict[str, Any]] = []
    ask_lost: list[dict[str, Any]] = []
    crash_moved: list[dict[str, Any]] = []
    tool_failed: list[dict[str, Any]] = []
    for position, command in enumerate(commands):
        base_decision, base_reason = baseline[position][tier_index]
        cand_decision, cand_reason = candidate[position][tier_index]
        matrix[f"{base_decision}->{cand_decision}"] += 1
        if TOOLFAIL in (base_decision, cand_decision):
            # One side has no verdict, so there is no transition to classify.
            # Routing it anywhere else would report a harness malfunction as a
            # policy change: `toolfail -> allow` would read as a relaxation and
            # `allow -> toolfail` as a new false positive.
            tool_failed.append(
                {
                    "command": command,
                    "invocations": invocations(corpus[command]),
                    "was": base_decision,
                    "decision": cand_decision,
                    "reason": (
                        cand_reason if cand_decision == TOOLFAIL else base_reason
                    ),
                }
            )
            continue
        if base_decision == cand_decision:
            if base_decision != "allow" and base_reason != cand_reason:
                reclassified[
                    f"{normalize_reason(base_reason, command)}"
                    f"  =>  {normalize_reason(cand_reason, command)}"
                ] += 1
            continue
        row = {
            "command": command,
            "invocations": invocations(corpus[command]),
            "was": base_decision,
            "decision": cand_decision,
            "reason": cand_reason if cand_decision != "allow" else base_reason,
        }
        if base_decision == "allow":
            newly_blocked.append(row)
        elif cand_decision == "allow":
            newly_allowed.append(row)
        elif cand_decision == "ask":
            ask_gained.append(row)
        elif base_decision == "ask":
            ask_lost.append(row)
        else:
            crash_moved.append(row)
    buckets = {
        "newly_blocked": newly_blocked,
        "newly_allowed": newly_allowed,
        "ask_gained": ask_gained,
        "ask_lost": ask_lost,
        "crash_moved": crash_moved,
        "tool_failed": tool_failed,
    }
    result: dict[str, Any] = {
        "transitions": dict(matrix),
        "reclassified_unique": sum(reclassified.values()),
        "reclassified_top": reclassified.most_common(top),
        "reclassified_all": reclassified.most_common(),
    }
    for label, rows in buckets.items():
        rows.sort(key=lambda row: (-row["invocations"], row["command"]))
        result[f"{label}_unique"] = len(rows)
        result[f"{label}_invocations"] = sum(row["invocations"] for row in rows)
        result[f"{label}_reasons"] = dict(
            Counter(
                normalize_reason(row["reason"], row["command"]) for row in rows
            ).most_common()
        )
        result[f"{label}_top"] = rows[:top]
        result[f"{label}_all"] = rows
    return result


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


def print_rest_of_bucket(
    delta: dict[str, Any], label: str, top: int, tier_key: Any
) -> None:
    """Point at the untruncated list instead of leaving the reader with `--top`.

    stdout deliberately never carries whole commands (see PRIVACY), so the
    remainder cannot simply be printed; naming its exact JSON path is what makes
    the count auditable.
    """
    remaining = delta[f"{label}_unique"] - top
    if remaining > 0:
        print(
            f"    ... and {remaining} more; the complete list is in --json at "
            f"tiers.{tier_key}.delta.{label}_all"
        )


def tier_label(tier: Any, overlays: Sequence[str]) -> str:
    """`T2`, or `T2+wave_mode` — a rate is only meaningful with its overlay set.

    A row labelled plain `T2` claims to describe every T2 repo. It describes
    only the ones that declare no flags, which `hq-private` and `wealthlens-hq`
    are not, so the overlay travels with the label everywhere a tier is named.
    """
    return f"T{tier}" + ("".join(f"+{name}" for name in overlays))


def print_report(result: dict[str, Any], top: int, width: int) -> None:
    corpus = result["corpus"]
    baseline = result["baseline"]
    candidate = result["candidate"]
    overlays = list(result["run"].get("overlays") or [])
    print("=" * 78)
    print("deny-floor corpus replay")
    print("=" * 78)
    print(
        f"baseline  : floor {baseline['version']}  {baseline['path']}\n"
        f"            check({', '.join(baseline.get('check_parameters') or [])})"
    )
    print(
        f"candidate : floor {candidate['version']}  {candidate['path']}\n"
        f"            check({', '.join(candidate.get('check_parameters') or [])})"
    )
    print(f"project   : {result['project_dir']}")
    print(
        "overlays  : "
        + (
            ", ".join(overlays)
            if overlays
            else "(none) - every row describes a repo declaring no tier.json flags"
        )
    )
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
    print(
        "  shell channels scanned: codex function_call{shell_command,shell} + "
        "custom_tool_call{exec}; claude tool_use{Bash,PowerShell}"
    )
    print("  entries in those channels that could NOT be parsed / extracted:")
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
    print(
        "  'blocked' = any non-allow, i.e. Codex semantics: respond() converts\n"
        "  ask -> deny for Codex. For Claude an ask is a prompt, not a refusal;\n"
        "  the Claude-semantics refusal rate (deny + error) is per tier below."
    )
    skipped = int(corpus["notes"].get("skipped-over-max-chars", 0))
    print(
        f"  excluded before replay: {skipped} command(s) longer than "
        f"--max-command-chars ({result['run'].get('max_command_chars')}). Long\n"
        "  commands skew blocked, so every rate below is biased slightly low."
    )
    print(
        "  'err' = check() raised. Any non-zero value invalidates the deltas on\n"
        "  that row: an error counts as blocked, so error->allow inflates 'new\n"
        "  alw' and error->deny never reaches 'new blk'."
    )
    labels = {key: tier_label(key, overlays) for key in result["tier_order"]}
    label_width = max([len("tier")] + [len(text) for text in labels.values()]) + 2
    header = (
        f"  {'tier':<{label_width}}{'baseline':>18}{'candidate':>18}"
        f"{'new blk':>9}{'new alw':>9}{'+ask':>7}{'-ask':>7}{'err b/c':>10}"
    )
    print(header)
    for tier_key in result["tier_order"]:
        base = result["tiers"][tier_key]["baseline"]
        cand = result["tiers"][tier_key]["candidate"]
        delta = result["tiers"][tier_key]["delta"]
        errors = (
            f"{base['decisions'].get('error', 0)}/{cand['decisions'].get('error', 0)}"
        )
        print(
            f"  {labels[tier_key]:<{label_width}}"
            f"{base['unique_blocked']:>8} {base['unique_block_rate'] * 100:>8.2f}%"
            f"{cand['unique_blocked']:>8} {cand['unique_block_rate'] * 100:>8.2f}%"
            f"{delta['newly_blocked_unique']:>9}{delta['newly_allowed_unique']:>9}"
            f"{delta['ask_gained_unique']:>7}{delta['ask_lost_unique']:>7}"
            f"{errors:>10}"
        )
    toolfails = count_toolfails(result)
    if sum(toolfails.values()):
        print(
            "  NOTE: the replay itself failed on some commands (baseline "
            f"{toolfails['baseline']} / candidate {toolfails['candidate']}).\n"
            "  Those are in no rate and in no delta bucket above; see the "
            "TOOL FAILURE banner."
        )
    asked = any(
        result["tiers"][tier_key][label]["unique_ask"]
        for tier_key in result["tier_order"]
        for label in ("baseline", "candidate")
    )
    if not asked:
        print("  no ask decisions at any replayed tier in either version")
    print()
    for tier_key in result["tier_order"]:
        tier = result["tiers"][tier_key]
        print("=" * 78)
        print(f"tier {tier_key}  [overlays: {', '.join(overlays) or 'none'}]")
        print("-" * 78)
        for label in ("baseline", "candidate"):
            summary = tier[label]
            decisions = summary["decisions"]
            print(
                f"  {label:<10} deny={decisions.get('deny', 0)} "
                f"ask={decisions.get('ask', 0)} "
                f"error={decisions.get('error', 0)} "
                f"allow={decisions.get('allow', 0)} "
                f"toolfail={summary.get('unique_toolfail', 0)}  "
                f"blocked invocations={summary['invocations_blocked']}"
                f" / {summary['invocations']}"
                f" ({summary['invocation_block_rate'] * 100:.2f}%)"
            )
            print(
                f"             blocked unique (codex semantics, ask counted)"
                f" = {summary['unique_blocked']}"
                f" ({summary['unique_block_rate'] * 100:.2f}%)"
                f"; refused unique (claude semantics, deny+error)"
                f" = {summary['unique_refused']}"
                f" ({summary['unique_refuse_rate'] * 100:.2f}%)"
            )
            runtimes = summary["blocked_unique_by_runtime"]
            print(
                "             blocked unique by runtime: "
                + ", ".join(f"{name}={runtimes.get(name, 0)}" for name in RUNTIMES)
            )
        if not (tier["baseline"]["unique_ask"] or tier["candidate"]["unique_ask"]):
            print(
                "  no ask decisions at this tier in either version, so the two "
                "rates above coincide"
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
        print_rest_of_bucket(delta, "newly_blocked", top, tier_key)
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
        print_rest_of_bucket(delta, "newly_allowed", top, tier_key)
        for label, caption in (
            (
                "ask_gained",
                "ASK GAINED (baseline refused -> candidate asks; a relaxation "
                "for Claude, still deny for Codex)",
            ),
            (
                "ask_lost",
                "ASK LOST (baseline asked -> candidate refuses; a tightening "
                "for Claude, no change for Codex)",
            ),
            (
                "crash_moved",
                "CRASH MOVED (deny <-> error: a rule-evaluation exception "
                "changed side)",
            ),
            (
                "tool_failed",
                "TOOL FAILED (the replay could not obtain a verdict: NOT a "
                "policy result, counted in no rate)",
            ),
        ):
            if not delta[f"{label}_unique"]:
                continue
            print(
                f"  {caption}: {delta[f'{label}_unique']} unique / "
                f"{delta[f'{label}_invocations']} invocations"
            )
            for row in delta[f"{label}_top"]:
                print(
                    f"    [{row['invocations']:>4}x {row['was']}->{row['decision']}] "
                    f"{clip(row['command'], width)}"
                )
                print(f"           reason: {clip(row['reason'], width)}")
            print_rest_of_bucket(delta, label, top, tier_key)
        residual = {
            key: value
            for key, value in delta["transitions"].items()
            if key.split("->")[0] != key.split("->")[1]
        }
        if residual:
            print(f"  full transition matrix (changed verdicts only): {residual}")
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


def count_errors(result: dict[str, Any]) -> dict[str, int]:
    """Per-version total of `check()` exceptions across every replayed tier."""
    return {
        version: sum(
            int(result["tiers"][tier][version]["decisions"].get("error", 0))
            for tier in result["tier_order"]
        )
        for version in ("baseline", "candidate")
    }


def count_toolfails(result: dict[str, Any]) -> dict[str, int]:
    """Per-version total of commands the *harness* failed to get a verdict for."""
    return {
        version: sum(
            int(result["tiers"][tier][version].get("unique_toolfail", 0))
            for tier in result["tier_order"]
        )
        for version in ("baseline", "candidate")
    }


def print_toolfail_banner(result: dict[str, Any], toolfails: dict[str, int]) -> None:
    """A malfunctioning instrument is never a measurement. Say so on both streams.

    Unlike the `check() RAISED` banner this one has no opt-out: `--allow-errors`
    exists to census *floor* crashes, and there is nothing to census when the
    script itself could not run the floor.
    """
    reasons: Counter[str] = Counter()
    for tier in result["tier_order"]:
        for version in ("baseline", "candidate"):
            for row in result["tiers"][tier][version].get("toolfail_reasons", []):
                reasons[row["reason"]] += int(row["unique"])
    for stream in (sys.stdout, sys.stderr):
        print("!" * 78, file=stream)
        print(
            "!! REPLAY TOOL FAILURE: baseline "
            f"{toolfails['baseline']} / candidate {toolfails['candidate']} "
            "commands got no verdict.",
            file=stream,
        )
        print(
            "!! These are the SCRIPT failing, not the floor deciding. They are "
            "excluded from\n"
            "!! every rate and every delta bucket, so the numbers above "
            "understate coverage\n"
            f"!! rather than misreport policy. Exiting {EXIT_TOOL_FAILURE}.",
            file=stream,
        )
        for reason, count in reasons.most_common(10):
            print(f"!!   {count:>6}  {reason}", file=stream)
        print("!" * 78, file=stream)


def print_error_banner(result: dict[str, Any], errors: dict[str, int]) -> None:
    """Refuse to let a crashing version be read as a clean comparison.

    `decide()` turns an exception into an `error` decision and `summarize_tier`
    counts every non-allow as blocked, so a version that crashes looks maximally
    strict. That corrupts both gate numbers in the unsafe direction at once:
    error -> allow lands in NEWLY ALLOWED (a relaxation looks larger and better
    evidenced than it is) and error -> deny lands in `crash_moved`, never in
    NEWLY BLOCKED — so a crashing baseline drives the regression count to zero.
    A stub baseline with a pre-`remote_resolver` `check()` signature produced
    `new blocks 0 / new allows 1` and exit 0 before this guard existed.
    """
    for stream in (sys.stdout, sys.stderr):
        print("!" * 78, file=stream)
        print(
            "!! check() RAISED: baseline "
            f"{errors['baseline']} / candidate {errors['candidate']} error "
            "decisions.",
            file=stream,
        )
        print(
            "!! Every delta above is unusable. An error counts as blocked, so "
            "NEWLY ALLOWED\n"
            "!! is inflated and NEWLY BLOCKED is suppressed. The exception "
            "texts are the\n"
            "!! `error` rows of the block-class tables. Fix the version, or "
            "pass --allow-errors\n"
            f"!! to accept the numbers anyway. Exiting {EXIT_ERRORS_PRESENT}.",
            file=stream,
        )
        print("!" * 78, file=stream)


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
    parser.add_argument(
        "--flag",
        action="append",
        dest="flags",
        choices=sorted(OVERLAY_FLAGS),
        help=(
            "tier.json overlay to enable for every replayed command (repeatable; "
            "default: none, i.e. a repo that declares no flags)"
        ),
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
    parser.add_argument(
        "--allow-errors",
        action="store_true",
        help=(
            "report an exception inside check() instead of exiting non-zero "
            "(for a deliberate crash census only; the deltas are not usable)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tiers = sorted(set(args.tiers)) if args.tiers else list(DEFAULT_TIERS)
    overlays = sorted(set(args.flags or ()))
    flags = {name: True for name in overlays}
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
    # Prove both versions are callable before replaying anything. Each side is
    # bound to its own declared signature, so a baseline predating
    # `command_cwd` / `remote_resolver` measures correctly instead of raising
    # `TypeError` per command and reading as a 100% block rate (issue #39).
    try:
        baseline_parameters = describe_check_signature(baseline_module)
        candidate_parameters = describe_check_signature(candidate_module)
    except CheckSignatureError as error:
        sys.stderr.write(f"cannot replay: {error}\n")
        return EXIT_TOOL_FAILURE

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
            flags,
        )
    except ReplayHarnessError as error:
        # A whole-run harness failure: never fall through to a report, because
        # a partial replay printed as a table is indistinguishable from a real
        # measurement.
        sys.stderr.write(f"replay aborted: {error}\n")
        return EXIT_TOOL_FAILURE
    finally:
        os.environ.update(injected)

    result: dict[str, Any] = {
        "baseline": {
            "path": str(args.baseline),
            "version": baseline_version,
            "sha256": file_sha256(args.baseline),
            "check_parameters": baseline_parameters,
        },
        "candidate": {
            "path": str(args.candidate),
            "version": candidate_version,
            "sha256": file_sha256(args.candidate),
            "check_parameters": candidate_parameters,
        },
        "project_dir": str(args.project_dir),
        "tier_order": tiers,
        "run": {
            "flags": flags,
            "overlays": overlays,
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
    errors = count_errors(result)
    toolfails = count_toolfails(result)
    result["run"]["errors"] = errors
    result["run"]["toolfails"] = toolfails
    result["run"]["allow_errors"] = bool(args.allow_errors)

    print_report(result, args.top, args.sample_width)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        sys.stderr.write(
            f"wrote {args.json_path} (contains untruncated command text)\n"
        )
    if sum(errors.values()) and not args.allow_errors:
        print_error_banner(result, errors)
    if sum(toolfails.values()):
        # Reported after the floor-crash banner and wins the exit code: a broken
        # instrument is the more fundamental failure of the two.
        print_toolfail_banner(result, toolfails)
        return EXIT_TOOL_FAILURE
    if sum(errors.values()) and not args.allow_errors:
        return EXIT_ERRORS_PRESENT
    return 0


if __name__ == "__main__":
    sys.exit(main())
