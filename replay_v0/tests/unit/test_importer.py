"""Private transcript importer: extraction, scrubbing and the Git boundary."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from replay_v0 import cli as kernel
from replay_v0.importer import (
    Scrubber,
    build_private_corpus,
    claude_commands,
    codex_commands,
    output_is_private,
    write_corpus,
)

REPO = Path(__file__).resolve().parents[3]
HAS_GIT = shutil.which("git") is not None


def _write_jsonl(path: Path, records: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )


class ScrubberTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scrubber = Scrubber(["projectphoenix"])

    def test_credentials_are_replaced(self) -> None:
        # Assembled at runtime so this file holds no credential-shaped literal.
        samples = [
            "gh" + "p_" + "A1b2" * 9,
            "github" + "_pat_" + "Z9" * 20,
            "s" + "k-" + "q" * 30,
            "AK" + "IA" + "Q" * 16,
            "ey" + "J" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12,
        ]
        for secret in samples:
            with self.subTest(prefix=secret[:4]):
                self.assertNotIn(secret, self.scrubber.scrub(f"use {secret} now"))

    def test_assignments_and_headers_are_redacted(self) -> None:
        text = self.scrubber.scrub(
            'API_TOKEN=abc123 curl -H "Authorization: Bearer abcdefghij" x'
        )
        self.assertIn("API_TOKEN=<redacted>", text)
        self.assertNotIn("abcdefghij", text)
        self.assertNotIn("abc123", text)

    def test_home_paths_emails_hosts_and_repos(self) -> None:
        text = self.scrubber.scrub(
            "cat C:\\Users\\someone\\notes /home/someone/x /Users/someone/y "
            "mail a.person@corp.example.net "
            "curl https://build.internal.corp/api https://example.com/ok "
            "gh pr view 3 --repo someorg/somerepo "
            "git clone git@github.com:someorg/somerepo.git"
        )
        self.assertNotIn("someone", text)
        self.assertNotIn("a.person", text)
        self.assertNotIn("internal.corp", text)
        self.assertIn("https://example.com/ok", text)
        self.assertNotIn("someorg", text)
        self.assertNotIn("somerepo", text)

    def test_flag_and_user_credentials_are_redacted(self) -> None:
        text = self.scrubber.scrub(
            "docker login -u me --password hunter2hunter2; tool --token abc123def; "
            "curl -u admin:S3cretPw https://example.com"
        )
        for secret in ("hunter2hunter2", "abc123def", "S3cretPw"):
            self.assertNotIn(secret, text)

    def test_a_home_name_with_a_space_is_fully_removed(self) -> None:
        scrubber = Scrubber(["Jane Doe", "Jane", "Doe"])
        text = scrubber.scrub(r"cd C:\Users\Jane Doe\repo")
        self.assertNotIn("Doe", text)
        self.assertNotIn("Jane", text)

    def test_identity_terms_do_not_shield_repos_or_emails(self) -> None:
        scrubber = Scrubber(["ownerlogin", "mail.example.net"])
        text = scrubber.scrub(
            "gh pr view 1 --repo ownerlogin/secretproject; "
            "git log --author someone@mail.example.net"
        )
        self.assertNotIn("secretproject", text)
        self.assertNotIn("someone", text)

    def test_private_hosts_lose_their_path_in_any_url_form(self) -> None:
        text = self.scrubber.scrub(
            "git clone ssh://git@code.private.corp/acme/secret.git; "
            "git clone git@code.private.corp:acme/secret.git; "
            "git fetch git://build.internal:9418/team/proj"
        )
        for private in ("private.corp", "acme", "secret", "build.internal", "proj"):
            self.assertNotIn(private, text)

    def test_url_scrub_keeps_the_following_command(self) -> None:
        text = self.scrubber.scrub(
            "curl https://private.corp/a;rm -rf /tmp/x && "
            "git clone git@buildhost:team/secret.git|wc"
        )
        self.assertIn(";rm -rf /tmp/x && ", text)
        self.assertIn("|wc", text)
        for private in ("private.corp", "buildhost", "team", "secret"):
            self.assertNotIn(private, text)

    def test_extra_terms_match_inside_joined_paths(self) -> None:
        text = self.scrubber.scrub("cd /src/ProjectPhoenix-app && ls xprojectphoenix")
        self.assertNotIn("phoenix", text.lower())

    def test_passphrase_and_attached_tool_passwords_are_redacted(self) -> None:
        cases = [
            ("deploy --passphrase hunter2hunter2", "hunter2hunter2"),
            ("deploy --passphrase=hunter2hunter2", "hunter2hunter2"),
            ("mysql -uroot -pS3cretPw db", "S3cretPw"),
            ("mysqldump -uroot -pS3cretPw db", "S3cretPw"),
            ("mysqladmin -uroot -pS3cretPw status", "S3cretPw"),
            ("mariadb -uroot -pS3cretPw db", "S3cretPw"),
            ("mariadb-dump -uroot -pS3cretPw db", "S3cretPw"),
            ("sshpass -p S3cretPw ssh deploy@example.com", "S3cretPw"),
            ("sshpass -pS3cretPw ssh deploy@example.com", "S3cretPw"),
            ("redis-cli -h example.com -a S3cretPw get mykey", "S3cretPw"),
        ]
        for command, secret in cases:
            with self.subTest(command=command):
                self.assertNotIn(secret, self.scrubber.scrub(command))
        self.assertEqual(
            self.scrubber.scrub("mysql -uroot -p db"), "mysql -uroot -p db"
        )

    def test_tilde_user_forms_are_redacted(self) -> None:
        for command in ("cat ~alice/notes", "cd ~alice"):
            with self.subTest(command=command):
                self.assertNotIn("alice", self.scrubber.scrub(command))
        self.assertEqual(
            self.scrubber.scrub("echo ~ ~+ ~- @~2 main~3"),
            "echo ~ ~+ ~- @~2 main~3",
        )

    def test_bare_private_hosts_are_redacted(self) -> None:
        cases = [
            ("ssh build.internal.corp", "build.internal.corp"),
            ("ssh -p 2222 deploy-box.lan", "deploy-box.lan"),
            ("ping db01.acme.net", "db01.acme.net"),
            ("docker pull registry.acme.io/team/img:1", "registry.acme.io"),
            ("scp a.txt files.acme.net:/srv/x", "files.acme.net"),
        ]
        for command, secret in cases:
            with self.subTest(command=command):
                self.assertNotIn(secret, self.scrubber.scrub(command))
        scp_text = self.scrubber.scrub("scp a.txt files.acme.net:/srv/x")
        self.assertIn("a.txt", scp_text)
        self.assertNotIn("/srv/x", scp_text)

    def test_scrub2_redis_attached_password_is_redacted(self) -> None:
        text = self.scrubber.scrub("redis-cli -h example.com -aS3cretPw get k")
        self.assertNotIn("S3cretPw", text)
        self.assertIn("-a<redacted>", text)

    def test_scrub2_digest_pinned_registry_is_redacted(self) -> None:
        digest = "a" * 64
        text = self.scrubber.scrub(
            f"docker pull registry.acme.io/team/img@sha256:{digest}"
        )
        self.assertNotIn("registry.acme.io", text)
        self.assertIn("@sha256:", text)

    def test_scrub2_ssh_destination_parsing(self) -> None:
        text = self.scrubber.scrub("ssh buildhost")
        self.assertNotIn("buildhost", text)
        text = self.scrubber.scrub("ssh -p 2222 deploy@buildhost uptime")
        self.assertNotIn("buildhost", text)
        self.assertIn("uptime", text)
        text = self.scrubber.scrub("ssh example-host.corp cat notes.txt")
        self.assertIn("cat notes.txt", text)
        text = self.scrubber.scrub("ssh -i key.pem build.corp")
        self.assertIn("-i key.pem", text)
        self.assertEqual(self.scrubber.scrub("ssh localhost"), "ssh localhost")

    def test_scrub2_single_label_scp_without_user(self) -> None:
        text = self.scrubber.scrub("scp a.txt buildhost:/srv/x")
        self.assertNotIn("buildhost", text)
        self.assertNotIn("/srv/x", text)
        self.assertIn("a.txt", text)
        text = self.scrubber.scrub("scp C:/x/a.txt example.com:/tmp")
        self.assertIn("C:/x/a.txt", text)

    def test_scrub2_mysql_port_flag_is_unchanged(self) -> None:
        self.assertEqual(
            self.scrubber.scrub("mysql -P3306 -uroot db"), "mysql -P3306 -uroot db"
        )

    def test_a_docker_login_server_is_redacted(self) -> None:
        for command in (
            "docker login registry.acme.io",
            "docker login -u bot registry.acme.io:5000",
            "podman login registry.acme.io",
        ):
            with self.subTest(command=command):
                self.assertNotIn("acme", self.scrubber.scrub(command))
        self.assertEqual(
            self.scrubber.scrub("docker login -u bot"), "docker login -u bot"
        )

    def test_login_private_ipv4_endpoints_are_redacted(self) -> None:
        scrubber = Scrubber([])
        cases = [
            ("docker login 10.0.0.5", "docker login <registry>", "10.0.0.5"),
            (
                "docker login 10.0.0.5:5000",
                "docker login <registry>",
                "10.0.0.5",
            ),
            (
                "podman login 192.168.1.10",
                "podman login <registry>",
                "192.168.1.10",
            ),
            (
                "podman login 192.168.1.10:5000",
                "podman login <registry>",
                "192.168.1.10",
            ),
        ]
        for command, expected, private in cases:
            with self.subTest(command=command):
                text = scrubber.scrub(command)
                self.assertEqual(text, expected)
                self.assertNotIn(private, text)

    def test_login_single_label_endpoints_are_redacted(self) -> None:
        scrubber = Scrubber([])
        cases = [
            ("docker login myregistry", "docker login <registry>"),
            ("docker login myregistry:5000", "docker login <registry>"),
            ("podman login myregistry", "podman login <registry>"),
            ("podman login myregistry:5000", "podman login <registry>"),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                text = scrubber.scrub(command)
                self.assertEqual(text, expected)
                self.assertNotIn("myregistry", text)

    def test_login_bracket_ipv6_endpoints_are_redacted(self) -> None:
        scrubber = Scrubber([])
        cases = [
            ("docker login [fd00::1]", "docker login <registry>"),
            ("docker login [fd00::1]:5000", "docker login <registry>"),
            ("podman login [fd00::1]", "podman login <registry>"),
            ("podman login [fd00::1]:5000", "podman login <registry>"),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                text = scrubber.scrub(command)
                self.assertEqual(text, expected)
                self.assertNotIn("fd00", text)

    def test_login_quoted_registries_are_redacted(self) -> None:
        scrubber = Scrubber([])
        cases = [
            (
                'docker login "10.0.0.5:5000"',
                'docker login "<registry>"',
                "10.0.0.5",
            ),
            (
                "docker login 'myregistry:5000'",
                "docker login '<registry>'",
                "myregistry",
            ),
            (
                'podman login "[fd00::1]:5000"',
                'podman login "<registry>"',
                "fd00",
            ),
        ]
        for command, expected, private in cases:
            with self.subTest(command=command):
                text = scrubber.scrub(command)
                self.assertEqual(text, expected)
                self.assertNotIn(private, text)

    def test_login_public_and_loopback_endpoints_are_preserved(self) -> None:
        scrubber = Scrubber([])
        for command in (
            "docker login example.com",
            "docker login example.com:5000",
            "docker login localhost",
            "docker login localhost:5000",
            "docker login 127.0.0.1",
            "docker login 127.0.0.1:5000",
            "docker login [::1]",
            "docker login [::1]:5000",
            "podman login localhost:5000",
            "podman login example.com:5000",
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), command)

    def test_login_missing_endpoint_and_flags_are_unchanged(self) -> None:
        scrubber = Scrubber([])
        for command in (
            "docker login",
            "docker login -u bot",
            "docker login --password-stdin",
            "docker login -u \"my user\"",
            "docker login --username 'my user'",
            "podman login",
            "podman login --password-stdin",
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), command)

    def test_login_option_values_do_not_become_endpoints(self) -> None:
        scrubber = Scrubber([])
        cases = [
            (
                "docker login -u bot 10.0.0.5:5000",
                "docker login -u bot <registry>",
                "10.0.0.5",
            ),
            (
                "docker login --username bot myregistry:5000",
                "docker login --username bot <registry>",
                "myregistry",
            ),
            (
                'docker login -u "my user" 10.0.0.5:5000',
                'docker login -u "my user" <registry>',
                "10.0.0.5",
            ),
            (
                "docker login --password-stdin myregistry:5000",
                "docker login --password-stdin <registry>",
                "myregistry",
            ),
            (
                "docker login --username=bot myregistry:5000",
                "docker login --username=bot <registry>",
                "myregistry",
            ),
            (
                "podman login -u bot myregistry",
                "podman login -u bot <registry>",
                "myregistry",
            ),
            (
                "docker  login   10.0.0.5:5000",
                "docker  login   <registry>",
                "10.0.0.5",
            ),
            (
                "docker login 10.0.0.5:5000; echo done",
                "docker login <registry>; echo done",
                "10.0.0.5",
            ),
        ]
        for command, expected, private in cases:
            with self.subTest(command=command):
                text = scrubber.scrub(command)
                self.assertEqual(text, expected)
                self.assertNotIn(private, text)

    def test_long_dotted_runs_scrub_in_linear_time(self) -> None:
        # #397: unbounded leading classes made this 8.5 s for 40,000 characters.
        for text in ("echo " + "x." * 20000, "echo " + "a-" * 20000 + "@"):
            started = time.perf_counter()
            self.scrubber.scrub(text)
            self.assertLess(time.perf_counter() - started, 2.0)

    def test_bounded_patterns_still_scrub_their_targets(self) -> None:
        text = self.scrubber.scrub(
            "curl -Lhttps://bot:S3cretPw@build.private.corp/x; "
            "mail jane.q.public.person.example.user@corp.example.net"
        )
        for private in ("S3cretPw", "private.corp", "corp.example.net"):
            self.assertNotIn(private, text)

    def test_documented_safe_commands_are_unchanged(self) -> None:
        for command in (
            "mkdir -p build/out",
            "ssh -p 2222 github.com",
            "psql -p 5432 -h localhost",
            "git -p log",
            "git reset HEAD~1",
            "cd ~/src",
            "python setup.py sdist",
            "ping 127.0.0.1",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.scrubber.scrub(command), command)


class ExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_claude_tool_uses(self) -> None:
        _write_jsonl(
            self.root / "claude" / "p" / "s.jsonl",
            [
                {
                    "timestamp": "2026-02-03T04:05:06.789Z",
                    "cwd": "/fictional/app",
                    "message": {
                        "content": [
                            {"type": "text", "text": "hi"},
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "git status"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file_path": "x"},
                            },
                        ]
                    },
                },
                "not an object",
            ],
        )
        with (self.root / "claude" / "p" / "s.jsonl").open("a") as handle:
            handle.write("{broken\n")
        stats: Counter[str] = Counter()
        found = list(claude_commands(self.root / "claude", stats))
        self.assertEqual(
            found, [("git status", "2026-02-03T04:05:06Z", "/fictional/app")]
        )
        self.assertEqual(stats["unparsed-lines"], 1)

    def test_codex_function_calls(self) -> None:
        call = {"type": "function_call", "name": "shell_command"}
        _write_jsonl(
            self.root / "codex" / "r.jsonl",
            [
                {"payload": {"type": "turn_context", "cwd": "/fictional/svc"}},
                {"payload": {**call, "arguments": json.dumps({"command": "ls -la"})}},
                {
                    "payload": {
                        **call,
                        "name": "shell",
                        "arguments": json.dumps({"command": ["bash", "-lc", "make"]}),
                    }
                },
                {
                    "payload": {
                        **call,
                        "name": "shell",
                        "arguments": json.dumps({"command": ["tool", "a b"]}),
                    }
                },
                {"payload": {**call, "arguments": "{"}},
            ],
        )
        stats: Counter[str] = Counter()
        found = [item[0] for item in codex_commands(self.root / "codex", stats)]
        self.assertEqual(found, ["ls -la", "make"])
        self.assertEqual(stats["codex-unparsed-calls"], 2)

    def test_corpus_is_scrubbed_deduplicated_and_loadable(self) -> None:
        commands = [
            ("ls /home/someone", "2026-01-01T00:00:00Z", None),
            ("ls /home/other", "2026-01-01T00:00:01Z", None),
            ("git status", "2026-01-01T00:00:02Z", None),
        ]
        events, cases, stats = build_private_corpus(
            [("claude", iter(commands))], Scrubber([])
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual({case["case_class"] for case in cases}, {"opaque"})
        output = self.root / "corpus"
        write_corpus(output, events, cases)
        loaded = kernel._load_charter_corpus(str(output))
        self.assertEqual(loaded.event_count, 2)
        self.assertEqual(loaded.events[0]["source"], "historical-redacted")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class GitBoundaryTests(unittest.TestCase):
    def test_output_inside_an_unignored_work_tree_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            self.assertFalse(output_is_private(repo / "corpus"))
            ignore = repo / ".gitignore"
            ignore.write_text("/corpus/events.jsonl\n", encoding="utf-8")
            self.assertFalse(output_is_private(repo / "corpus"))
            ignore.write_text("/corpus/\n", encoding="utf-8")
            self.assertTrue(output_is_private(repo / "corpus"))

    def test_output_outside_any_work_tree_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            if any((parent / ".git").exists() for parent in Path(tmp).parents):
                self.skipTest("temporary directory sits inside a Git work tree")
            self.assertTrue(output_is_private(Path(tmp) / "corpus"))

    def test_this_repository_ignores_private_corpora(self) -> None:
        for path in (".local/private-corpus", "examples/private-corpus"):
            with self.subTest(path=path):
                self.assertTrue(output_is_private(REPO / path))

    def test_no_private_corpus_is_tracked(self) -> None:
        tracked = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "*corpus-manifest.json"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        for name in tracked:
            manifest = json.loads((REPO / name).read_text(encoding="utf-8"))
            self.assertNotEqual(manifest.get("corpus_id"), "private-local", name)
        paths = subprocess.run(
            ["git", "-C", str(REPO), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertFalse([path for path in paths if "private-corpus/" in path])


if __name__ == "__main__":
    unittest.main()
