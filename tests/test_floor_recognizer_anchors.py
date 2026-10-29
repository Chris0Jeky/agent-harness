"""A static floor proof requires anchors the selected shell really expands."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

import harness


class FloorRecognizerAnchorTests(unittest.TestCase):
    pin = "a" * 64

    def certifies(self, body: str, *, windows: bool = False, reject=False) -> bool:
        marker = f"$expected='{self.pin}'" if windows else f"expected={self.pin}"
        return harness.platform_project_floor_command(
            f"{marker}; {body}",
            self.pin,
            windows=windows,
            reject_relative_wrapper=reject,
        )

    def test_dispatcher_bindings_use_only_expanding_platform_anchors(self):
        cases = (
            ("$HOME/.claude/hooks/dispatch.py", False, True),
            ('"${HOME}/.claude/hooks/dispatch.py"', False, True),
            ("~/.claude/hooks/dispatch.py", False, True),
            ("$env:USERPROFILE/.claude/hooks/dispatch.py", False, False),
            ("'$HOME/.claude/hooks/dispatch.py'", False, False),
            ('"~/.claude/hooks/dispatch.py"', False, False),
            (r"\$HOME/.claude/hooks/dispatch.py", False, False),
            (r"$HOME\.claude\hooks\dispatch.py", False, False),
            ("$home/.claude/hooks/dispatch.py", False, False),
            ('"$HOME/.CLAUDE/hooks/dispatch.py"', False, False),
            ("$HOME}/.claude/hooks/dispatch.py", False, False),
            ("${HOME/.claude/hooks/dispatch.py", False, False),
            ("$env:USERPROFILE/.claude/hooks/dispatch.py", True, False),
            ('"${env:USERPROFILE}/.claude/hooks/dispatch.py"', True, True),
            ("$HOME+'/.claude/hooks/dispatch.py'", True, True),
            ("Join-Path $env:USERPROFILE '.claude/hooks/dispatch.py'", True, True),
            (r'"$env:USERPROFILE\.claude\hooks\dispatch.py"', True, True),
            ("'$env:USERPROFILE/.claude/hooks/dispatch.py'", True, False),
            ('"~/.claude/hooks/dispatch.py"', True, False),
            (r"\$env:USERPROFILE/.claude/hooks/dispatch.py", True, False),
            ("`$env:USERPROFILE/.claude/hooks/dispatch.py", True, False),
        )
        for value, windows, expected in cases:
            with self.subTest(value=value, windows=windows):
                binding = f"$d={value}" if windows else f"d={value}"
                invocation = "py -3 $d" if windows else 'python3 "$d"'
                self.assertEqual(
                    self.certifies(
                        f"{binding}; {invocation} --event pre --runtime codex",
                        windows=windows,
                    ),
                    expected,
                )

    def test_system_interpreter_bindings_are_windows_only_and_not_literals(self):
        for value, expected in (
            ("$env:SystemRoot/py.exe", False),
            ('"$env:SystemRoot/py.exe"', True),
            ('"${env:windir}/py.exe"', True),
            ("$env:SystemRoot+'/py.exe'", True),
            ("Join-Path $env:SystemRoot 'py.exe'", True),
            ("'$env:SystemRoot/py.exe'", False),
            (r"\$env:SystemRoot/py.exe", False),
            ("`$env:SystemRoot/py.exe", False),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    self.certifies(
                        f"$p={value}; & $p -3 $env:USERPROFILE/.claude/hooks/dispatch.py "
                        "--event pre --runtime codex",
                        windows=True,
                    ),
                    expected,
                )
                self.assertFalse(
                    self.certifies(
                        f'p={value}; "$p" -3 "$HOME/.claude/hooks/dispatch.py" '
                        "--event pre --runtime codex"
                    )
                )

    def test_direct_dispatcher_operands_preserve_quote_and_escape_evidence(self):
        for operand, windows, expected in (
            ('"$HOME/.claude/hooks/dispatch.py"', False, True),
            ("~/.claude/hooks/dispatch.py", False, True),
            ("$HOME/.claude/hooks/dispatch.py", False, False),
            ("'$HOME/.claude/hooks/dispatch.py'", False, False),
            ('"~/.claude/hooks/dispatch.py"', False, False),
            (r"\$HOME/.claude/hooks/dispatch.py", False, False),
            (r"\~/.claude/hooks/dispatch.py", False, False),
            ('"$home/.claude/hooks/dispatch.py"', False, False),
            ('"$HOME/.claude/hooks/Dispatch.py"', False, False),
            ("$env:USERPROFILE/.claude/hooks/dispatch.py", False, False),
            ("$env:USERPROFILE/.claude/hooks/dispatch.py", True, True),
            ('"$env:USERPROFILE/.claude/hooks/dispatch.py"', True, True),
            ("'$env:USERPROFILE/.claude/hooks/dispatch.py'", True, False),
            (r"\$env:USERPROFILE/.claude/hooks/dispatch.py", True, False),
            ("`$env:USERPROFILE/.claude/hooks/dispatch.py", True, False),
        ):
            with self.subTest(operand=operand, windows=windows):
                interpreter = "py -3" if windows else "python3"
                self.assertEqual(
                    self.certifies(
                        f"{interpreter} {operand} --event pre --runtime codex",
                        windows=windows,
                    ),
                    expected,
                )

    def test_indirect_dispatcher_references_must_expand_as_one_operand(self):
        for operand, windows, expected in (
            ('"$d"', False, True),
            ("$d", False, False),
            ("'$d'", False, False),
            (r"\$d", False, False),
            ("$d", True, True),
            ('"$d"', True, True),
            ("'$d'", True, False),
            (r"\$d", True, False),
            ("`$d", True, False),
        ):
            with self.subTest(operand=operand, windows=windows):
                binding = (
                    "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'"
                    if windows
                    else "d=$HOME/.claude/hooks/dispatch.py"
                )
                interpreter = "py -3" if windows else "python3"
                self.assertEqual(
                    self.certifies(
                        f"{binding}; {interpreter} {operand} --event pre --runtime codex",
                        windows=windows,
                    ),
                    expected,
                )

    def test_wrapper_variables_must_expand_as_one_operand_from_every_cwd(self):
        for reject in (False, True):
            for operand, windows, expected in (
                ('"$w"', False, True),
                ("$w", False, False),
                ("'$w'", False, False),
                (r"\$w", False, False),
                ("$w", True, True),
                ('"$w"', True, True),
                ("'$w'", True, False),
                (r"\$w", True, False),
                ("`$w", True, False),
            ):
                with self.subTest(operand=operand, windows=windows, reject=reject):
                    body = (
                        "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                        '$w="$env:USERPROFILE/work/invoke_deny_floor.ps1"; '
                        f"powershell -File {operand}"
                        if windows
                        else "d=$HOME/.claude/hooks/dispatch.py; "
                        "w=$HOME/work/invoke_deny_floor.sh; "
                        f"sh {operand}"
                    )
                    self.assertEqual(
                        self.certifies(body, windows=windows, reject=reject), expected
                    )

    def test_later_quoted_argument_cannot_certify_an_escaped_script_operand(self):
        for body, windows in (
            (
                r"python3 \$HOME/.claude/hooks/dispatch.py --event pre --runtime codex "
                '"$HOME/.claude/hooks/dispatch.py"',
                False,
            ),
            (
                "d=$HOME/.claude/hooks/dispatch.py; python3 \\$d "
                '--event pre --runtime codex "$d"',
                False,
            ),
            (
                "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                '$p="$env:SystemRoot/py.exe"; & \\$p -3 $d '
                '--event pre --runtime codex "$p"',
                True,
            ),
            (
                "d=$HOME/.claude/hooks/dispatch.py; "
                'w=$HOME/work/invoke_deny_floor.sh; sh \\$w "$w"',
                False,
            ),
        ):
            with self.subTest(body=body, windows=windows):
                self.assertFalse(self.certifies(body, windows=windows, reject=True))

    def test_floor_variable_names_keep_the_selected_shells_case_rules(self):
        for windows in (False, True):
            for reference in ("$d", "$D"):
                with self.subTest(windows=windows, reference=reference):
                    body = (
                        "$D=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                        f"py -3 {reference} --event pre --runtime codex"
                        if windows
                        else "D=$HOME/.claude/hooks/dispatch.py; "
                        f'python3 "{reference}" --event pre --runtime codex'
                    )
                    self.assertEqual(
                        self.certifies(body, windows=windows),
                        windows or reference == "$D",
                    )

    def test_windows_native_operands_do_not_assume_tilde_expansion(self):
        for body in (
            "py -3 ~/.claude/hooks/dispatch.py --event pre --runtime codex",
            "& ~/.claude/hooks/dispatch.py --event pre --runtime codex",
            "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
            "powershell -File ~/work/invoke_deny_floor.ps1",
            "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
            "& ~/work/invoke_deny_floor.ps1",
        ):
            for reject in (False, True):
                with self.subTest(body=body, reject=reject):
                    self.assertFalse(self.certifies(body, windows=True, reject=reject))
        for body in (
            "python3 ~/.claude/hooks/dispatch.py --event pre --runtime codex",
            "d=$HOME/.claude/hooks/dispatch.py; sh ~/work/invoke_deny_floor.sh",
            "d=$HOME/.claude/hooks/dispatch.py; "
            'w=~/work/invoke_deny_floor.sh; sh "$w"',
        ):
            with self.subTest(body=body):
                self.assertTrue(self.certifies(body, reject=True))

    def test_windows_wrapper_bindings_are_resolved_strings(self):
        for value, expected, relative in (
            ("~/work/invoke_deny_floor.ps1", False, False),
            ('"~/work/invoke_deny_floor.ps1"', False, False),
            ("'~/work/invoke_deny_floor.ps1'", False, False),
            ("$env:USERPROFILE/work/invoke_deny_floor.ps1", False, False),
            (".codex/invoke_deny_floor.ps1", False, True),
            ('"$env:USERPROFILE/work/invoke_deny_floor.ps1"', True, False),
            ('"$HOME/work/invoke_deny_floor.ps1"', True, False),
            ("'.codex/invoke_deny_floor.ps1'", True, True),
        ):
            for reject in (False, True):
                with self.subTest(value=value, reject=reject):
                    body = (
                        "$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'; "
                        f"$w={value}; powershell -File $w"
                    )
                    self.assertEqual(
                        self.certifies(body, windows=True, reject=reject),
                        expected and not (relative and reject),
                    )

    def test_current_adapter_template_keeps_both_platforms_certified(self):
        template = (
            Path(harness.__file__).resolve().parent / "templates/codex/hooks.json"
        ).read_text(encoding="utf-8")
        self.assertEqual(len(harness.repo_codex_floor_groups(template, None)), 1)
        handler = json.loads(template)["hooks"]["PreToolUse"][0]["hooks"][0]
        for key, windows in (("command", False), ("commandWindows", True)):
            self.assertTrue(
                harness.platform_project_floor_command(
                    handler[key], None, windows=windows
                )
            )

    @unittest.skipUnless(os.name == "nt", "native Windows PowerShell parser")
    def test_windows_assignment_values_obey_native_expression_mode(self):
        executable = shutil.which("powershell.exe")
        self.assertIsNotNone(executable, "Windows conformance requires PowerShell")
        cases = (
            ('$d="$env:USERPROFILE/.claude/hooks/dispatch.py"', True),
            ("$d=$env:USERPROFILE+'/.claude/hooks/dispatch.py'", True),
            ("$d=Join-Path $env:USERPROFILE '.claude/hooks/dispatch.py'", True),
            ('$p="$env:SystemRoot/py.exe"', True),
            ("$d=$env:USERPROFILE/.claude/hooks/dispatch.py", False),
            ("$p=$env:SystemRoot/py.exe", False),
        )
        scripts = ",".join("'" + source.replace("'", "''") + "'" for source, _ in cases)
        command = (
            "$results = @(" + scripts + ") | ForEach-Object { "
            "$tokens=$null; $errors=$null; "
            "[void][System.Management.Automation.Language.Parser]::ParseInput("
            "$_,[ref]$tokens,[ref]$errors); $errors.Count -eq 0 }; "
            "ConvertTo-Json -Compress -InputObject @($results)"
        )
        result = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                base64.b64encode(command.encode("utf-16-le")).decode("ascii"),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [expected for _, expected in cases])


if __name__ == "__main__":
    unittest.main()
