#!/usr/bin/env python3
"""Stage a curated, public-safe subset of the repository docs for GitHub Pages.

    python scripts/build_docs_site.py [--out _site_src]

The output folder is the Jekyll source for `actions/jekyll-build-pages` (GitHub's
own Jekyll 3.10, the `github-pages` gem). Only the explicit allowlist below is
published; operational files stay out. The build is deterministic (sorted order,
no timestamps) and fails closed: a named root document that is missing is an
error, never a silent omission.

Liquid safety: GitHub Pages Jekyll 3.10 does not support `render_with_liquid`
(that arrived in Jekyll 4.0), so every page body is wrapped in
`{% raw %} ... {% endraw %}` instead, and any literal `{% endraw %}` inside a
doc is split so it cannot end the block early.
"""

import argparse
import json
from pathlib import Path
import posixpath
import re
import shutil
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
DOC_GLOB = "docs/**/*.md"
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
    ("Home", "index.md"),
    ("Blueprint", "BLUEPRINT.md"),
    ("Specs", "SPECS.md"),
    ("Book", "BOOK.md"),
    ("Roadmap", "ROADMAP.md"),
    ("All documents", "docs-index.md"),
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
  - jekyll-relative-links
  - jekyll-optional-front-matter
  - jekyll-titles-from-headings
  - jekyll-default-layout
relative_links:
  enabled: true
  collections: false
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


def collect_sources(root):
    """Return {repo-relative path: staged path}, sorted; fail closed on a missing root doc."""
    sources = {}
    missing = [name for name in ROOT_DOCS if not (root / name).is_file()]
    if missing:
        raise BuildError(
            "missing required root document(s): " + ", ".join(sorted(missing))
        )
    for name, staged in ROOT_DOCS.items():
        sources[name] = staged
    globbed = sorted(
        p.relative_to(root).as_posix()
        for p in root.glob(DOC_GLOB)
        if p.is_file() or p.is_symlink()
    )
    for rel in globbed:
        if any(rel.startswith(d + "/") for d in EXCLUDED_DIRS):
            continue
        if (root / rel).is_symlink():
            raise BuildError(f"refusing to publish symlink: {rel}")
        sources[rel] = rel
    for rel in sources:
        check_not_denied(rel)
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


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^ {0,3}#[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
INLINE_LINK = re.compile(
    r"(!?)\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*(<[^>\n]*>|[^\s()]+(?:\([^\s()]*\)[^\s()]*)*)"
    r"((?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?)\s*\)"
)
REF_DEF = re.compile(r"^( {0,3}\[[^\]\n]+\]:[ \t]*)(<[^>\n]*>|\S+)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
ENDRAW = re.compile(r"\{%(?=-?\s*endraw\b)")


def iter_lines(text):
    """Yield (line, in_fence) for each line; fence delimiters count as fenced."""
    fence = None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                yield line, True
                continue
            yield line, False
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            yield line, True


def first_title(text):
    for line, fenced in iter_lines(text):
        if fenced:
            continue
        m = HEADING.match(line)
        if m and m.group(1):
            return plain_title(m.group(1))
    return None


def plain_title(raw):
    title = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", raw)
    title = re.sub(r"<[^>]+>", "", title)
    title = title.replace("`", "").replace("*", "")
    return " ".join(title.split())


def link_target(raw, src_rel, root, staged, image):
    """Return the rewritten link target, or None to leave it untouched."""
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
        if resolved == "README.md" and decoded.endswith("README.md"):
            return path[: -len("README.md")] + "index.md" + suffix
        return None
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


def rewrite_links(text, src_rel, root, staged):
    out = []
    for line, fenced in iter_lines(text):
        if fenced:
            out.append(line)
            continue
        spans = [m.span() for m in CODE_SPAN.finditer(line)]

        def in_code(pos, spans=spans):
            return any(a <= pos < b for a, b in spans)

        def inline(m):
            if in_code(m.start()):
                return m.group(0)
            new = link_target(m.group(3), src_rel, root, staged, m.group(1) == "!")
            if new is None:
                return m.group(0)
            return f"{m.group(1)}[{m.group(2)}]({new}{m.group(4)})"

        line = INLINE_LINK.sub(inline, line)
        ref = REF_DEF.match(line)
        if ref:
            new = link_target(ref.group(2), src_rel, root, staged, False)
            if new is not None:
                line = ref.group(1) + new + line[ref.end() :]
        out.append(line)
    return "\n".join(out)


def split_front_matter(text):
    """Return (front matter lines without fences, body) or (None, text)."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            return text[4:end], text[end + 5 :]
    return None, text


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
            lines.append(f"- [{title}]({staged})")
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--out", default="_site_src", help="output folder inside the repository"
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
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
