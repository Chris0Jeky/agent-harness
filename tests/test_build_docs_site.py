"""Contract tests for the GitHub Pages docs-site stager."""

import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

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
    for rel, text in (extra or {}).items():
        write(root, rel, text)
    return root


def read_tree(out):
    out = Path(out)
    return {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in sorted(out.rglob("*"))
        if p.is_file()
    }


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


class StageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo(Path(self._tmp.name) / "repo")
        self.out = self.root / "_site_src"

    def build(self, **kwargs):
        return site.build(self.out, root=self.root, **kwargs)

    def page(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def test_readme_becomes_index_with_nav(self):
        self.build()
        index = self.page("index.md")
        self.assertIn("# agent-harness", index)
        self.assertFalse((self.out / "README.md").exists())
        nav = (
            "[Home](index.md) · [Blueprint](BLUEPRINT.md) · [Specs](SPECS.md) · "
            "[Book](BOOK.md) · [Roadmap](ROADMAP.md) · [All documents](docs-index.md)"
        )
        self.assertIn(nav, index)

    def test_nav_links_are_relative_from_any_depth(self):
        self.build()
        self.assertIn("[Home](../index.md)", self.page("docs/GUIDE.md"))
        deep = self.page("docs/evals/TAXONOMY.md")
        self.assertIn("[Home](../../index.md)", deep)
        self.assertIn("[All documents](../../docs-index.md)", deep)

    def test_docs_index_lists_pages_grouped_by_folder(self):
        self.build()
        listing = self.page("docs-index.md")
        self.assertIn("# All documents", listing)
        self.assertIn("[The Guide](docs/GUIDE.md)", listing)
        self.assertIn("[Eval Taxonomy](docs/evals/TAXONOMY.md)", listing)
        self.assertIn("[Title of SPECS.md](SPECS.md)", listing)
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
        self.assertIn("theme: jekyll-theme-primer", config)
        for plugin in (
            "jekyll-relative-links",
            "jekyll-optional-front-matter",
            "jekyll-titles-from-headings",
            "jekyll-default-layout",
        ):
            self.assertIn(f"  - {plugin}\n", config)
        self.assertIn("relative_links:\n  enabled: true\n  collections: false", config)

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
            "[guide](GUIDE.md)",
            "[guide2](GUIDE.md#sec)",
            "[up](../SPECS.md)",
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
        self.assertIn("[home](../index.md#top)", text)
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
        self.assertIn('title: "The Guide"', self.page("docs/GUIDE.md"))

    def test_existing_front_matter_is_preserved(self):
        write(self.root, "docs/FM.md", "---\nlayout: default\n---\n# FM Doc\n\nx\n")
        self.build()
        text = self.page("docs/FM.md")
        self.assertTrue(text.startswith("---\n"))
        head, rest = text.split("\n---\n", 1)
        self.assertIn("layout: default", head)
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
        self.assertIn("[Real Title](docs/F.md)", self.page("docs-index.md"))

    def test_untitled_page_falls_back_to_stem(self):
        write(self.root, "docs/no_heading.md", "just text\n")
        self.build()
        self.assertIn("[no_heading](docs/no_heading.md)", self.page("docs-index.md"))

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
            "[Added Later](docs/freshly/ADDED.md)", self.page("docs-index.md")
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

    def test_cli_builds_into_out(self):
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


class RealRepositoryTests(unittest.TestCase):
    def test_real_repository_stages_only_the_allowlist(self):
        out = ROOT / "_site_src" / f"test-{os.getpid()}"
        self.addCleanup(shutil.rmtree, out, True)
        staged = site.build(out, root=ROOT)
        tree = read_tree(out)
        self.assertEqual(set(staged) | {"_config.yml", site.MARKER}, set(tree))
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
        for rel, data in tree.items():
            if rel.endswith(".md"):
                text = data.decode("utf-8")
                self.assertTrue(text.startswith("---\n"), rel)
                body = text.split("---\n", 2)[2]
                self.assertNotIn("<<LIQUID-LEAK>>", liquid_render(body), rel)


if __name__ == "__main__":
    unittest.main()
