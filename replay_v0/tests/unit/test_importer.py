"""Private transcript importer: extraction, scrubbing and the Git boundary."""

from __future__ import annotations

from collections import Counter
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from replay_v0 import cli as kernel
from replay_v0.importer import (
    Scrubber,
    build_private_corpus,
    claude_commands,
    codex_commands,
    output_is_private,
    run_import,
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

    def test_stripe_secret_and_restricted_keys_are_scrubbed(self) -> None:
        scrubber = Scrubber([])
        prefixes = [
            "s" + "k_" + "live" + "_",
            "s" + "k_" + "test" + "_",
            "r" + "k_" + "live" + "_",
            "r" + "k_" + "test" + "_",
        ]
        bodies = ["A" * 30, "A1b2" * 5, "Ab3_" * 5, "Ab3-" * 5]
        for prefix in prefixes:
            for body in bodies:
                with self.subTest(prefix=prefix, body=body):
                    token = prefix + body
                    self.assertEqual(
                        scrubber.scrub("deploy " + token), "deploy <token>"
                    )

    def test_slack_tokens_old_and_new_forms_are_scrubbed(self) -> None:
        scrubber = Scrubber([])
        prefixes = [
            "xa" + "pp-",
            "xo" + "xe-",
            "xo" + "xo-",
            "xo" + "xa-",
            "xo" + "xb-",
            "xo" + "xp-",
            "xo" + "xr-",
            "xo" + "xs-",
        ]
        bodies = ["A" * 30, "A1b2" * 5, "AbC-123-XyZ-4567"]
        for prefix in prefixes:
            for body in bodies:
                with self.subTest(prefix=prefix, body=body):
                    token = prefix + body
                    self.assertEqual(
                        scrubber.scrub("deploy " + token), "deploy <token>"
                    )

    def test_openai_preserved_and_safe_controls_unchanged(self) -> None:
        scrubber = Scrubber([])
        openai = "s" + "k-" + "q" * 30
        self.assertEqual(scrubber.scrub("deploy " + openai), "deploy <token>")
        for prefix in ["p" + "k_" + "live" + "_", "p" + "k_" + "test" + "_"]:
            with self.subTest(prefix=prefix):
                command = "deploy " + prefix + "A" * 30
                self.assertEqual(scrubber.scrub(command), command)
        short_tokens = [
            "s" + "k_" + "live" + "_" + "ABC123",
            "r" + "k_" + "test" + "_" + "abc",
            "xo" + "xe-" + "abc",
            "xa" + "pp-" + "abc",
        ]
        for token in short_tokens:
            with self.subTest(token=token):
                command = "deploy " + token
                self.assertEqual(scrubber.scrub(command), command)
        ordinary = [
            "deploy " + "s" + "k_" + "live" + " status",
            "deploy " + "xo" + "xe" + " check",
        ]
        for command in ordinary:
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), command)

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

    def test_gh_repo_positional_selectors_are_scrubbed(self) -> None:
        scrubber = Scrubber([])
        for subcommand in (
            "archive",
            "clone",
            "create",
            "new",
            "delete",
            "edit",
            "fork",
            "set-default",
            "sync",
            "unarchive",
            "view",
        ):
            for selector in (
                "acme-private/secret-proj",
                "'acme-private/secret-proj'",
                '"acme-private/secret-proj"',
            ):
                with self.subTest(subcommand=subcommand, selector=selector):
                    quote = selector[0] if selector[0] in "\"'" else ""
                    self.assertEqual(
                        scrubber.scrub(f"gh repo {subcommand} {selector}"),
                        f"gh repo {subcommand} {quote}<owner>/<repo>{quote}",
                    )

    def test_gh_repo_options_and_later_arguments_keep_their_roles(self) -> None:
        scrubber = Scrubber([])
        cases = (
            (
                "gh repo view --branch feature/topic acme-private/secret-proj --web",
                "gh repo view --branch feature/topic <owner>/<repo> --web",
            ),
            (
                "gh repo view -bfeature/topic --json name --jq '.name' acme-private/secret-proj",
                "gh repo view -bfeature/topic --json name --jq '.name' <owner>/<repo>",
            ),
            (
                'gh repo view --template "a/b; c/d" acme-private/secret-proj',
                'gh repo view --template "a/b; c/d" <owner>/<repo>',
            ),
            (
                "gh repo clone -u source/remote acme-private/secret-proj workspace/checkout -- --reference cache/repo",
                "gh repo clone -u source/remote <owner>/<repo> workspace/checkout -- --reference cache/repo",
            ),
            (
                "gh repo create --source src/project --private acme-private/secret-proj",
                "gh repo create --source src/project --private <owner>/<repo>",
            ),
            (
                "gh repo edit --description 'group/project' --enable-issues=false acme-private/secret-proj",
                "gh repo edit --description 'group/project' --enable-issues=false <owner>/<repo>",
            ),
            (
                "gh repo sync --branch=feature/topic acme-private/secret-proj",
                "gh repo sync --branch=feature/topic <owner>/<repo>",
            ),
            (
                "gh repo view -- acme-private/secret-proj",
                "gh repo view -- <owner>/<repo>",
            ),
            (
                "gh repo clone secret-proj workspace/checkout -- --reference cache/repo",
                "gh repo clone <repo> workspace/checkout -- --reference cache/repo",
            ),
            ("gh repo create --private secret-proj", "gh repo create --private <repo>"),
            (
                '"C:/fictional tools/gh.exe" repo view acme-private/secret-proj',
                '"C:/fictional tools/gh.exe" repo view <owner>/<repo>',
            ),
            (
                "echo done && gh repo view acme-private/secret-proj; gh repo clone acme-private/secret-proj workspace/checkout",
                "echo done && gh repo view <owner>/<repo>; gh repo clone <owner>/<repo> workspace/checkout",
            ),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), expected)

    def test_gh_repo_nonselectors_are_unchanged(self) -> None:
        scrubber = Scrubber([])
        for command in (
            "echo acme-private/secret-proj",
            "gh repo list group/project",
            "gh repo rename group/project",
            "gh repo gitignore view group/project",
            "gh repo view --branch feature/topic",
            "gh repo view --template 'group/project'",
            "gh repo fork -- --reference cache/repo",
            "gh repo create --source src/project --private",
            "gh repo set-default origin",
            "gh repo unknown group/project",
            "gh repo view --future-option group/project",
            'echo "gh repo view acme-private/secret-proj"',
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), command)

    def test_gh_repo_short_clusters_preserve_option_values(self) -> None:
        scrubber = Scrubber([])
        for option in ("-wbfeature/topic", "-wb feature/topic"):
            with self.subTest(option=option):
                self.assertEqual(
                    scrubber.scrub(f"gh repo view {option} acme-private/secret-proj"),
                    f"gh repo view {option} <owner>/<repo>",
                )
        for command in (
            "gh repo view -wbfeature/topic",
            "gh repo view -wb feature/topic",
            "gh repo view -wtgroup/project",
            "gh repo view -wt 'group/project'",
            "gh repo view -wx group/project acme-private/secret-proj",
            "gh repo view -wxbfeature/topic acme-private/secret-proj",
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), command)

    def test_gh_repo_urls_keep_existing_host_rules(self) -> None:
        scrubber = Scrubber([])
        for command, expected in (
            (
                "gh repo view https://github.com/acme-private/secret-proj",
                "gh repo view https://github.com/<owner>/<repo>",
            ),
            (
                "gh repo clone https://code.private.corp/acme-private/secret-proj workspace/checkout",
                "gh repo clone https://<host>/<path> workspace/checkout",
            ),
            (
                "gh repo view --template https://example.com/a/b",
                "gh repo view --template https://example.com/a/b",
            ),
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), expected)

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
            'docker login -u "my user"',
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

    def test_login_escaped_username_quotes_preserve_endpoint_redaction(self) -> None:
        scrubber = Scrubber([])
        usernames = (r'"build\"bot"', r"build\"bot", r"'build\bot'", r'"build\\"')
        for tool in ("docker", "podman"):
            for username in usernames:
                with self.subTest(tool=tool, username=username):
                    command = f"{tool} login -u {username} private.corp:5000"
                    self.assertEqual(
                        scrubber.scrub(command),
                        f"{tool} login -u {username} <registry>",
                    )

    def test_login_password_values_are_redacted(self) -> None:
        scrubber = Scrubber([])
        for tool in ("docker", "podman"):
            for option, expected in (
                ("-p private.password", "-p <redacted>"),
                ('-p "private password"', '-p "<redacted>"'),
                ("-p 'private password'", "-p '<redacted>'"),
                ("-pprivate.password", "-p<redacted>"),
                ("-p=private.password", "-p=<redacted>"),
                ("--password private.password", "--password <redacted>"),
                ("--password=private.password", "--password=<redacted>"),
            ):
                with self.subTest(tool=tool, option=option):
                    self.assertEqual(
                        scrubber.scrub(f"{tool} login {option} private.corp:5000"),
                        f"{tool} login {expected} <registry>",
                    )
            self.assertEqual(
                scrubber.scrub(f"{tool} login --password-stdin example.com"),
                f"{tool} login --password-stdin example.com",
            )

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

    def test_login_password_does_not_reach_private_corpus_events(self) -> None:
        commands = [
            (
                f"{tool} login -p private.password private.corp:5000",
                "2026-01-01T00:00:00Z",
                None,
            )
            for tool in ("docker", "podman")
        ]
        events, _, _ = build_private_corpus([("claude", iter(commands))], Scrubber([]))
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertNotIn("private.password", event["command"])
            self.assertNotIn("private.corp", event["command"])
            self.assertIn("-p <redacted>", event["command"])

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

    def test_gh_repo_selectors_do_not_reach_imported_corpus(self) -> None:
        _write_jsonl(
            self.root / "codex" / "fictional.jsonl",
            [
                {
                    "payload": {
                        "type": "function_call",
                        "name": "shell_command",
                        "arguments": json.dumps({"command": command}),
                    }
                }
                for command in (
                    "gh repo view acme-private/secret-proj --web",
                    "gh repo clone acme-private/secret-proj workspace/checkout",
                )
            ],
        )
        events, cases, _ = build_private_corpus(
            [("codex", codex_commands(self.root / "codex", Counter()))], Scrubber([])
        )
        output = self.root / "gh-corpus"
        write_corpus(output, events, cases)
        loaded = kernel._load_charter_corpus(str(output))
        self.assertEqual(loaded.event_count, 2)
        for event in loaded.events:
            self.assertIn("<owner>/<repo>", event["command"])
            self.assertNotIn("acme-private", event["command"])
            self.assertNotIn("secret-proj", event["command"])


class WriteCorpusAtomicityTests(unittest.TestCase):
    @unittest.skipUnless(HAS_GIT, "git is not installed")
    def test_file_only_ignore_rules_refuse_unignored_staging(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text(
            "/corpus/events.jsonl\n/corpus/cases.jsonl\n/corpus/corpus-manifest.json\n",
            encoding="utf-8",
        )
        output = self.root / "corpus"
        self.assertTrue(output_is_private(output))
        with self.assertRaisesRegex(OSError, "must be private"):
            write_corpus(output, *self._events_cases("private"))
        self.assertEqual(list(output.iterdir()), [])

    def test_staging_stays_within_private_output(self) -> None:
        output = self.root / "private-corpus"
        real_mkdtemp = tempfile.mkdtemp

        def check_staging(*args, **kwargs):
            self.assertEqual(Path(kwargs["dir"]), output)
            return real_mkdtemp(*args, **kwargs)

        with mock.patch(
            "replay_v0.importer.tempfile.mkdtemp", side_effect=check_staging
        ):
            write_corpus(output, *self._events_cases("private"))
        self.assertFalse(list(output.glob(".corpus-output-*")))

    def test_interrupt_restores_previous_corpus(self) -> None:
        output = self.root / "corpus"
        write_corpus(output, *self._events_cases("old"))
        before = {p.name: p.read_bytes() for p in output.iterdir()}
        real_replace = Path.replace

        def interrupt_publish(path, target):
            if path.parent.name == "staged":
                raise KeyboardInterrupt("synthetic cancellation")
            return real_replace(path, target)

        with mock.patch.object(Path, "replace", interrupt_publish):
            with self.assertRaises(KeyboardInterrupt):
                write_corpus(output, *self._events_cases("new"))
        self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
        self.assertFalse(list(output.glob(".corpus-output-*")))

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _events_cases(
        self, marker: str
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        event_id = f"imp-claude-{marker}"
        events = [
            {
                "schema_version": "command-event.v1",
                "event_id": event_id,
                "timestamp": "2026-01-01T00:00:00Z",
                "command": f"git status {marker}",
                "cwd": "project",
                "source": "historical-redacted",
            }
        ]
        cases = [
            {
                "schema_version": "charter-case.v1",
                "event_id": event_id,
                "case_class": "opaque",
                "case_family": "claude-git",
                "rationale": "Imported from a local transcript; not labelled.",
                "provenance": "historical-redacted",
            }
        ]
        return events, cases

    def test_write_corpus_atomic_on_failure(self) -> None:
        # Fresh output: a directory blocking cases.jsonl must leave no
        # partial new files behind.
        fresh = self.root / "fresh-corpus"
        fresh.mkdir()
        (fresh / "cases.jsonl").mkdir()
        events, cases = self._events_cases("new")
        with self.assertRaises(OSError):
            write_corpus(fresh, events, cases)
        self.assertFalse((fresh / "events.jsonl").is_file())
        self.assertFalse((fresh / "corpus-manifest.json").is_file())
        self.assertTrue((fresh / "cases.jsonl").is_dir())

        # Existing corpus: the failed second write must leave the old
        # events and manifest intact instead of replacing the first file
        # and leaving a stale/missing manifest.
        output = self.root / "corpus"
        old_events, old_cases = self._events_cases("old")
        write_corpus(output, old_events, old_cases)
        old_event_bytes = (output / "events.jsonl").read_bytes()
        old_manifest_bytes = (output / "corpus-manifest.json").read_bytes()
        (output / "cases.jsonl").unlink()
        (output / "cases.jsonl").mkdir()
        new_events, new_cases = self._events_cases("new")
        with self.assertRaises(OSError):
            write_corpus(output, new_events, new_cases)
        self.assertEqual((output / "events.jsonl").read_bytes(), old_event_bytes)
        self.assertNotIn(b"git status new", (output / "events.jsonl").read_bytes())
        self.assertEqual(
            (output / "corpus-manifest.json").read_bytes(), old_manifest_bytes
        )
        self.assertFalse(
            list((output.parent).glob(".corpus-output-*")),
            "staging directory was not cleaned up",
        )

    def test_write_corpus_manifest_shas(self) -> None:
        output = self.root / "sha-corpus"
        events, cases = self._events_cases("sha")
        write_corpus(output, events, cases)
        manifest = json.loads(
            (output / "corpus-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["corpus_id"], "private-local")
        self.assertEqual(manifest["event_count"], len(events))
        entries = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
        self.assertEqual(set(entries), {"events.jsonl", "cases.jsonl"})
        for name in ("events.jsonl", "cases.jsonl"):
            digest = hashlib.sha256((output / name).read_bytes()).hexdigest()
            self.assertEqual(entries[name], digest)
        loaded = kernel._load_charter_corpus(str(output))
        self.assertEqual(loaded.event_count, len(events))


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


class RunImportRedactTermsTests(unittest.TestCase):
    @staticmethod
    def _args(output: Path, redact_terms: Path) -> argparse.Namespace:
        return argparse.Namespace(
            output=str(output),
            redact_terms=str(redact_terms),
            claude_root="none",
            codex_root="none",
            keep_duplicates=False,
            limit=0,
            sample=0,
            seed=0,
        )

    def test_run_import_bad_redact_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            missing = tmpdir / "does-not-exist.txt"
            directory = tmpdir / "terms-dir"
            directory.mkdir()
            invalid = tmpdir / "invalid.txt"
            invalid.write_bytes(b"\xff\xfe\x00not-utf8")
            for label, bad in (
                ("missing", missing),
                ("directory", directory),
                ("invalid-utf8", invalid),
            ):
                with self.subTest(case=label):
                    diagnostic = io.StringIO()
                    with (
                        mock.patch(
                            "replay_v0.importer.output_is_private",
                            return_value=True,
                        ),
                        redirect_stdout(diagnostic),
                    ):
                        self.assertEqual(
                            2, run_import(self._args(tmpdir / "corpus", bad))
                        )
                    self.assertIn("import:", diagnostic.getvalue())


if __name__ == "__main__":
    unittest.main()
