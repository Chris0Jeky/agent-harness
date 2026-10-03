"""Fictional literal-command privacy regressions; no remote command executes."""

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from replay_v0.importer import (
    Scrubber,
    build_private_corpus,
    codex_commands,
    write_corpus,
)


class LiteralPrivacyEdgesTests(unittest.TestCase):
    def test_sftp_remote_paths_hide_only_private_destinations(self):
        scrubber = Scrubber([])
        for destination, expected in (
            ("buildhost:uploads", "<host>:<path>"),
            ("buildhost:uploads/logs", "<host>:<path>"),
            ("buildhost:/uploads/logs", "<host>:<path>"),
            ("buildhost:2222", "<host>:<path>"),
            ("buildhost:", "<host>:<path>"),
            ("10.2.3.4:uploads", "<ip>:<path>"),
            ("[fd00::2]:uploads/logs", "[<ip>]:<path>"),
            ("deploy@[fd00::2]:uploads", "deploy@[<ip>]:<path>"),
            ("deploy@buildhost:uploads", "deploy@<host>:<path>"),
        ):
            for quote in ("", "'", '"'):
                with self.subTest(destination=destination, quote=quote):
                    result = scrubber.scrub(f"sftp {quote}{destination}{quote}")
                    self.assertEqual(result, f"sftp {quote}{expected}{quote}")
                    self.assertEqual(scrubber.scrub(result), result)

    def test_sftp_option_paths_ports_and_public_destinations_are_preserved(self):
        scrubber = Scrubber([])
        for command in (
            "sftp -b batch/file -B 65536 -P 2222 example.com:uploads/logs",
            "sftp -i keys/id -F local/config -D local/server localhost:/uploads",
            "sftp 127.0.0.2:uploads",
            "sftp [::1]:uploads/logs",
            "sftp -b batch/file example.com",
            "sftp local/folder",
            "sftp ./local:path",
            r"sftp C:\local\file",
            "sftp C:/local/file",
            "sftp --unknown buildhost:uploads",
            "echo sftp buildhost:uploads",
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), command)
        self.assertEqual(
            scrubber.scrub(
                'sftp -b "batch/file name" -P 2222 -J jumpbox buildhost:uploads/logs'
            ),
            'sftp -b "batch/file name" -P 2222 -J <host> <host>:<path>',
        )

    def test_quoted_literal_ssh_executables_keep_command_boundaries(self):
        scrubber = Scrubber([])
        for executable in ('"ssh"', "'ssh'", '"ssh.exe"', '"/opt/tools dir/ssh"'):
            with self.subTest(executable=executable):
                self.assertEqual(
                    scrubber.scrub(f"{executable} -J jumpbox targetbox echo otherbox"),
                    f"{executable} -J <host> <host> echo otherbox",
                )
        for command, expected in (
            ('"ssh-keyscan" firstbox secondbox', '"ssh-keyscan" <host> <host>'),
            ('"sftp" -P 2222 buildhost:uploads', '"sftp" -P 2222 <host>:<path>'),
            ('"mosh" --port=60001 targetbox', '"mosh" --port=60001 <host>'),
            (
                'echo "ssh -J jumpbox targetbox"; "ssh" targetbox uptime',
                'echo "ssh -J jumpbox targetbox"; "ssh" <host> uptime',
            ),
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), expected)
        for command in (
            'echo "ssh" -J jumpbox targetbox',
            '"${TOOLS}/ssh" -J jumpbox targetbox',
            '"ssh" --unknown jumpbox targetbox',
            '"ssh" example.com echo targetbox',
        ):
            with self.subTest(control=command):
                self.assertEqual(scrubber.scrub(command), command)

    def test_credential_shaped_email_is_removed_before_specific_tokens(self):
        scrubber = Scrubber([])
        for prefix in ("ghp_", "github_pat_", "sk-proj-", "sk_test_"):
            with self.subTest(prefix=prefix):
                credential = prefix + "a" * 48
                self.assertEqual(
                    scrubber.scrub(f"mail {credential}@private.example.net"),
                    "mail <email>",
                )
                self.assertEqual(scrubber.scrub(f"echo {credential}"), "echo <token>")
        for command, expected in (
            ("git fetch git@buildhost:team/repo.git", "git fetch <host>:<path>"),
            (
                "curl https://deploy:password@private.example.net/path",
                "curl https://<host>/<path>",
            ),
            ("ssh deploy@targetbox uptime", "ssh deploy@<host> uptime"),
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), expected)

    def test_bracketed_dns_jump_is_explicitly_outside_literal_ipv6_grammar(self):
        self.assertEqual(
            Scrubber([]).scrub("ssh -J admin@[bastion.internal]:2222 appbox"),
            "ssh -J admin@[bastion.internal]:2222 <host>",
        )

    def test_new_literals_survive_persisted_corpus_and_fresh_kernel_load(self):
        commands = (
            "sftp buildhost:uploads/logs",
            '"ssh" -J jumpbox targetbox uptime',
            "mail ghp_" + "a" * 48 + "@private.example.net",
        )
        forbidden = (
            "buildhost",
            "uploads/logs",
            "jumpbox",
            "targetbox",
            "private.example.net",
        )
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
            for artifact in output.rglob("*"):
                if artifact.is_file():
                    text = artifact.read_text(encoding="utf-8")
                    for term in forbidden:
                        self.assertNotIn(term, text, str(artifact))
            loaded = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from replay_v0.cli import _load_charter_corpus; "
                    "import sys; print(_load_charter_corpus(sys.argv[1]).event_count)",
                    str(output),
                ],
                cwd=Path(__file__).resolve().parents[3],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(loaded.returncode, 0, loaded.stderr)
            self.assertEqual(loaded.stdout.strip(), "3")
