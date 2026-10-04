#!/usr/bin/env python3
"""Stage a curated, public-safe subset of the repository docs for GitHub Pages.

    python scripts/build_docs_site.py [--out _site_src]

The output folder is the Jekyll source for `actions/jekyll-build-pages` (GitHub's
own Jekyll 3.10, the `github-pages` gem). Only the explicit allowlist below is
published; operational files stay out. The build is deterministic (sorted order,
no timestamps) and fails closed: a named root document that is missing is an
error, never a silent omission.

Links: every Markdown link between staged pages is converted to a relative `.html`
link here, relative to the page it sits in, and links to files that are not
published are pointed at GitHub. No Jekyll plugin rewrites links (the
`jekyll-relative-links` regex also rewrote text inside code). Code is found by a
small block scanner (fences, indented code, blockquotes, list items, multi-line
code spans), so links inside code are left exactly as written.

Liquid safety: GitHub Pages Jekyll 3.10 does not support `render_with_liquid`
(that arrived in Jekyll 4.0), so every page body is wrapped in
`{% raw %} ... {% endraw %}` instead, and any literal `{% endraw %}` inside a
doc is split so it cannot end the block early.
"""

import argparse
import bisect
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import quote, unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/Chris0Jeky/agent-harness"
RAW_URL = "https://raw.githubusercontent.com/Chris0Jeky/agent-harness/main"

# Allowlist: root document -> staged name. All of these must exist.
ROOT_DOCS = {
    "README.md": "index.md",
    "BLUEPRINT.md": "BLUEPRINT.md",
    "SPECS.md": "SPECS.md",
    "BOOK.md": "BOOK.md",
    "ROADMAP.md": "ROADMAP.md",
    "FLOOR_LIMITATIONS.md": "FLOOR_LIMITATIONS.md",
    "LICENSING.md": "LICENSING.md",
    "REPLAY_TOOL_PRODUCT.md": "REPLAY_TOOL_PRODUCT.md",
    "BLUEPRINT_PLUGIN_PRODUCT.md": "BLUEPRINT_PLUGIN_PRODUCT.md",
}
# These two briefs open with metadata lines, so their first `# ` heading is a later section.
TITLE_OVERRIDES = {
    "BLUEPRINT_PLUGIN_PRODUCT.md": "Blueprint plugin product brief",
    "REPLAY_TOOL_PRODUCT.md": "Replay tool product brief",
}
# Globbed documents (may vary as docs are added) and what the glob must skip.
DOC_GLOB = "docs/**/*.md"  # selected from `git ls-files`, never from the filesystem
EXCLUDED_DIRS = ("docs/archive", "docs/superpowers")
# Never published, whatever the allowlist says (belt and braces).
DENIED_ROOT_FILES = frozenset(
    {
        "AGENT_HARNESS_AGENT_BRIEF.md",
        "AGENT_HARNESS_OPERATIONS.md",
        "CLAUDE_CONFIG_OPERATIONS.md",
        "HANDOFF.md",
        "HUMAN_TODO.md",
        "MIGRATION_PROMPT.md",
        "AGENTS.md",
        "CLAUDE.md",
    }
)
DENIED_DIRS = ("handoffs", "plans", *EXCLUDED_DIRS)

NAV = (
    ("Home", "index.html"),
    ("Blueprint", "BLUEPRINT.html"),
    ("Specs", "SPECS.html"),
    ("Book", "BOOK.html"),
    ("Roadmap", "ROADMAP.html"),
    ("All documents", "docs-index.html"),
)
DESCRIPTION = (
    "Tier model, deny floor, and tooling for measuring and improving "
    "coding-agent policies."
)
CONFIG = f"""title: agent-harness
description: {DESCRIPTION}
url: https://chris0jeky.github.io
baseurl: /agent-harness
theme: jekyll-theme-primer
plugins:
  - jekyll-optional-front-matter
  - jekyll-titles-from-headings
  - jekyll-default-layout
"""
MARKER = ".docs-site-stage"
MARKER_TEXT = "Staged by scripts/build_docs_site.py; safe to clear.\n"


class BuildError(Exception):
    """A condition under which the site must not be built."""


def check_not_denied(rel):
    """Refuse to publish anything on the deny list."""
    parts = rel.split("/")
    if rel in DENIED_ROOT_FILES or (len(parts) == 1 and parts[0] in DENIED_ROOT_FILES):
        raise BuildError(f"refusing to publish denied file: {rel}")
    for denied in DENIED_DIRS:
        if rel == denied or rel.startswith(denied + "/"):
            raise BuildError(f"refusing to publish denied path: {rel}")


def validate_source(root, rel):
    """Require a regular file reached without any symlink or reparse point.

    Every component from the repository root down is checked with lstat, the
    resolved path must stay inside the repository and outside `.git`, and the
    leaf must be a regular file. Applies to root documents and globbed ones alike.
    """
    root = Path(root).resolve()
    parts = rel.split("/")
    if rel.startswith("/") or ".." in parts or ".git" in parts:
        raise BuildError(f"refusing source path outside the published tree: {rel}")
    current = root
    info = None
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise BuildError(f"cannot read source {rel}: {exc.strerror}") from exc
        reparse = (getattr(info, "st_file_attributes", 0) or 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        )
        if stat.S_ISLNK(info.st_mode) or reparse:
            raise BuildError(f"refusing symlink or reparse point in source path: {rel}")
    if not stat.S_ISREG(info.st_mode):
        raise BuildError(f"source is not a regular file: {rel}")
    resolved = current.resolve()
    if root not in resolved.parents or ".git" in resolved.relative_to(root).parts:
        raise BuildError(f"source resolves outside the repository: {rel}")


# Only these inherited variables survive into git: everything else under GIT_ can
# redirect the repository, index, worktree or config that `ls-files` would read.
GIT_ENV_KEEP = frozenset({"GIT_EXEC_PATH"})
GITLINK_MODE = b"160000"


def git_env():
    """The environment for git: inherited, minus every GIT_* repository override."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_") or key.upper() in GIT_ENV_KEEP
    }


def run_git(root, *args):
    """Run git bound to the checkout `root`; return stdout, failing closed."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, env=git_env()
        )
    except OSError as exc:
        raise BuildError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise BuildError(
            f"git {args[0]} failed with status {proc.returncode}: {detail}"
        )
    return proc.stdout


def check_checkout(root):
    """Require `root` to be the top level of the git checkout that answers for it."""
    top = os.fsdecode(run_git(root, "rev-parse", "--show-toplevel")).strip()
    try:
        same = bool(top) and os.path.samefile(top, root)
    except OSError:
        same = False
    if not same:
        raise BuildError(
            f"{root} is not the top level of its git checkout (git reports {top or 'nothing'})"
        )


def tracked_docs(root):
    """Tracked files under docs/ (git index only, gitlinks excluded); fail closed."""
    check_checkout(root)
    docs = set()
    for entry in run_git(root, "ls-files", "-s", "-z", "--", "docs").split(b"\0"):
        if not entry:
            continue
        meta, tab, path = entry.partition(b"\t")
        fields = meta.split()
        if not tab or len(fields) != 3:
            raise BuildError(f"cannot parse git ls-files output: {entry!r}")
        if fields[0] == GITLINK_MODE:  # a submodule, not a document
            continue
        docs.add(path.decode("utf-8"))
    return sorted(docs)


def collect_sources(root):
    """Return {repo-relative path: staged path}, sorted; fail closed on any doubt."""
    root = Path(root)
    missing = [name for name in ROOT_DOCS if not os.path.lexists(root / name)]
    if missing:
        raise BuildError(
            "missing required root document(s): " + ", ".join(sorted(missing))
        )
    sources = dict(ROOT_DOCS)
    for rel in tracked_docs(root):
        parts = rel.split("/")
        if not rel.endswith(".md") or any(part.startswith(".") for part in parts):
            continue
        if any(rel.startswith(d + "/") for d in EXCLUDED_DIRS):
            continue
        sources[rel] = rel
    for rel in sources:
        check_not_denied(rel)
        validate_source(root, rel)
    return dict(sorted(sources.items()))


def check_output_path(out, root, sources):
    """Resolve `out`, refusing anything that is not a safe place to clear and rewrite."""
    root = root.resolve()
    if out.is_symlink():
        raise BuildError(f"refusing symlinked output path: {out}")
    out = out.resolve()
    if out == root or root not in out.parents:
        raise BuildError(f"output path must be a folder inside the repository: {out}")
    if ".git" in out.relative_to(root).parts:
        raise BuildError(f"refusing to write inside .git: {out}")
    if out.exists():
        if not out.is_dir():
            raise BuildError(f"output path exists and is not a directory: {out}")
        if any(out.iterdir()) and not (out / MARKER).is_file():
            raise BuildError(
                f"refusing to clear {out}: not empty and not a previous staging folder"
            )
    for rel in sources:
        if out == (root / rel).resolve() or out in (root / rel).resolve().parents:
            raise BuildError(f"output path contains a published source: {out}")
    return out


HEADING = re.compile(r"[ \t]*#[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
INLINE_LINK = re.compile(
    r"(!?)\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*(<[^>\n]*>|[^\s()]+(?:\([^\s()]*\)[^\s()]*)*)"
    r"((?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?)\s*\)"
)
REF_DEF = re.compile(r"^( {0,3}\[[^\]\n]+\]:[ \t]*)(<[^>\n]*>|\S+)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
ENDRAW = re.compile(r"\{%(?=-?\s*endraw\b)")

FENCE_OPEN = re.compile(r"(`{3,}|~{3,})(.*)$")
FENCE_CLOSE = re.compile(r"(`{3,}|~{3,})[ \t]*$")
ATX = re.compile(r"#{1,6}(?:[ \t]|$)")
HRULE = re.compile(r"([-*_])(?:[ \t]*\1){2,}[ \t]*$")
LIST_MARK = re.compile(r"([-+*]|\d{1,9}[.)])(?=[ \t]|$)")
TABLE_DELIM = re.compile(r"\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
MASK = "\x00"


def skip_ws(line, pos, col):
    """Advance past spaces and tabs (tab stops of 4); return (pos, column)."""
    while pos < len(line) and line[pos] in " \t":
        col += 1 if line[pos] == " " else 4 - col % 4
        pos += 1
    return pos, col


def advance_to(line, pos, col, target):
    """Advance over whitespace until `col` reaches `target`."""
    while pos < len(line) and col < target and line[pos] in " \t":
        col += 1 if line[pos] == " " else 4 - col % 4
        pos += 1
    return pos, col


def after_quote_marker(line, pos, col):
    """Step past the optional single space (or tab) that follows a `>`."""
    if pos < len(line) and line[pos] in " \t":
        col += 1 if line[pos] == " " else 4 - col % 4
        pos += 1
    return pos, col


def starts_block(line, pos, indent):
    """Whether a line begins a block that may interrupt a paragraph."""
    if indent >= 4 or pos >= len(line):
        return False
    if line[pos] == ">" or ATX.match(line, pos) or HRULE.match(line, pos):
        return True
    fence = FENCE_OPEN.match(line, pos)
    if fence and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
        return True
    item = LIST_MARK.match(line, pos)
    if item:
        marker = item.group(1)
        blank = not line[item.end() :].strip()
        return not blank and (marker[0] in "-+*" or marker[:-1] == "1")
    return False


def scan_blocks(lines):
    """Find the text blocks of a Markdown document.

    Returns [(kind, depth, [(line index, start offset), ...])] for every
    paragraph, table row and ATX heading ("para" or "heading"); `depth` counts
    enclosing blockquotes and list items and `start` is where the line's own
    content begins after those containers' prefixes. Fenced code (inside
    blockquotes and list items too), indented code and blank lines are left out:
    that is how callers know where code is. A simplified CommonMark pass: no
    HTML blocks, no link reference definitions spanning lines.
    """
    blocks = []
    containers = []  # ("q", None) for a blockquote, ("l", content column) for a list item
    para = []
    fence = None  # (character, length) of the open fenced block

    def flush():
        nonlocal para
        if not para:
            return
        first = lines[para[0][0]][para[0][1] :]
        second = lines[para[1][0]][para[1][1] :] if len(para) > 1 else ""
        if "|" in first and "|" in second and TABLE_DELIM.match(second.strip()):
            for item in para:  # table cells never share a code span across rows
                blocks.append(("para", len(containers), [item]))
        else:
            blocks.append(("para", len(containers), para))
        para = []

    for idx, line in enumerate(lines):
        pos = col = matched = 0
        for kind, content_col in containers:
            p, c = skip_ws(line, pos, col)
            if kind == "q":
                if c - col < 4 and p < len(line) and line[p] == ">":
                    pos, col = after_quote_marker(line, p + 1, c + 1)
                    matched += 1
                    continue
            elif p >= len(line):  # a blank line keeps list items open
                pos, col = p, c
                matched += 1
                continue
            elif c >= content_col:
                pos, col = advance_to(line, pos, col, content_col)
                matched += 1
                continue
            break
        whole = matched == len(containers)
        if fence:
            if whole:
                p, c = skip_ws(line, pos, col)
                closer = FENCE_CLOSE.match(line, p)
                if (
                    closer
                    and c - col < 4
                    and closer.group(1)[0] == fence[0]
                    and len(closer.group(1)) >= fence[1]
                ):
                    fence = None
                continue
            fence = None  # the fence's container ended
        if not whole:
            p, c = skip_ws(line, pos, col)
            if para and p < len(line) and not starts_block(line, p, c - col):
                para.append((idx, pos))  # lazy continuation of the open paragraph
                continue
            flush()
            del containers[matched:]
        while True:  # open any new containers this line starts
            p, c = skip_ws(line, pos, col)
            if p >= len(line) or c - col >= 4:
                break
            if line[p] == ">":
                flush()
                containers.append(("q", None))
                pos, col = after_quote_marker(line, p + 1, c + 1)
                continue
            item = LIST_MARK.match(line, p)
            if not item or HRULE.match(line, p):
                break
            marker_end = c + len(item.group(1))
            q, qc = skip_ws(line, item.end(), marker_end)
            blank = q >= len(line)
            if para and not starts_block(line, p, c - col):
                break  # cannot interrupt a paragraph: it is paragraph text
            flush()
            if blank or qc - marker_end >= 5:
                content_col = marker_end + 1
            else:
                content_col = qc
            containers.append(("l", content_col))
            pos, col = advance_to(line, item.end(), marker_end, content_col)
        p, c = skip_ws(line, pos, col)
        if p >= len(line):
            flush()
        elif c - col >= 4:
            if para:  # indented text continues a paragraph; otherwise it is code
                para.append((idx, pos))
        else:
            opener = FENCE_OPEN.match(line, p)
            if opener and not (opener.group(1)[0] == "`" and "`" in opener.group(2)):
                flush()
                fence = (opener.group(1)[0], len(opener.group(1)))
            elif ATX.match(line, p):
                flush()
                blocks.append(("heading", len(containers), [(idx, pos)]))
            elif HRULE.match(line, p):
                flush()
            else:
                para.append((idx, pos))
    flush()
    return blocks


def first_title(text):
    lines = text.split("\n")
    for kind, depth, items in scan_blocks(lines):
        if kind == "heading" and depth == 0:
            index, start = items[0]
            m = HEADING.match(lines[index], start)
            if m and m.group(1):
                return plain_title(m.group(1))
    return None


def plain_title(raw):
    title = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", raw)
    title = re.sub(r"<[^>]+>", "", title)
    title = title.replace("`", "").replace("*", "")
    return " ".join(title.split())


def relative_path(from_dir, to):
    """The relative path from directory `from_dir` to `to` (both posix, repo-style)."""
    base = [part for part in from_dir.split("/") if part]
    dest = to.split("/")
    common = 0
    while common < len(base) and common < len(dest) - 1 and base[common] == dest[common]:
        common += 1
    return "/".join([".."] * (len(base) - common) + dest[common:])


def link_target(raw, src_rel, root, staged, image):
    """Return the rewritten link target, or None to leave it untouched.

    A link to a staged page becomes a relative `.html` link from the page it is
    in; a link to any other file or folder in the repository points at GitHub.
    """
    wrapped = raw.startswith("<") and raw.endswith(">")
    target = raw[1:-1] if wrapped else raw
    if (
        not target
        or target.startswith("#")
        or target.startswith("//")
        or SCHEME.match(target)
    ):
        return None
    suffix = ""
    cut = re.search(r"[?#]", target)
    path = target
    if cut:
        path, suffix = target[: cut.start()], target[cut.start() :]
    if not path:
        return None
    decoded = unquote(path)
    if decoded.startswith("/"):
        resolved = posixpath.normpath(decoded.lstrip("/"))
    else:
        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(src_rel), decoded)
        )
    if resolved == ".." or resolved.startswith("../"):
        return None
    if resolved in staged:
        here = posixpath.dirname(staged[src_rel])
        page = relative_path(here, html_name(staged[resolved]))
        return quote(page, safe="/") + suffix
    full = root / resolved
    if resolved == ".":
        return f"{REPO_URL}/tree/main{suffix}"
    quoted = quote(resolved, safe="/")
    if full.is_dir():
        return f"{REPO_URL}/tree/main/{quoted}{suffix}"
    if full.exists():
        base = RAW_URL if image else f"{REPO_URL}/blob/main"
        return f"{base}/{quoted}{suffix}"
    return None


def mask_code(text):
    """Blank out code spans and backslash escapes so link syntax inside is not seen.

    Same length as `text` (newlines kept), so offsets stay valid. A backtick run
    closes only on a run of the same length; an unclosed run is plain text; an
    escaped backtick opens nothing.
    """
    out = list(text)
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in ASCII_PUNCT:
            out[i] = out[i + 1] = MASK
            i += 2
        elif ch == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            run = j - i
            k = j
            close = -1
            while k < n:
                if text[k] != "`":
                    k += 1
                    continue
                e = k
                while e < n and text[e] == "`":
                    e += 1
                if e - k == run:
                    close = e
                    break
                k = e
            if close == -1:
                i = j
            else:
                for t in range(i, close):
                    if text[t] != "\n":
                        out[t] = MASK
                i = close
        else:
            i += 1
    return "".join(out)


def rewrite_block(contents, src_rel, root, staged):
    """Rewrite the links of one paragraph (its lines' own content, without prefixes)."""
    out = list(contents)
    defs = 0
    for k, text in enumerate(contents):  # definitions only open a paragraph
        ref = REF_DEF.match(text)
        if not ref:
            break
        new = link_target(ref.group(2), src_rel, root, staged, False)
        if new is not None:
            out[k] = ref.group(1) + new + text[ref.end() :]
        defs += 1
    rest = out[defs:]
    virtual = "\n".join(rest)
    starts = []
    offset = 0
    for text in rest:
        starts.append(offset)
        offset += len(text) + 1
    edits = []
    for m in INLINE_LINK.finditer(mask_code(virtual)):
        new = link_target(
            virtual[m.start(3) : m.end(3)], src_rel, root, staged, m.group(1) == "!"
        )
        if new is not None:
            edits.append((m.start(3), m.end(3), new))
    for begin, end, new in reversed(edits):
        k = bisect.bisect_right(starts, begin) - 1
        line = rest[k]
        rest[k] = line[: begin - starts[k]] + new + line[end - starts[k] :]
    return out[:defs] + rest


def rewrite_links(text, src_rel, root, staged):
    lines = text.split("\n")
    for _kind, _depth, items in scan_blocks(lines):
        contents = [lines[index][start:] for index, start in items]
        for (index, start), new in zip(
            items, rewrite_block(contents, src_rel, root, staged)
        ):
            lines[index] = lines[index][:start] + new
    return "\n".join(lines)


def split_front_matter(text):
    """Return (front matter lines without fences, body) or (None, text)."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            return text[4:end], text[end + 5 :]
    return None, text


def html_name(staged):
    """The page Jekyll produces for a staged Markdown file."""
    return posixpath.splitext(staged)[0] + ".html"


def nav_line(depth):
    prefix = "../" * depth
    return " · ".join(f"[{label}]({prefix}{target})" for label, target in NAV)


def wrap_page(title, body, depth):
    """Front matter, nav and a Liquid-safe body for one page."""
    front, body = split_front_matter(body)
    lines = [] if front is None else front.split("\n")
    if not any(line.startswith("title:") for line in lines):
        lines.insert(0, f"title: {json.dumps(title, ensure_ascii=False)}")
    safe = ENDRAW.sub('{% endraw %}{{ "{%" }}{% raw %}', body.strip("\n"))
    content = f"{nav_line(depth)}\n\n{safe}"
    return (
        "---\n" + "\n".join(lines) + "\n---\n{% raw %}\n" + content + "\n{% endraw %}\n"
    )


def docs_index(pages):
    """The 'All documents' listing, grouped by folder. pages: [(staged path, title)]."""
    groups = {}
    for staged, title in pages:
        groups.setdefault(posixpath.dirname(staged), []).append((staged, title))
    lines = [
        "# All documents",
        "",
        "Every page published on this site, grouped by folder.",
    ]
    for folder in sorted(groups, key=lambda f: (f != "", f)):
        lines += ["", f"## {folder or 'Root'}", ""]
        for staged, title in sorted(
            groups[folder], key=lambda p: (p[0] != "index.md", p)
        ):
            lines.append(f"- [{title}]({quote(html_name(staged), safe='/')})")
    return "\n".join(lines) + "\n"


def read_source(path):
    try:
        return (
            path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        )
    except UnicodeDecodeError as exc:
        raise BuildError(f"not valid UTF-8: {path}") from exc


def build(out, root=REPO_ROOT):
    """Stage the site into `out`; return the staged page paths (excluding _config.yml)."""
    root = Path(root).resolve()
    sources = collect_sources(root)
    out = check_output_path(Path(out), root, sources)
    staged_map = sources
    rendered = {}
    pages = []
    for rel, staged in staged_map.items():
        text = rewrite_links(read_source(root / rel), rel, root, staged_map)
        title = (
            TITLE_OVERRIDES.get(rel)
            or first_title(text)
            or posixpath.splitext(posixpath.basename(staged))[0]
        )
        pages.append((staged, title))
        rendered[staged] = wrap_page(title, text, staged.count("/"))
    index_title = "All documents"
    rendered["docs-index.md"] = wrap_page(index_title, docs_index(pages), 0)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for rel, text in sorted(rendered.items()):
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(text.encode("utf-8"))
    (out / "_config.yml").write_bytes(CONFIG.encode("utf-8"))
    (out / MARKER).write_bytes(MARKER_TEXT.encode("utf-8"))
    return sorted(rendered)


class LinkCollector(HTMLParser):
    """Collect the targets of `<a href>` and `<img src>` in one rendered page."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value and (tag, name) in (("a", "href"), ("img", "src")):
                self.links.append(value)


def check_built_site(site_dir, baseurl="/agent-harness"):
    """Check the rendered HTML Jekyll produced; return a list of problems.

    Every relative link, and every root-relative link under `baseurl`, must name
    a file (or a folder with an index page, or an extensionless page) inside the
    site; root-relative links outside `baseurl` would 404 once deployed; and no
    link may still point at a `.md` file.
    """
    site_dir = Path(site_dir).resolve()
    base = baseurl.rstrip("/")
    pages = sorted(site_dir.rglob("*.html"))
    if not pages:
        return [f"no HTML pages found in {site_dir.name}"]
    problems = []
    for page in pages:
        rel = page.relative_to(site_dir).as_posix()
        collector = LinkCollector()
        collector.feed(page.read_text(encoding="utf-8"))
        for href in collector.links:
            path = re.split(r"[?#]", href, maxsplit=1)[0]
            if not path or href.startswith("//") or SCHEME.match(href):
                continue
            path = unquote(path)
            if path.startswith("/"):
                if base and path != base and not path.startswith(base + "/"):
                    problems.append(f"{rel}: root-relative link outside {base}/: {href}")
                    continue
                target = posixpath.normpath(path[len(base) :].lstrip("/") or ".")
            else:
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(rel), path)
                )
            if target == ".." or target.startswith("../"):
                problems.append(f"{rel}: link leaves the site: {href}")
            elif path.endswith(".md"):
                problems.append(f"{rel}: link still points at Markdown: {href}")
            else:
                found = site_dir / target
                if not (
                    found.is_file()
                    or (found / "index.html").is_file()
                    or found.with_name(found.name + ".html").is_file()
                ):
                    problems.append(f"{rel}: broken link: {href}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--out", default="_site_src", help="output folder inside the repository"
    )
    parser.add_argument(
        "--check-site",
        metavar="DIR",
        help="instead of staging, check the links in the Jekyll-built site in DIR",
    )
    parser.add_argument(
        "--baseurl", default="/agent-harness", help="site base path for --check-site"
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check_site:
        problems = check_built_site(args.check_site, args.baseurl)
        for problem in problems:
            print(f"build_docs_site: {problem}", file=sys.stderr)
        if not problems:
            print(f"checked the links of {args.check_site}")
        return 1 if problems else 0
    root = Path(args.root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    try:
        staged = build(out, root=root)
    except BuildError as exc:
        print(f"build_docs_site: {exc}", file=sys.stderr)
        return 1
    print(f"staged {len(staged)} pages into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
