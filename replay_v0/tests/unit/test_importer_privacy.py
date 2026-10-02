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

    def test_keyscan_all_hosts_and_option_roles(self):
        scrubber = Scrubber([])
        cases = (
            (
                "ssh-keyscan -t rsa firstbox secondbox",
                "ssh-keyscan -t rsa <host> <host>",
            ),
            (
                "ssh-keyscan -46 -p 2222 -T 10 -f hosts.txt -O hashalg=sha256 firstbox,10.2.3.4 example.com",
                "ssh-keyscan -46 -p 2222 -T 10 -f hosts.txt -O hashalg=sha256 <host>,<ip> example.com",
            ),
            ("ssh-keyscan -vrsa firstbox", "ssh-keyscan -vrsa firstbox"),
            (
                'ssh-keyscan -Ht rsa "[fd00::2]" secondbox',
                'ssh-keyscan -Ht rsa "[<ip>]" <host>',
            ),
            ("ssh-keyscan -- firstbox secondbox", "ssh-keyscan -- <host> <host>"),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), expected)

    def test_ssh_private_option_values_and_controls(self):
        scrubber = Scrubber([])
        cases = (
            (
                "ssh -J alice@jumpbox:2222,bob@[fd00::1]:33 targetbox uptime",
                "ssh -J alice@<host>:2222,bob@[<ip>]:33 <host> uptime",
            ),
            (
                'ssh -vJ"alice@jumpbox:2222,bob@[fd00::1]:33" targetbox uptime',
                'ssh -vJ"alice@<host>:2222,bob@[<ip>]:33" <host> uptime',
            ),
            (
                "ssh -o ProxyJump=jumpbox -o HostName=realbox -b 10.2.3.4 -B Ethernet targetbox uptime",
                "ssh -o ProxyJump=<host> -o HostName=<host> -b <ip> -B Ethernet <host> uptime",
            ),
            (
                'ssh -o "ProxyJump alice@jumpbox:33,bob@[fd00::2]:22" -oHostName=realbox -b10.2.3.4 targetbox cat notes.txt',
                'ssh -o "ProxyJump alice@<host>:33,bob@[<ip>]:22" -oHostName=<host> -b<ip> <host> cat notes.txt',
            ),
            ('ssh -o HostName="realbox" targetbox', 'ssh -o HostName="<host>" <host>'),
            (
                'ssh -o "BindAddress=10.2.3.4" targetbox',
                'ssh -o "BindAddress=<ip>" <host>',
            ),
            (
                "ssh -- alice@[fd00::3]:2222 echo targetbox",
                "ssh -- alice@[<ip>]:2222 echo targetbox",
            ),
            (
                'ssh -i "key name.pem" -o "RemoteCommand=echo a\\"b;c" targetbox uptime',
                'ssh -i "key name.pem" -o "RemoteCommand=echo a\\"b;c" <host> uptime',
            ),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), expected)
        for command in (
            "ssh -J none example.com",
            "ssh -o ProxyJump=none -o HostName=example.com -B Ethernet -b 127.0.0.1 example.com cat notes.txt",
            "ssh -J github.com:22,bob@[::1]:33 example.com",
            "ssh -c aes256-ctr -l deploy -p 2222 example.com echo otherbox",
            'ssh -o "UserKnownHostsFile=known hosts" example.com',
        ):
            with self.subTest(control=command):
                self.assertEqual(scrubber.scrub(command), command)

    def test_mosh_literal_option_roles(self):
        scrubber = Scrubber([])
        for option in (
            "--port=60001",
            '--port="60001"',
            "--port 60001",
            '--port "60001"',
            "-p60001",
            "-p 60001",
            '-p"60001"',
            "-p=60001",
            "-o",
            "-ap60001",
            "--server /opt/bin/mosh-server",
            '--ssh "ssh -i key.pem"',
            "--client /opt/bin/mosh-client",
            "--predict adaptive",
            "--family inet",
            "--experimental-remote-ip remote",
            "--bind-server any",
            "--bind-server ssh",
            "--no-init",
            "--ssh-pty",
        ):
            with self.subTest(option=option):
                self.assertEqual(
                    scrubber.scrub(f"mosh {option} targetbox cat notes.txt"),
                    f"mosh {option} <host> cat notes.txt",
                )
        for command, expected in (
            ("mosh --bind-server=10.2.3.4 targetbox", "mosh --bind-server=<ip> <host>"),
            (
                'mosh --bind-server "10.2.3.4" targetbox',
                'mosh --bind-server "<ip>" <host>',
            ),
            (
                "mosh -- targetbox --port=60001 && echo done",
                "mosh -- <host> --port=60001 && echo done",
            ),
        ):
            self.assertEqual(scrubber.scrub(command), expected)
        for command in (
            "mosh --port=60001 example.com cat notes.txt",
            'mosh -o --server /opt/bin/mosh-server --ssh "ssh -i key.pem" example.com',
            "mosh --unknown targetbox",
            "mosh --bind-server any example.com",
        ):
            self.assertEqual(scrubber.scrub(command), command)
        self.assert_private_roundtrip(
            (
                "mosh --port=60001 targetbox cat notes.txt",
                "mosh --bind-server=10.2.3.4 targetbox",
            ),
            ("targetbox", "10.2.3.4"),
        )

    def test_ssh_family_option_roles(self):
        scrubber = Scrubber([])
        cases = (
            ("sftp -J jumpbox targetbox", "sftp -J <host> <host>"),
            (
                "sftp -vJalice@jumpbox:22 -oHostName=realbox -b batch.txt -B 65536 -P 2222 targetbox",
                "sftp -vJalice@<host>:22 -oHostName=<host> -b batch.txt -B 65536 -P 2222 <host>",
            ),
            (
                'sftp -o "ProxyJump=alice@jumpbox:22,bob@[fd00::2]:33" targetbox',
                'sftp -o "ProxyJump=alice@<host>:22,bob@[<ip>]:33" <host>',
            ),
            (
                "ssh-copy-id -o HostName=realbox -oProxyJump=jumpbox -i key.pem -p 2222 targetbox",
                "ssh-copy-id -o HostName=<host> -oProxyJump=<host> -i key.pem -p 2222 <host>",
            ),
            ("ssh -p 2222 alice@[fd00::2] uptime", "ssh -p 2222 alice@[<ip>] uptime"),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), expected)
        for command in (
            "sftp -b batch.txt -B 65536 -P 2222 example.com",
            "ssh-copy-id -i key.pem -p 2222 example.com",
            "ssh -o BindInterface=Ethernet -B Ethernet example.com",
            'sftp -o "BindInterface Ethernet" example.com',
            "ssh-copy-id -o BindInterface=Ethernet example.com",
        ):
            with self.subTest(control=command):
                self.assertEqual(scrubber.scrub(command), command)
        self.assert_private_roundtrip(
            ("sftp -J jumpbox targetbox", "ssh-copy-id -o HostName=realbox targetbox"),
            ("jumpbox", "targetbox", "realbox"),
        )

    def test_login_endpoint_controls_and_quoted_chains(self):
        scrubber = Scrubber([])
        for tool in ("docker", "podman"):
            for endpoint in (
                "registrybox",
                "registrybox:5000",
                "10.2.3.4",
                "10.2.3.4:5000",
                "[fd00::2]",
                "[fd00::2]:5000",
            ):
                for option in (
                    "-u bot",
                    "--username=bot",
                    "-ubot",
                    "--password-stdin",
                    "--",
                ):
                    with self.subTest(tool=tool, endpoint=endpoint, option=option):
                        self.assertEqual(
                            scrubber.scrub(f'{tool} login {option} "{endpoint}"'),
                            f'{tool} login {option} "<registry>"',
                        )
            self.assertEqual(
                scrubber.scrub(f'{tool} login -u "a\\"b;c" registrybox && echo done'),
                f'{tool} login -u "a\\"b;c" <registry> && echo done',
            )
            for endpoint in ("example.com:5000", "127.0.0.1:5000", "[::1]:5000"):
                command = f"{tool} login --password-stdin {endpoint}"
                self.assertEqual(scrubber.scrub(command), command)

    def test_escaped_login_credentials_are_removed_before_generic_rules(self):
        scrubber = Scrubber([])
        for tool in ("docker", "podman"):
            for option in (
                '-p "private\\"credential;tail"',
                '--password "private\\"credential;tail"',
                '--password="private\\"credential;tail"',
                '-p"private\\"credential;tail"',
            ):
                with self.subTest(tool=tool, option=option):
                    result = scrubber.scrub(
                        f"{tool} login {option} registrybox && echo done"
                    )
                    for private in ("private", "credential", "tail", "registrybox"):
                        self.assertNotIn(private, result)
                    self.assertIn("&& echo done", result)
                    self.assertIn("<redacted>", result)

    def test_long_email_local_parts_are_scrubbed_as_a_whole(self):
        scrubber = Scrubber([])
        for local in ("a" * 32, "z" * 48, "a" * 128, "name.surname"):
            self.assertEqual(
                scrubber.scrub(f"mail {local}@private.example.net"), "mail <email>"
            )
        self.assertEqual(scrubber.scrub("echo " + "a" * 32), "echo <hex>")
        self.assertEqual(scrubber.scrub("echo " + "z" * 48), "echo <blob>")

    def test_digest_shape_and_username_roles_remain_deterministic(self):
        scrubber = Scrubber([])
        digest = "ab" * 32
        self.assertEqual(
            scrubber.scrub(f"docker pull example.com/team/app@sha256:{digest}"),
            "docker pull example.com/team/app@sha256:<hex>",
        )
        self.assertEqual(
            scrubber.scrub("git fetch git@sha256:secret/path"),
            "git fetch <host>:<path>",
        )
        for command, expected in (
            ("ssh deploy@targetbox uptime", "ssh deploy@<host> uptime"),
            (
                "ssh -J deploy@jumpbox:22 targetbox uptime",
                "ssh -J deploy@<host>:22 <host> uptime",
            ),
            (
                "docker login --username=deploy registrybox",
                "docker login --username=deploy <registry>",
            ),
            (
                "ssh -J deploy@example.com:22 targetbox uptime",
                "ssh -J <email>:22 <host> uptime",
            ),
        ):
            with self.subTest(command=command):
                self.assertEqual(scrubber.scrub(command), expected)
                self.assertEqual(scrubber.scrub(command), scrubber.scrub(command))
                self.assertEqual(scrubber.scrub(expected), expected)

    def test_endpoint_and_email_roundtrip(self):
        self.assert_private_roundtrip(
            (
                "ssh-keyscan -t rsa firstbox secondbox",
                "ssh -J alice@jumpbox:2222,bob@[fd00::2]:22 -o HostName=realbox -b 10.2.3.4 -B Ethernet targetbox uptime",
                'podman login -u "a\\"b;c" registrybox:5000 && echo done',
                "mail " + "a" * 32 + "@private.example.net",
                "mail " + "z" * 48 + "@private.example.net",
            ),
            (
                "firstbox",
                "secondbox",
                "jumpbox",
                "fd00::2",
                "realbox",
                "10.2.3.4",
                "targetbox",
                "registrybox",
                "private.example.net",
            ),
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
            self.assertEqual(
                loaded.event_count,
                len({Scrubber([]).scrub(command) for command in commands}),
            )
            for artifact in output.rglob("*"):
                if artifact.is_file():
                    text = artifact.read_text(encoding="utf-8")
                    for term in forbidden:
                        self.assertNotIn(term, text, str(artifact))
            for event in loaded.events:
                for term in forbidden:
                    self.assertNotIn(term, event["command"])
