"""Fictional regression fixtures for contextual importer identities."""

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

from replay_v0 import cli as kernel
from replay_v0.importer import (
    Scrubber,
    build_private_corpus,
    codex_commands,
    write_corpus,
)


class ContextualPrivacyTests(unittest.TestCase):
    def test_gh_repository_value_options(self):
        scrubber = Scrubber([])
        for verb, long, short in (
            ("sync", "--source", "-s"),
            ("create", "--template", "-p"),
        ):
            for option in (
                f"{long} acme-private/secret-template",
                f'{long} "acme-private/secret-template"',
                f"{long}=acme-private/secret-template",
                f"{short}acme-private/secret-template",
                f'{short}"acme-private/secret-template"',
                f"{short}=acme-private/secret-template",
            ):
                for before in (True, False):
                    command = (
                        f"gh repo {verb} {option} secret-proj"
                        if before
                        else f"gh repo {verb} secret-proj {option}"
                    )
                    with self.subTest(command=command):
                        result = scrubber.scrub(command)
                        self.assertNotIn("acme-private", result)
                        self.assertNotIn("secret-template", result)
                        self.assertIn("<owner>/<repo>", result)
        self.assertEqual(
            scrubber.scrub('gh "repo" "view" "acme-private/secret-proj"'),
            'gh "repo" "view" "<owner>/<repo>"',
        )
        self.assertEqual(
            scrubber.scrub(
                "gh repo create -cpacme-private/secret-template secret-proj"
            ),
            "gh repo create -cp<owner>/<repo> <repo>",
        )
        self.assertEqual(
            scrubber.scrub(
                "gh repo fork acme-private/secret-proj --org fictional-org --fork-name secret-fork"
            ),
            "gh repo fork <owner>/<repo> --org <owner> --fork-name <repo>",
        )

    def test_gh_controls_and_chains(self):
        scrubber = Scrubber([])
        for command in (
            "gh repo create --source local/folder",
            'gh repo view --template "{{.name}}"',
            'gh repo view --template "a/b; c/d"',
            'gh repo view --template "a\\"b/c"',
            "gh repo fork -- --org fictional-org",
            "gh repo sync -- --source acme-private/secret-proj",
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), command)
        self.assertEqual(
            scrubber.scrub(
                "gh repo sync --source acme-private/secret-proj && gh repo create secret-proj -p acme-private/secret-template"
            ),
            "gh repo sync --source <owner>/<repo> && gh repo create <repo> -p <owner>/<repo>",
        )

    def test_repository_values_survive_extraction_write_and_kernel_load(self):
        commands = (
            "gh repo sync --source acme-private/secret-proj",
            "gh repo create secret-proj --template acme-private/secret-template",
        )
        self.assert_private_roundtrip(
            commands, ("acme-private", "secret-proj", "secret-template")
        )

    def assert_private_roundtrip(self, commands, forbidden):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            records = [
                {
                    "payload": {
                        "type": "function_call",
                        "name": "shell_command",
                        "arguments": json.dumps({"command": command}),
                    }
                }
                for command in commands
            ]
            (source / "fictional.jsonl").write_text(
                "\n".join(json.dumps(record) for record in records), encoding="utf-8"
            )
            events, cases, _ = build_private_corpus(
                [("codex", codex_commands(source, Counter()))], Scrubber([])
            )
            output = root / "corpus"
            write_corpus(output, events, cases)
            loaded = kernel._load_charter_corpus(str(output))
            self.assertEqual(loaded.event_count, len(commands))
            for artifact in output.rglob("*"):
                if artifact.is_file():
                    text = artifact.read_text(encoding="utf-8")
                    for term in forbidden:
                        self.assertNotIn(term, text, str(artifact))
            for event in loaded.events:
                for term in forbidden:
                    self.assertNotIn(term, event["command"])
