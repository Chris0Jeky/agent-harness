"""Contract tests for the GitHub Pages docs-site stager."""

import importlib.util
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_docs_site.py"

spec = importlib.util.spec_from_file_location("build_docs_site", SCRIPT)
site = importlib.util.module_from_spec(spec)
sys.modules["build_docs_site"] = site
spec.loader.exec_module(site)

REPO_URL = "https://github.com/Chris0Jeky/agent-harness"


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def make_repo(root, readme=None, extra=None):
    """A miniature repository: every named root doc, a few docs, and unpublished files."""
    root = Path(root)
    for name in site.ROOT_DOCS:
        write(root, name, f"# Title of {name}\n\nBody of {name}.\n")
    write(root, "README.md", readme or "# agent-harness\n\nHello.\n")
    write(root, "docs/GUIDE.md", "# The Guide\n\nGuide body.\n")
    write(root, "docs/evals/TAXONOMY.md", "# Eval Taxonomy\n\nTaxonomy.\n")
    write(root, "docs/archive/OLD.md", "# Old stuff\n")
    write(root, "docs/superpowers/SCRATCH.md", "# Scratch\n")
    for name in (
        "HANDOFF.md",
        "HUMAN_TODO.md",
        "AGENTS.md",
        "CLAUDE.md",
        "MIGRATION_PROMPT.md",
        "AGENT_HARNESS_AGENT_BRIEF.md",
        "AGENT_HARNESS_OPERATIONS.md",
        "CLAUDE_CONFIG_OPERATIONS.md",
        "handoffs/2026-01-01.md",
        "plans/ACTIVE.md",
    ):
        write(root, name, f"# Private {name}\n")
    write(root, "scripts/tool.py", "print('hi')\n")
    write(root, "tests/test_x.py", "pass\n")
    write(root, "templates/hooks/dispatch.py", "pass\n")
    write(root, "harness.py", "pass\n")
    for (
        name
    ) in (
        site.THEME_FILES
    ):  # the real theme: the layout is part of what these tests exercise
        theme = (ROOT / site.THEME_DIR / name).read_text(encoding="utf-8")
        write(root, f"{site.THEME_DIR}/{name}", theme)
    for rel, text in (extra or {}).items():
        write(root, rel, text)
    return root


def git(root, *args):
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def git_track_all(root):
    """Make `root` a git repository with everything (not ignored) in the index."""
    root = Path(root)
    if not (root / ".git").exists():
        git(root, "init", "-q")
    git(root, "add", "-A")


def symlink_or_skip(testcase, link, target, directory=False):
    try:
        os.symlink(target, link, target_is_directory=directory)
        return
    except (OSError, NotImplementedError) as exc:
        failure = exc
    if directory and sys.platform == "win32":  # a junction needs no privilege
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True
        )
        if done.returncode == 0:
            return
    testcase.skipTest(f"symlinks unavailable: {failure}")


def fake_lstat(real, rel_name, mode=None, attributes=None):
    """An os.lstat that reports `rel_name` as a symlink (mode) or reparse point."""

    def lstat(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        if Path(path).name != rel_name:
            return info
        fields = list(info)
        if mode is not None:
            fields[0] = mode
        result = os.stat_result(fields)
        if attributes is None:
            return result

        class Wrapped:
            st_mode = result.st_mode
            st_file_attributes = attributes

        return Wrapped()

    return lstat


def read_tree(out):
    out = Path(out)
    return {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in sorted(out.rglob("*"))
        if p.is_file()
    }


NAV_ITEM = re.compile(r'^ +- \{title: (".*"), url: (".*")\}$')
GROUP_HEAD = re.compile(r'^  - title: (".*")$')


def parse_nav(text):
    """`_data/docs_nav.yml` as {top: [(title, url)], groups: [(title, [(title, url)])], scalars: {...}}."""
    nav = {"top": [], "groups": [], "scalars": {}}
    section = None
    for line in text.split("\n"):
        item, head = NAV_ITEM.match(line), GROUP_HEAD.match(line)
        if line in ("top:", "groups:"):
            section = line[:-1]
        elif head:
            nav["groups"].append((json.loads(head.group(1)), []))
        elif item:
            pair = (json.loads(item.group(1)), json.loads(item.group(2)))
            (nav["top"] if section == "top" else nav["groups"][-1][1]).append(pair)
        elif line and not line.startswith(" ") and ": " in line:
            key, value = line.split(": ", 1)
            nav["scalars"][key] = json.loads(value) if value.startswith('"') else value
        elif line.strip() and line.strip() != "pages:":
            raise AssertionError(f"unexpected line in docs_nav.yml: {line!r}")
    return nav


def liquid_render(text):
    """Minimal model of Liquid for the constructs the stager emits.

    Handles {% raw %}...{% endraw %} blocks and the {{ "{%" }} string output that
    splits a literal endraw tag. Any other tag or output is returned as a
    sentinel so a leak fails the comparison.
    """
    out = []
    pos = 0
    token = re.compile(
        r"\{%-?\s*(\w+)\s*-?%\}|\{\{\s*\"(\{%)\"\s*\}\}|\{\{.*?\}\}|\{%.*?%\}"
    )
    while pos < len(text):
        m = token.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos : m.start()])
        if m.group(1) == "raw":
            end = re.compile(r"\{%-?\s*endraw\s*-?%\}").search(text, m.end())
            assert end, "unterminated raw block"
            out.append(text[m.end() : end.start()])
            pos = end.end()
        elif m.group(2):
            out.append(m.group(2))
            pos = m.end()
        else:
            out.append("<<LIQUID-LEAK>>")
            pos = m.end()
    return "".join(out)


class StageBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo(Path(self._tmp.name) / "repo")
        self.out = self.root / "_site_src"

    def build(self, **kwargs):
        git_track_all(self.root)
        return site.build(self.out, root=self.root, **kwargs)

    def page(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")


class StageTests(StageBase):
    def test_readme_becomes_index_without_an_inline_nav_line(self):
        self.build()
        index = self.page("index.md")
        self.assertIn("# agent-harness", index)
        self.assertFalse((self.out / "README.md").exists())
        self.assertNotIn("[Home](", index)  # navigation now comes from the layout
        self.assertNotIn(" · ", index)
        for rel in ("docs/GUIDE.md", "docs/evals/TAXONOMY.md", "docs-index.md"):
            self.assertNotIn("[Home](", self.page(rel), rel)

    def test_pages_name_the_layout_and_their_source(self):
        self.build()
        self.assertIn("\nlayout: default\n", self.page("index.md"))
        self.assertIn('\nsource_path: "README.md"\n', self.page("index.md"))
        taxonomy = self.page("docs/evals/TAXONOMY.md")
        self.assertIn('\nsource_path: "docs/evals/TAXONOMY.md"\n', taxonomy)
        self.assertIn("\nlayout: default\n", self.page("docs-index.md"))
        self.assertNotIn(
            "source_path", self.page("docs-index.md")
        )  # generated: no file to edit

    def test_nav_data_has_brand_top_entries_and_grouped_sidebar(self):
        self.build()
        nav = parse_nav(self.page("_data/docs_nav.yml"))
        self.assertEqual(nav["scalars"]["title"], "agent-harness")
        self.assertEqual(nav["scalars"]["tagline"], site.DESCRIPTION)
        self.assertEqual(nav["scalars"]["repo"], REPO_URL)
        self.assertEqual(nav["scalars"]["license"], "GPL-3.0-only")
        self.assertEqual(
            nav["top"],
            [
                ("Home", "/"),
                ("Blueprint", "/BLUEPRINT.html"),
                ("Specs", "/SPECS.html"),
                ("Book", "/BOOK.html"),
                ("Roadmap", "/ROADMAP.html"),
                ("All documents", "/docs-index.html"),
            ],
        )
        self.assertEqual(
            [title for title, _ in nav["groups"]], ["Overview", "Docs", "Evals"]
        )
        groups = dict(nav["groups"])
        self.assertEqual(
            groups["Overview"][0], ("agent-harness", "/")
        )  # the index leads its group
        self.assertIn(("Title of SPECS.md", "/SPECS.html"), groups["Overview"])
        self.assertEqual(groups["Docs"], [("The Guide", "/docs/GUIDE.html")])
        self.assertEqual(
            groups["Evals"], [("Eval Taxonomy", "/docs/evals/TAXONOMY.html")]
        )

    def test_nav_data_lists_every_staged_page_once(self):
        staged = self.build()
        nav = parse_nav(self.page("_data/docs_nav.yml"))
        urls = [url for _, pages in nav["groups"] for _, url in pages]
        self.assertEqual(len(urls), len(set(urls)))
        expected = {
            "/" if rel == "index.md" else "/" + rel[:-3] + ".html" for rel in staged
        }
        # The sidebar lists the content pages; the generated listing is reached from the top navigation.
        self.assertEqual(set(urls), expected - {"/docs-index.html"})

    def test_every_nav_url_maps_to_a_staged_page(self):
        self.build()
        nav = parse_nav(self.page("_data/docs_nav.yml"))
        urls = [url for _, url in nav["top"]]
        urls += [url for _, pages in nav["groups"] for _, url in pages]
        for url in urls:
            rel = "index.md" if url == "/" else url.lstrip("/")[: -len(".html")] + ".md"
            self.assertTrue((self.out / rel).is_file(), f"{url} is not a staged page")

    def test_nav_data_is_deterministic_and_quotes_awkward_titles(self):
        write(self.root, "docs/ODD.md", '# "Quoted": a {{ title }} here\n')
        self.build()
        first = self.page("_data/docs_nav.yml")
        self.assertNotIn(" ", first)
        nav = parse_nav(first)
        docs = dict(nav["groups"])["Docs"]
        self.assertIn(('"Quoted": a {{ title }} here', "/docs/ODD.html"), docs)
        self.build()
        self.assertEqual(first, self.page("_data/docs_nav.yml"))

    def test_yaml_strings_escape_line_separators(self):
        bs = chr(92)
        raw = "a" + chr(0x2028) + "b" + chr(0x85) + 'c "q" ' + chr(92) + " d"
        text = site.yaml_string(raw)
        for char in (chr(0x2028), chr(0x2029), chr(0x85)):
            self.assertNotIn(char, text)
        self.assertEqual(
            text,
            '"a'
            + bs
            + "u2028b"
            + bs
            + "u0085c "
            + bs
            + '"q'
            + bs
            + '" '
            + bs
            + bs
            + ' d"',
        )
        self.assertEqual(json.loads(text), raw)  # JSON-quoted strings are valid YAML

    def test_group_titles_are_human_friendly(self):
        self.assertEqual(site.folder_title(""), "Overview")
        self.assertEqual(site.folder_title("docs"), "Docs")
        self.assertEqual(site.folder_title("docs/evals"), "Evals")
        self.assertEqual(site.folder_title("docs/evals/examples"), "Evals / Examples")
        self.assertEqual(site.folder_title("docs/ux-evaluation"), "UX evaluation")
        self.assertEqual(site.folder_title("docs/review-evidence"), "Review evidence")

    def test_theme_files_are_staged(self):
        self.build()
        layout = self.page("_layouts/default.html")
        self.assertIn("site.data.docs_nav", layout)
        self.assertIn("{{ content }}", layout)
        for opener, closer in (("for", "endfor"), ("if", "endif")):
            opened = len(re.findall(r"\{%-?\s*" + opener + r"\b", layout))
            closed = len(re.findall(r"\{%-?\s*" + closer + r"\b", layout))
            self.assertGreater(opened, 0, f"no {opener} blocks found: pattern is wrong")
            self.assertEqual(
                opened, closed, f"unbalanced {opener} blocks in the layout"
            )
        self.assertNotIn("{{ page.title }}", layout)  # a title is always escaped
        for output in re.findall(r"\{\{[^}]*page\.title[^}]*\}\}", layout):
            self.assertIn("| escape", output)
        self.assertIn("--accent:", self.page("assets/css/docs.css"))
        for name in site.THEME_FILES:
            # Text mode: a Windows checkout may hold CRLF, and the stager writes LF.
            source = (ROOT / site.THEME_DIR / name).read_text(encoding="utf-8")
            self.assertEqual(self.page(name), source, name)

    def test_missing_theme_file_fails_closed_before_touching_output(self):
        (self.root / site.THEME_DIR / "_layouts" / "default.html").unlink()
        with self.assertRaises(site.BuildError) as ctx:
            self.build()
        self.assertIn("default.html", str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_symlinked_theme_file_is_rejected(self):
        outside = Path(self._tmp.name) / "outside.css"
        outside.write_text("body{}\n", encoding="utf-8")
        target = self.root / site.THEME_DIR / "assets" / "css" / "docs.css"
        target.unlink()
        symlink_or_skip(self, target, outside)
        with self.assertRaises(site.BuildError) as ctx:
            self.build()
        self.assertIn("docs.css", str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_docs_index_lists_pages_grouped_by_folder(self):
        self.build()
        listing = self.page("docs-index.md")
        self.assertIn("# All documents", listing)
        self.assertIn("[The Guide](docs/GUIDE.html)", listing)
        self.assertIn("[Eval Taxonomy](docs/evals/TAXONOMY.html)", listing)
        self.assertIn("[Title of SPECS.md](SPECS.html)", listing)
        self.assertLess(listing.index("## docs\n"), listing.index("## docs/evals\n"))

    def test_unpublished_material_is_absent(self):
        staged = self.build()
        tree = read_tree(self.out)
        for rel in (
            "HANDOFF.md",
            "HUMAN_TODO.md",
            "AGENTS.md",
            "CLAUDE.md",
            "MIGRATION_PROMPT.md",
            "AGENT_HARNESS_AGENT_BRIEF.md",
            "AGENT_HARNESS_OPERATIONS.md",
            "CLAUDE_CONFIG_OPERATIONS.md",
            "README.md",
            "docs/archive/OLD.md",
            "docs/superpowers/SCRATCH.md",
            "handoffs/2026-01-01.md",
            "plans/ACTIVE.md",
        ):
            self.assertNotIn(rel, tree)
            self.assertNotIn(rel, staged)
        self.assertEqual(
            {"_config.yml", "docs-index.md", "index.md", "docs/GUIDE.md"} <= set(tree),
            True,
        )

    def test_config_is_pinned(self):
        self.build()
        config = self.page("_config.yml")
        self.assertIn("title: agent-harness", config)
        self.assertIn(
            "\ntheme: null\n", config
        )  # the site's own layout replaces the stock theme
        self.assertNotIn("primer", config)
        for plugin in (
            "jekyll-optional-front-matter",
            "jekyll-titles-from-headings",
            "jekyll-default-layout",
        ):
            self.assertIn(f"  - {plugin}\n", config)

    def test_relative_links_plugin_is_switched_off(self):
        # The plugin ran a regex over the whole Markdown, code included; the stager converts every link itself.
        # It is on by default on GitHub Pages, so it is switched off as well as left out of the plugin list.
        self.build()
        config = self.page("_config.yml")
        self.assertNotIn("  - jekyll-relative-links", config)
        self.assertIn("relative_links:\n  enabled: false\n", config)
        self.assertEqual(config, site.CONFIG)

    def test_unpublished_links_are_rewritten_to_github(self):
        body = (
            "# Links\n\n"
            "[tool](../scripts/tool.py) and [dir](../templates/hooks/) and "
            "[dir2](../templates/hooks) and [anchor](../harness.py#L10) and "
            "[dot](./../harness.py) and [priv](../HANDOFF.md) and "
            '[abs](/harness.py) and [title](../harness.py "The CLI").\n'
        )
        write(self.root, "docs/LINKS.md", body)
        self.build()
        text = self.page("docs/LINKS.md")
        self.assertIn(f"[tool]({REPO_URL}/blob/main/scripts/tool.py)", text)
        self.assertIn(f"[dir]({REPO_URL}/tree/main/templates/hooks)", text)
        self.assertIn(f"[dir2]({REPO_URL}/tree/main/templates/hooks)", text)
        self.assertIn(f"[anchor]({REPO_URL}/blob/main/harness.py#L10)", text)
        self.assertIn(f"[dot]({REPO_URL}/blob/main/harness.py)", text)
        self.assertIn(f"[priv]({REPO_URL}/blob/main/HANDOFF.md)", text)
        self.assertIn(f"[abs]({REPO_URL}/blob/main/harness.py)", text)
        self.assertIn(f'[title]({REPO_URL}/blob/main/harness.py "The CLI")', text)

    def test_reference_definitions_are_rewritten(self):
        write(
            self.root,
            "docs/REF.md",
            "# Ref\n\nSee [tool][t].\n\n[t]: ../scripts/tool.py\n",
        )
        self.build()
        self.assertIn(
            f"[t]: {REPO_URL}/blob/main/scripts/tool.py", self.page("docs/REF.md")
        )

    def test_images_to_unpublished_files_use_raw_urls(self):
        write(self.root, "docs/img/a b.png", "x")
        write(self.root, "docs/IMG.md", "# I\n\n![alt](img/a%20b.png)\n")
        self.build()
        raw = "https://raw.githubusercontent.com/Chris0Jeky/agent-harness/main"
        self.assertIn(f"![alt]({raw}/docs/img/a%20b.png)", self.page("docs/IMG.md"))

    def test_staged_external_anchor_and_code_links_are_untouched(self):
        body = (
            "# Keep\n\n"
            "[guide](GUIDE.md) [guide2](GUIDE.md#sec) [up](../SPECS.md) "
            "[home](../README.md#top) [ext](https://example.com/a.py) "
            "[mail](mailto:a@example.com) [here](#local) [net](//example.com/x) "
            "[nope](../scripts/missing.py)\n\n"
            "`[code](../scripts/tool.py)`\n\n"
            "```\n[fenced](../scripts/tool.py)\n```\n"
        )
        write(self.root, "docs/KEEP.md", body)
        self.build()
        text = self.page("docs/KEEP.md")
        for kept in (
            "[guide](GUIDE.html)",
            "[guide2](GUIDE.html#sec)",
            "[up](../SPECS.html)",
            "[ext](https://example.com/a.py)",
            "[mail](mailto:a@example.com)",
            "[here](#local)",
            "[net](//example.com/x)",
            "[nope](../scripts/missing.py)",
            "`[code](../scripts/tool.py)`",
            "[fenced](../scripts/tool.py)",
        ):
            self.assertIn(kept, text)
        # README is staged as index.md, so its links follow it.
        self.assertIn("[home](../index.html#top)", text)
        self.assertNotIn("blob/main/scripts/tool.py", text)

    def test_liquid_syntax_survives_unrendered(self):
        body = (
            "# Liquid\n\nUse {{ site.title }} and {% if x %}y{% endif %}.\n\n"
            "A literal {% endraw %} tag, and {%- endraw -%} again.\n\n"
            "```\n{% include foo.html %}\n```\n"
        )
        write(self.root, "docs/LIQUID.md", body)
        self.build()
        text = self.page("docs/LIQUID.md")
        rendered = liquid_render(text.split("---\n", 2)[2])
        self.assertNotIn("<<LIQUID-LEAK>>", rendered)
        self.assertIn("Use {{ site.title }} and {% if x %}y{% endif %}.", rendered)
        self.assertIn("A literal {% endraw %} tag, and {%- endraw -%} again.", rendered)
        self.assertIn("{% include foo.html %}", rendered)

    def test_liquid_in_titles_is_safe(self):
        write(self.root, "docs/T.md", "# About {{ site.url }}\n\nx\n")
        self.build()
        listing = liquid_render(self.page("docs-index.md").split("---\n", 2)[2])
        self.assertNotIn("<<LIQUID-LEAK>>", listing)
        self.assertIn("About {{ site.url }}", listing)

    def test_every_page_has_front_matter_with_title(self):
        self.build()
        for rel in ("index.md", "docs/GUIDE.md", "docs-index.md"):
            text = self.page(rel)
            self.assertTrue(text.startswith("---\ntitle: "), rel)
            self.assertIn("\nlayout: default\n", text, rel)
        self.assertIn('title: "The Guide"', self.page("docs/GUIDE.md"))

    def test_existing_front_matter_is_preserved(self):
        write(
            self.root,
            "docs/FM.md",
            "---\nlayout: default\npermalink: /fm/\n---\n# FM Doc\n\nx\n",
        )
        self.build()
        text = self.page("docs/FM.md")
        self.assertTrue(text.startswith("---\n"))
        head, rest = text.split("\n---\n", 1)
        self.assertEqual(head.count("layout:"), 1)
        self.assertIn("permalink: /fm/", head)
        self.assertIn('title: "FM Doc"', head)
        self.assertIn("{% raw %}", rest)
        self.assertEqual(text.count("\n---\n"), 1)

    def test_crlf_sources_are_normalised(self):
        (self.root / "docs" / "CRLF.md").write_bytes(b"# Crlf\r\n\r\nbody\r\n")
        self.build()
        self.assertNotIn(b"\r", (self.out / "docs" / "CRLF.md").read_bytes())

    def test_titles_skip_fenced_headings(self):
        write(self.root, "docs/F.md", "```\n# not a title\n```\n\n# Real Title\n")
        self.build()
        self.assertIn("[Real Title](docs/F.html)", self.page("docs-index.md"))

    def test_untitled_page_falls_back_to_stem(self):
        write(self.root, "docs/no_heading.md", "just text\n")
        self.build()
        self.assertIn("[no_heading](docs/no_heading.html)", self.page("docs-index.md"))

    def test_builds_are_byte_identical_and_rebuild_clears_stale_files(self):
        self.build()
        first = read_tree(self.out)
        (self.out / "stale.md").write_text("x", encoding="utf-8")
        self.build()
        self.assertEqual(first, read_tree(self.out))
        other = self.root / "_site_src_b"
        site.build(other, root=self.root)
        self.assertEqual(first, read_tree(other))

    def test_missing_named_root_file_fails_closed(self):
        (self.root / "SPECS.md").unlink()
        with self.assertRaises(site.BuildError) as ctx:
            self.build()
        self.assertIn("SPECS.md", str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_new_docs_appear_automatically(self):
        write(self.root, "docs/freshly/ADDED.md", "# Added Later\n")
        self.build()
        self.assertIn(
            "[Added Later](docs/freshly/ADDED.html)", self.page("docs-index.md")
        )

    def test_refuses_dangerous_output_paths(self):
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        for bad in (
            outside,
            self.root,
            self.root.parent,
            self.root / "docs",
            self.root / "scripts",
            self.root / ".git",
        ):
            (self.root / ".git").mkdir(exist_ok=True)
            with self.assertRaises(site.BuildError, msg=str(bad)):
                site.build(bad, root=self.root)
        self.assertTrue((outside / "keep.txt").exists())
        self.assertTrue((self.root / "docs" / "GUIDE.md").exists())
        self.assertTrue((self.root / "README.md").exists())

    def test_refuses_output_that_is_a_file(self):
        target = self.root / "afile"
        target.write_text("x", encoding="utf-8")
        with self.assertRaises(site.BuildError):
            site.build(target, root=self.root)

    def test_denylisted_allowlist_entries_are_refused(self):
        with self.assertRaises(site.BuildError):
            site.check_not_denied("HANDOFF.md")
        with self.assertRaises(site.BuildError):
            site.check_not_denied("plans/ACTIVE.md")
        site.check_not_denied("docs/GUIDE.md")

    def test_root_symlink_is_rejected(self):
        secret = Path(self._tmp.name) / "external.md"
        secret.write_text("# External secret\n", encoding="utf-8")
        for name in ("README.md", "SPECS.md"):
            target = self.root / name
            target.unlink()
            symlink_or_skip(self, target, secret)
            with self.assertRaises(site.BuildError, msg=name) as ctx:
                self.build()
            self.assertIn(name, str(ctx.exception))
            self.assertFalse(self.out.exists())
            target.unlink()
            write(self.root, name, f"# {name}\n")

    def test_symlink_detection_does_not_need_symlink_privileges(self):
        import stat as stat_module

        real = os.lstat
        with mock.patch.object(
            site.os, "lstat", fake_lstat(real, "README.md", stat_module.S_IFLNK | 0o777)
        ):
            with self.assertRaises(site.BuildError):
                site.validate_source(self.root, "README.md")
        with mock.patch.object(
            site.os, "lstat", fake_lstat(real, "docs", attributes=0x400)
        ):
            with self.assertRaises(site.BuildError):
                site.validate_source(self.root, "docs/GUIDE.md")
        site.validate_source(self.root, "README.md")

    def test_root_symlink_to_excluded_doc_is_rejected(self):
        (self.root / "ROADMAP.md").unlink()
        symlink_or_skip(self, self.root / "ROADMAP.md", self.root / "HANDOFF.md")
        with self.assertRaises(site.BuildError):
            self.build()
        self.assertFalse(self.out.exists())

    def test_globbed_symlink_is_rejected(self):
        symlink_or_skip(self, self.root / "docs" / "LINK.md", self.root / "HANDOFF.md")
        with self.assertRaises(site.BuildError):
            self.build()
        self.assertFalse(self.out.exists())

    def test_symlinked_parent_component_is_rejected(self):
        elsewhere = Path(self._tmp.name) / "elsewhere"
        write(elsewhere, "X.md", "# X\n")
        symlink_or_skip(self, self.root / "docs" / "linked", elsewhere, directory=True)
        with self.assertRaises(site.BuildError):
            site.validate_source(self.root, "docs/linked/X.md")
        with self.assertRaises(site.BuildError):
            site.validate_source(self.root, "docs/linked")
        site.validate_source(self.root, "docs/GUIDE.md")

    def test_validate_source_requires_a_regular_file_inside_the_repo(self):
        with self.assertRaises(site.BuildError):
            site.validate_source(self.root, "docs")  # a directory
        with self.assertRaises(site.BuildError):
            site.validate_source(self.root, "docs/NOPE.md")  # missing
        with self.assertRaises(site.BuildError):
            site.validate_source(self.root, "../outside.md")
        with self.assertRaises(site.BuildError):
            site.validate_source(self.root, ".git/config")

    def test_untracked_and_ignored_docs_are_not_published(self):
        write(self.root, ".gitignore", "docs/private-corpus/\n")
        write(self.root, "docs/private-corpus/SECRET.md", "# Secret corpus\n")
        git_track_all(self.root)
        write(self.root, "docs/UNTRACKED.md", "# Untracked\n")
        staged = site.build(self.out, root=self.root)
        self.assertNotIn("docs/private-corpus/SECRET.md", staged)
        self.assertNotIn("docs/UNTRACKED.md", staged)
        self.assertIn("docs/GUIDE.md", staged)
        self.assertFalse((self.out / "docs" / "UNTRACKED.md").exists())
        # Judge by what is on disk, not by the builder's own return value.
        tree = read_tree(self.out)
        self.assertNotIn("docs/private-corpus/SECRET.md", tree)
        self.assertNotIn("docs/UNTRACKED.md", tree)
        self.assertNotIn("Secret corpus", "".join(v.decode() for v in tree.values()))

    def test_hidden_paths_are_not_published_even_when_tracked(self):
        write(self.root, "docs/.hidden/NOTES.md", "# Hidden dir\n")
        write(self.root, "docs/evals/.DRAFT.md", "# Hidden file\n")
        staged = self.build()
        self.assertNotIn("docs/.hidden/NOTES.md", staged)
        self.assertNotIn("docs/evals/.DRAFT.md", staged)
        self.assertIn("docs/evals/TAXONOMY.md", staged)
        tree = read_tree(self.out)
        self.assertNotIn("docs/.hidden/NOTES.md", tree)
        self.assertNotIn("docs/evals/.DRAFT.md", tree)
        self.assertNotIn("Hidden", self.page("docs-index.md"))
        self.assertIn("docs/evals/TAXONOMY.md", tree)

    def test_fails_closed_without_git(self):
        plain = make_repo(Path(self._tmp.name) / "plain")
        with self.assertRaises(site.BuildError):
            site.build(plain / "_site_src", root=plain)
        self.assertFalse((plain / "_site_src").exists())

    def test_cli_builds_into_out(self):
        git_track_all(self.root)
        out = self.root / "_site_cli"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--out", str(out)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((out / "index.md").is_file())

    def test_cli_fails_closed_on_missing_root_file(self):
        (self.root / "BOOK.md").unlink()
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.root),
                "--out",
                str(self.out),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("BOOK.md", proc.stderr)


BLOB = f"{REPO_URL}/blob/main/scripts/tool.py"
TOOL = "[x](../scripts/tool.py)"


class CodeAwareLinkTests(StageBase):
    """Links inside code, in every Markdown form, are never rewritten."""

    def doc(self, body, rel="docs/CODE.md"):
        write(self.root, rel, body)
        self.build()
        return self.page(rel)

    def test_indented_code_is_left_alone(self):
        text = self.doc(
            f"# I\n\nPara.\n\n    {TOOL}\n\nAfter [y](../scripts/tool.py).\n"
        )
        self.assertIn(f"\n    {TOOL}\n", text)
        self.assertIn(f"After [y]({BLOB}).", text)

    def test_indented_code_after_a_heading_and_tab_indent(self):
        text = self.doc(
            f"# I\n    {TOOL}\n\n## H\n\n\t{TOOL}\n\n[z](../scripts/tool.py)\n"
        )
        self.assertIn(f"    {TOOL}\n", text)
        self.assertIn(f"\t{TOOL}\n", text)
        self.assertIn(f"[z]({BLOB})", text)

    def test_four_space_continuation_of_a_paragraph_is_text(self):
        text = self.doc(f"# P\n\nA paragraph\n    still {TOOL} text\n")
        self.assertIn(f"still [x]({BLOB}) text", text)

    def test_multi_line_code_span_is_left_alone(self):
        text = self.doc(
            f"# M\n\nStart `code\n{TOOL}\nmore` then [y](../scripts/tool.py).\n"
        )
        self.assertIn(f"\n{TOOL}\nmore` then", text)
        self.assertIn(f"[y]({BLOB}).", text)

    def test_multi_line_double_backtick_span(self):
        text = self.doc(f"# M\n\n``a ` b\n{TOOL} c`` and {TOOL}\n")
        self.assertIn(f"\n{TOOL} c`` and [x]({BLOB})\n", text)

    def test_unclosed_backtick_is_literal_text(self):
        text = self.doc(f"# U\n\nA lone ` tick and {TOOL}\n\nNext {TOOL}\n")
        self.assertIn(f"tick and [x]({BLOB})", text)
        self.assertIn(f"Next [x]({BLOB})", text)

    def test_code_span_does_not_cross_a_paragraph_break(self):
        text = self.doc(f"# C\n\nopen ` here\n\n{TOOL} and `close`\n")
        self.assertIn(f"[x]({BLOB}) and `close`", text)

    def test_escaped_backticks_are_not_code(self):
        text = self.doc(f"# E\n\n\\`{TOOL}\\` and \\{TOOL}\n")
        self.assertIn(f"\\`[x]({BLOB})\\`", text)
        self.assertIn(f"\\{TOOL}", text)  # an escaped bracket is no link

    def test_table_rows_do_not_share_a_code_span(self):
        text = self.doc(
            f"# T\n\n| a | b |\n|---|---|\n| `x | {TOOL} |\n| y` | {TOOL} |\n"
        )
        self.assertEqual(text.count(BLOB), 2)

    def test_fence_inside_a_blockquote(self):
        text = self.doc(f"# Q\n\n> ```\n> {TOOL}\n> ```\n> after {TOOL}\n\n{TOOL}\n")
        self.assertIn(f"> {TOOL}\n", text)
        self.assertIn(f"> after [x]({BLOB})", text)
        self.assertEqual(text.count(BLOB), 2)

    def test_nested_blockquote_fence_and_lazy_continuation(self):
        text = self.doc(
            f"# Q\n\n> > ~~~\n> > {TOOL}\n> > ~~~\n> text `span\n> {TOOL}` end\n"
            f"lazy {TOOL}\n"
        )
        self.assertIn(f"> > {TOOL}\n", text)
        self.assertIn(f"> {TOOL}` end", text)
        self.assertIn(f"lazy [x]({BLOB})", text)

    def test_a_fence_ends_with_its_blockquote(self):
        text = self.doc(f"# Q\n\n> ```\n> {TOOL}\n{TOOL}\n")
        self.assertIn(f"> {TOOL}\n", text)
        self.assertIn(f"\n[x]({BLOB})\n", text)

    def test_content_after_an_invalid_closing_fence_stays_code(self):
        body = (
            "# F\n\n```python\n[a](../scripts/tool.py)\n```js\n"
            "[b](../scripts/tool.py)\n```\n[c](../scripts/tool.py)\n"
        )
        text = self.doc(body)
        self.assertIn("[a](../scripts/tool.py)", text)
        self.assertIn("[b](../scripts/tool.py)", text)
        self.assertIn(f"[c]({BLOB})", text)
        self.assertEqual(text.count(BLOB), 1)

    def test_fence_closer_must_match_character_and_length(self):
        text = self.doc(
            f"# F\n\n````\n```\n{TOOL}\n~~~~\n{TOOL}\n````\n\n"
            f"~~~\n{TOOL}\n```\n{TOOL}\n~~~~\n\n{TOOL}\n"
        )
        # Only the final link, after both fences really closed, is prose.
        self.assertEqual(text.count(BLOB), 1)
        self.assertEqual(text.count(TOOL), 4)

    def test_backtick_fence_info_string_cannot_contain_a_backtick(self):
        text = self.doc(f"# F\n\n``` a`b\n{TOOL}\n")
        self.assertIn(f"[x]({BLOB})", text)

    def test_unterminated_fence_runs_to_the_end(self):
        text = self.doc(f"# F\n\n```\n{TOOL}\n\n{TOOL}\n")
        self.assertNotIn(BLOB, text)

    def test_list_item_content(self):
        body = (
            "# L\n\n"
            f"- item `span\n  {TOOL}` end\n"
            f"- real {TOOL}\n\n"
            f"  ```\n  {TOOL}\n  ```\n\n"
            f"  continued {TOOL}\n\n"
            f"      indented code {TOOL}\n\n"
            f"1. one\n   ```\n   {TOOL}\n   ```\n"
            f"2. two {TOOL}\n"
        )
        text = self.doc(body)
        self.assertIn(f"  {TOOL}` end", text)
        self.assertIn(f"real [x]({BLOB})", text)
        self.assertIn(f"  ```\n  {TOOL}\n  ```", text)
        self.assertIn(f"continued [x]({BLOB})", text)
        self.assertIn(f"      indented code {TOOL}", text)
        self.assertIn(f"   {TOOL}\n   ```", text)
        self.assertIn(f"two [x]({BLOB})", text)
        self.assertEqual(text.count(BLOB), 3)

    def test_fence_in_a_list_item_nested_in_a_blockquote(self):
        text = self.doc(f"# L\n\n> - a\n>   ```\n>   {TOOL}\n>   ```\n> - b {TOOL}\n")
        self.assertIn(f">   {TOOL}\n", text)
        self.assertIn(f"- b [x]({BLOB})", text)

    def test_reference_definitions_in_code_are_left_alone(self):
        text = self.doc(
            "# R\n\n```\n[t]: ../scripts/tool.py\n```\n\n"
            "    [u]: ../scripts/tool.py\n\n[v]: ../scripts/tool.py\n"
        )
        self.assertIn("\n[t]: ../scripts/tool.py\n", text)
        self.assertIn("    [u]: ../scripts/tool.py", text)
        self.assertIn(f"[v]: {BLOB}", text)

    def test_reference_definition_inside_a_paragraph_is_text(self):
        text = self.doc("# R\n\nsome text\n[t]: ../scripts/tool.py\n")
        self.assertNotIn(BLOB, text)

    def test_link_text_may_contain_code_and_span_multiple_lines(self):
        text = self.doc(
            "# L\n\n[the `tool` and\nmore](../scripts/tool.py) [`k`](../scripts/tool.py)\n"
        )
        self.assertEqual(text.count(BLOB), 2)

    def test_headings_in_code_and_quotes_are_not_page_titles(self):
        write(self.root, "docs/T1.md", "    # indented\n\n> # quoted\n\n# Real\n")
        write(
            self.root,
            "docs/T2.md",
            "```\n# fenced\n```js\n# still fenced\n```\n\n# Real 2\n",
        )
        self.build()
        listing = self.page("docs-index.md")
        self.assertIn("[Real](docs/T1.html)", listing)
        self.assertIn("[Real 2](docs/T2.html)", listing)


class StagedLinkTests(StageBase):
    """Links between staged pages become relative .html links, computed here."""

    def doc(self, rel, body):
        write(self.root, rel, body)
        self.build()
        return self.page(rel)

    def test_links_to_staged_pages_become_relative_html(self):
        text = self.doc(
            "docs/evals/L.md",
            "# L\n\n[a](TAXONOMY.md) [b](../GUIDE.md#sec) [c](./TAXONOMY.md?x=1) "
            "[d](../../SPECS.md) [e](../../README.md#top) [f](<../GUIDE.md>) "
            '[g](../GUIDE.md "Guide")\n\n[h]: ../GUIDE.md#x\n',
        )
        for expected in (
            "[a](TAXONOMY.html)",
            "[b](../GUIDE.html#sec)",
            "[c](TAXONOMY.html?x=1)",
            "[d](../../SPECS.html)",
            "[e](../../index.html#top)",
            "[f](../GUIDE.html)",
            '[g](../GUIDE.html "Guide")',
            "[h]: ../GUIDE.html#x",
        ):
            self.assertIn(expected, text)

    def test_root_page_links_do_not_climb(self):
        text = self.doc(
            "BOOK.md", "# B\n\n[a](SPECS.md) [b](docs/GUIDE.md) [c](README.md)\n"
        )
        self.assertIn("[a](SPECS.html) [b](docs/GUIDE.html) [c](index.html)", text)

    def test_encoded_readme_links_resolve_to_index(self):
        text = self.doc(
            "docs/ENC.md",
            "# E\n\n[a](../%52EADME.md#top) [b](../README%2Emd) "
            "[c](%2E%2E/README.md?q=1#f) [d](../README.md)\n",
        )
        self.assertIn("[a](../index.html#top)", text)
        self.assertIn("[b](../index.html)", text)
        self.assertIn("[c](../index.html?q=1#f)", text)
        self.assertIn("[d](../index.html)", text)
        self.assertNotIn("%5", text)

    def test_encoded_staged_page_links_resolve(self):
        text = self.doc(
            "docs/ENC2.md", "# E\n\n[a](%47UIDE.md#s) [b](../docs/GUIDE.md)\n"
        )
        self.assertIn("[a](GUIDE.html#s)", text)
        self.assertIn("[b](GUIDE.html)", text)

    def test_root_relative_links_are_rebased(self):
        text = self.doc(
            "docs/evals/ROOT.md",
            "# R\n\n[a](/SPECS.md#x) [b](/README.md) [c](/docs/GUIDE.md) "
            "[d](/harness.py) [e](/scripts/) [f](/nope.md)\n\n[g]: /BOOK.md\n",
        )
        self.assertIn("[a](../../SPECS.html#x)", text)
        self.assertIn("[b](../../index.html)", text)
        self.assertIn("[c](../GUIDE.html)", text)
        self.assertIn(f"[d]({REPO_URL}/blob/main/harness.py)", text)
        self.assertIn(f"[e]({REPO_URL}/tree/main/scripts)", text)
        self.assertIn("[f](/nope.md)", text)
        self.assertIn("[g]: ../../BOOK.html", text)

    def test_root_relative_links_from_a_root_page(self):
        text = self.doc(
            "SPECS.md", "# S\n\n[a](/BOOK.md) [b](/README.md#r) [c](/docs/GUIDE.md)\n"
        )
        self.assertIn("[a](BOOK.html) [b](index.html#r) [c](docs/GUIDE.html)", text)

    def test_staged_links_in_code_stay_as_written(self):
        body = (
            "# C\n\n`[a](GUIDE.md)` and\n\n    [b](GUIDE.md)\n\n```\n[c](/SPECS.md)\n```\n"
            "\n> ```\n> [d](../README.md)\n> ```\n\n[real](GUIDE.md)\n"
        )
        text = self.doc("docs/C.md", body)
        for kept in (
            "`[a](GUIDE.md)`",
            "    [b](GUIDE.md)",
            "[c](/SPECS.md)",
            "[d](../README.md)",
        ):
            self.assertIn(kept, text)
        self.assertIn("[real](GUIDE.html)", text)

    def test_every_staged_relative_link_resolves_to_a_staged_page(self):
        write(
            self.root,
            "docs/evals/X.md",
            "# X\n\n[a](../GUIDE.md) [b](/README.md) [c](TAXONOMY.md)\n",
        )
        write(self.root, "BOOK.md", "# B\n\n[a](docs/evals/X.md) [b](/docs/GUIDE.md)\n")
        self.build()
        self.assertEqual(broken_staged_links(self.out), [])
        self.assertIn("docs/evals/X.md", read_tree(self.out))

    def test_the_link_checker_itself_notices_breakage(self):
        write(
            self.root,
            "docs/BAD.md",
            "# Bad\n\n[a](NOPE.html) [b](/SPECS.md) [c](GUIDE.md)\n",
        )
        self.build()
        (self.out / "docs" / "BAD.md").write_text(
            "[a](NOPE.html) [b](/SPECS.md) [c](GUIDE.md)\n", encoding="utf-8"
        )
        self.assertEqual(len(broken_staged_links(self.out)), 3)


def broken_staged_links(out):
    """Independent check: every relative link in staged pages names a staged page.

    Written against the Markdown text with its own naive code-stripping, not the
    stager's scanner. Returns a list of problems.
    """
    out = Path(out)
    pages = {p.relative_to(out).as_posix() for p in out.rglob("*.md")}
    problems = []
    for page in sorted(pages):
        body = (out / page).read_text(encoding="utf-8")
        body = re.sub(r"^(```|~~~).*?^\1\s*$", "", body, flags=re.S | re.M)
        body = re.sub(r"`[^`\n]*`", "", body)
        targets = re.findall(r"\]\(\s*<?([^)\s>]+)", body)
        targets += re.findall(r"^\[[^\]\n]+\]:[ \t]*<?(\S+?)>?\s*$", body, flags=re.M)
        for target in targets:
            if re.match(r"^([A-Za-z][A-Za-z0-9+.-]*:|//|#)", target):
                continue
            path = re.split(r"[?#]", target, maxsplit=1)[0]
            if not path:
                continue
            if path.startswith("/") or path.endswith(".md"):
                problems.append(f"{page}: {target}")
                continue
            if path.endswith(".html"):
                dest = posixpath.normpath(posixpath.join(posixpath.dirname(page), path))
                if dest[: -len(".html")] + ".md" not in pages:
                    problems.append(f"{page}: {target} -> {dest}")
    return problems


class GitBindingTests(StageBase):
    def track(self):
        git_track_all(self.root)

    def test_git_runs_bound_to_the_checkout_with_a_clean_environment(self):
        self.track()
        calls = []
        real_run = subprocess.run

        def spy(args, *a, **kw):
            calls.append((list(args), kw))
            return real_run(args, *a, **kw)

        with mock.patch.dict(os.environ, {"GIT_DIR": "x", "GIT_WORK_TREE": "y"}):
            with mock.patch.object(site.subprocess, "run", spy):
                site.build(self.out, root=self.root)
        self.assertGreaterEqual(len(calls), 2)
        for args, kw in calls:
            self.assertEqual(args[:3], ["git", "-C", str(self.root.resolve())])
            env = kw.get("env")
            self.assertIsNotNone(env)
            self.assertEqual([k for k in env if k.upper().startswith("GIT_")], [])

    def test_inherited_git_variables_cannot_redirect_the_listing(self):
        foreign = make_repo(
            Path(self._tmp.name) / "foreign", extra={"docs/FOREIGN.md": "# Foreign\n"}
        )
        git_track_all(foreign)
        self.track()
        poisoned = {
            "GIT_DIR": str(foreign / ".git"),
            "GIT_WORK_TREE": str(foreign),
            "GIT_INDEX_FILE": str(foreign / ".git" / "index"),
            "GIT_CEILING_DIRECTORIES": str(self.root.parent),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.worktree",
            "GIT_CONFIG_VALUE_0": str(foreign),
        }
        with mock.patch.dict(os.environ, poisoned):
            staged = site.build(self.out, root=self.root)
        tree = read_tree(self.out)
        self.assertIn("docs/GUIDE.md", tree)
        self.assertNotIn("docs/FOREIGN.md", tree)
        self.assertNotIn("docs/FOREIGN.md", staged)

    def test_root_must_be_the_repository_top_level(self):
        outer = Path(self._tmp.name) / "outer"
        inner = make_repo(outer / "sub")
        git(outer, "init", "-q")
        git(outer, "add", "-A")
        with self.assertRaises(site.BuildError) as ctx:
            site.build(inner / "_site_src", root=inner)
        self.assertIn("top level", str(ctx.exception))
        self.assertFalse((inner / "_site_src").exists())

    def test_gitlinks_are_not_published(self):
        self.track()
        git(
            self.root,
            "update-index",
            "--add",
            "--cacheinfo",
            "160000,0123456789abcdef0123456789abcdef01234567,docs/vendored.md",
        )
        staged = site.build(self.out, root=self.root)
        self.assertNotIn("docs/vendored.md", staged)
        self.assertNotIn("docs/vendored.md", read_tree(self.out))
        self.assertIn("docs/GUIDE.md", read_tree(self.out))

    def test_missing_git_executable_fails_closed(self):
        self.track()
        with mock.patch.object(
            site.subprocess, "run", side_effect=FileNotFoundError("git")
        ):
            with self.assertRaises(site.BuildError) as ctx:
                site.build(self.out, root=self.root)
        self.assertIn("git", str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_non_zero_toplevel_probe_fails_closed(self):
        self.track()

        def fake(args, *a, **kw):
            return subprocess.CompletedProcess(args, 128, b"", b"fatal: probe broke")

        with mock.patch.object(site.subprocess, "run", fake):
            with self.assertRaises(site.BuildError) as ctx:
                site.build(self.out, root=self.root)
        self.assertIn("128", str(ctx.exception))
        self.assertIn("probe broke", str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_non_zero_listing_fails_closed(self):
        self.track()
        real_run = subprocess.run

        def fake(args, *a, **kw):
            if "ls-files" in args:
                return subprocess.CompletedProcess(args, 1, b"", b"fatal: list broke")
            return real_run(args, *a, **kw)

        with mock.patch.object(site.subprocess, "run", fake):
            with self.assertRaises(site.BuildError) as ctx:
                site.build(self.out, root=self.root)
        self.assertIn("status 1", str(ctx.exception))
        self.assertIn("list broke", str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_a_corrupt_repository_fails_closed(self):
        broken = make_repo(Path(self._tmp.name) / "broken")
        (broken / ".git").mkdir()
        (broken / ".git" / "HEAD").write_text("garbage\n", encoding="utf-8")
        with self.assertRaises(site.BuildError):
            site.build(broken / "_site_src", root=broken)


class BuiltSiteCheckTests(unittest.TestCase):
    """`--check-site` verifies Jekyll's rendered HTML, the final published links."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "_site"

    def check_files(self, files, baseurl="/agent-harness"):
        for rel, text in files.items():
            write(self.dir, rel, text)
        return site.check_built_site(self.dir, baseurl)

    def test_valid_site_has_no_problems(self):
        problems = self.check_files(
            {
                "index.html": '<a href="docs/G.html#x">g</a><a href="/agent-harness/">h</a>'
                '<a href="https://example.com/a.md">e</a><a href="#top">t</a>'
                '<a href="mailto:a@b.c">m</a><img src="/agent-harness/assets/a.png">',
                "docs/G.html": '<a href="../index.html">i</a>'
                '<a href="/agent-harness/docs/G.html">s</a><a href="G.html#y">d</a>',
                "assets/a.png": "x",
            }
        )
        self.assertEqual(problems, [])

    def test_broken_and_unrebased_links_are_reported(self):
        problems = self.check_files(
            {
                "index.html": '<a href="missing.html">a</a><a href="/SPECS.html">b</a>'
                '<a href="docs/G.md">c</a><a href="/agent-harness/nope.html">d</a>',
                "docs/G.html": "",
            }
        )
        joined = "\n".join(problems)
        for needle in ("missing.html", "/SPECS.html", "docs/G.md", "nope.html"):
            self.assertIn(needle, joined)
        self.assertEqual(len(problems), 4)

    def test_links_may_not_escape_the_site(self):
        problems = self.check_files({"index.html": '<a href="../../etc/passwd">x</a>'})
        self.assertEqual(len(problems), 1)

    def test_cli_check_site(self):
        write(self.dir, "index.html", '<a href="gone.html">x</a>')
        cmd = [sys.executable, str(SCRIPT), "--check-site", str(self.dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("gone.html", proc.stderr)
        write(self.dir, "gone.html", "")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class WorkflowTests(unittest.TestCase):
    def test_workflow_watches_the_theme_on_push_and_pull_request(self):
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(
            encoding="utf-8"
        )
        for path in ("scripts/build_docs_site.py", "scripts/docs_site/**"):
            self.assertEqual(workflow.count(f'      - "{path}"\n'), 2, path)


class RealRepositoryTests(unittest.TestCase):
    def test_real_repository_stages_only_the_allowlist(self):
        out = ROOT / "_site_src" / f"test-{os.getpid()}"
        self.addCleanup(shutil.rmtree, out, True)
        staged = site.build(out, root=ROOT)
        tree = read_tree(out)
        extras = {"_config.yml", site.NAV_DATA, site.MARKER, *site.THEME_FILES}
        self.assertEqual(set(staged) | extras, set(tree))
        self.assertIn("index.md", tree)
        self.assertIn("docs-index.md", tree)
        for name in site.ROOT_DOCS.values():
            self.assertIn(name, tree)
        for rel in tree:
            self.assertFalse(
                rel.startswith(("docs/archive/", "docs/superpowers/")), rel
            )
        for name in (
            "HANDOFF.md",
            "HUMAN_TODO.md",
            "AGENTS.md",
            "CLAUDE.md",
            "MIGRATION_PROMPT.md",
            "AGENT_HARNESS_AGENT_BRIEF.md",
            "AGENT_HARNESS_OPERATIONS.md",
            "CLAUDE_CONFIG_OPERATIONS.md",
        ):
            self.assertNotIn(name, tree)
        self.assertEqual(broken_staged_links(out), [])
        for rel, data in tree.items():
            if rel.endswith(".md"):
                text = data.decode("utf-8")
                self.assertTrue(text.startswith("---\n"), rel)
                body = text.split("---\n", 2)[2]
                self.assertNotIn("<<LIQUID-LEAK>>", liquid_render(body), rel)


if __name__ == "__main__":
    unittest.main()
