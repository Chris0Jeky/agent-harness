"""A policy-root alias binds one real tree, not a mutable invocation path."""

from contextlib import contextmanager, redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

from replay_v0 import cli, policy_sources
from replay_v0.digests import sha256_tree
from replay_v0.tests.contract import test_cli as fixtures


class PolicyRootAliasTests(unittest.TestCase):
    def link(self, alias, target, *, directory=True):
        try:
            alias.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"host cannot create the required symlink: {exc}")

    @contextmanager
    def fixture(self):
        with fixtures.CliTests().fixture("same") as data:
            directory, corpus, recording, policy = data
            alias = directory / "policy-alias"
            self.link(alias, policy.parent)
            snapshots = directory / "snapshots"
            snapshots.mkdir()
            path = str(snapshots)
            with mock.patch.object(cli.tempfile, "gettempdir", return_value=path):
                yield directory, corpus, recording, policy, alias, snapshots

    def load(self, path):
        try:
            return cli._load_process_source(f"{sys.executable},{path}", 30.0)
        except (cli.ReplayInputError, OSError, RuntimeError) as exc:
            self.fail(f"readable aliased policy root was rejected: {exc}")

    def test_alias_and_direct_source_share_identity_and_decisions(self):
        with self.fixture() as data:
            directory, _corpus, _recording, policy, alias, snapshots = data
            before = sha256_tree(policy.parent)
            direct = self.load(policy)
            linked = self.load(alias / policy.name)
            self.assertEqual(direct.identity, linked.identity)
            bound_root = linked.source.policy_tree_binding[0]
            self.assertEqual(policy.parent.resolve(), bound_root)
            self.assertEqual(str(alias.absolute()), linked.source.cwd)
            self.assertEqual(policy.name, linked.source.argv[-1])
            direct_result = direct.source.evaluate(fixtures.EVENTS)
            linked_result = linked.source.evaluate(fixtures.EVENTS)
            self.assertFalse(direct_result.failures)
            self.assertEqual(direct_result, linked_result)
            self.assertEqual(before, sha256_tree(policy.parent))
            self.assertEqual([], list(snapshots.iterdir()))
            self.assertNotIn(str(directory), json.dumps(linked.identity))

    def test_cli_both_alias_sources_preserve_reproduction_and_report_identity(self):
        with self.fixture() as data:
            directory, corpus, recording, policy, alias, snapshots = data
            output = directory / "reports"
            args = fixtures.CliTests.replay_args(corpus, recording, policy, output)
            args[args.index("--baseline") + 1] = f"process:{sys.executable},{policy}"
            before = sha256_tree(policy.parent)
            with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
                self.assertEqual(0, cli.main(args))
                direct = (output / "run-manifest.json").read_bytes()
                linked = alias / policy.name
                reference = "process-json:" + json.dumps([sys.executable, str(linked)])
                args[args.index("--baseline") + 1] = reference
                args[args.index("--candidate") + 1] = reference
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    code = cli.main(args)
                self.assertEqual(0, code, stderr.getvalue())
                manifest = (output / "run-manifest.json").read_bytes()
                self.assertEqual(direct, manifest)
                markdown = (output / "report.md").read_text("utf-8")
                lines = markdown.splitlines()
                line = next(line for line in lines if line.startswith("    ["))
                reproduced = json.loads(line)
                self.assertEqual(args, reproduced[3 : 3 + len(args)])
                self.assertEqual(0, cli.main(reproduced[3:]))
                manifest = (output / "run-manifest.json").read_bytes()
                self.assertEqual(direct, manifest)
            self.assertEqual(before, sha256_tree(policy.parent))
            self.assertEqual([], list(snapshots.iterdir()))
            self.assertNotIn(str(alias), (output / "report.json").read_text("utf-8"))

    def test_retarget_after_binding_does_not_select_a_different_tree(self):
        with self.fixture() as data:
            directory, _corpus, _recording, policy, alias, snapshots = data
            captured = self.load(alias / policy.name)
            foreign = directory / "foreign"
            foreign.mkdir()
            (foreign / policy.name).write_text(
                fixtures.CliTests.policy_script("regression"), encoding="utf-8"
            )
            alias.unlink()
            self.link(alias, foreign)
            result = captured.source.evaluate(fixtures.EVENTS)
            self.assertFalse(result.failures)
            effects = [d["effect"] for d in result.decisions]
            self.assertEqual(["deny", "allow"], effects)
            retargeted = self.load(alias / policy.name)
            self.assertNotEqual(captured.identity, retargeted.identity)
            self.assertEqual([], list(snapshots.iterdir()))

    def test_changed_bound_tree_is_refused_before_process_execution(self):
        with self.fixture() as data:
            _directory, _corpus, _recording, policy, alias, snapshots = data
            loaded = self.load(alias / policy.name)
            policy.write_text(
                fixtures.CliTests.policy_script("regression"), encoding="utf-8"
            )
            with mock.patch.object(policy_sources, "_run_policy_process") as run:
                result = loaded.source.evaluate(fixtures.EVENTS)
            run.assert_not_called()
            codes = [failure.code for failure in result.failures]
            self.assertEqual(["process-input-changed"], codes)
            self.assertEqual([], list(snapshots.iterdir()))

    def test_file_symlink_keeps_lexical_filename_inside_resolved_root(self):
        with self.fixture() as data:
            directory, _corpus, _recording, policy, alias, snapshots = data
            outside = directory / "implementation.py"
            policy.rename(outside)
            self.link(policy, outside, directory=False)
            direct = self.load(policy)
            linked = self.load(alias / policy.name)
            self.assertEqual(policy.name, linked.source.argv[-1])
            bound_root = linked.source.policy_tree_binding[0]
            self.assertEqual(policy.parent.resolve(), bound_root)
            self.assertEqual(direct.identity, linked.identity)
            self.assertFalse(linked.source.evaluate(fixtures.EVENTS).failures)
            self.assertEqual([], list(snapshots.iterdir()))
            self.assertTrue(policy.is_symlink())

    @unittest.skipIf(
        os.name == "nt", "POSIX traversal follows the directory alias before '..'"
    )
    def test_parent_traversal_uses_the_filesystem_not_lexical_collapsing(self):
        with self.fixture() as data:
            directory, _corpus, _recording, policy, alias, snapshots = data
            inner = policy.parent / "inner"
            inner.mkdir()
            alias.unlink()
            self.link(alias, inner)
            (directory / policy.name).write_text(
                fixtures.CliTests.policy_script("regression"), encoding="utf-8"
            )
            direct = self.load(policy)
            linked = self.load(alias / ".." / policy.name)
            self.assertEqual(direct.identity, linked.identity)
            result = linked.source.evaluate(fixtures.EVENTS)
            self.assertFalse(result.failures)
            effects = [d["effect"] for d in result.decisions]
            self.assertEqual(["deny", "allow"], effects)
            self.assertEqual([], list(snapshots.iterdir()))

    @unittest.skipUnless(os.name == "nt", "requires native Windows path lookup")
    def test_windows_parent_traversal_rejects_the_selected_link_containing_tree(self):
        with self.fixture() as data:
            directory, corpus, recording, policy, alias, snapshots = data
            inner = policy.parent / "inner"
            inner.mkdir()
            alias.unlink()
            self.link(alias, inner)
            other = directory / policy.name
            other.write_text(
                fixtures.CliTests.policy_script("regression"), encoding="utf-8"
            )
            spelled = alias / ".." / policy.name
            # Establish the real host lookup independently of the replay loader.
            self.assertEqual(other.read_bytes(), spelled.read_bytes())
            self.assertEqual(directory.resolve(), spelled.parent.resolve(strict=True))
            before = sha256_tree(policy.parent)
            other_before = other.read_bytes()
            output = directory / "reports"
            args = fixtures.CliTests.replay_args(corpus, recording, spelled, output)
            stderr = io.StringIO()
            with (
                redirect_stderr(stderr),
                mock.patch.object(policy_sources, "_run_policy_process") as run,
            ):
                self.assertEqual(2, cli.main(args))
            run.assert_not_called()
            self.assertIn(
                "process executable or policy file could not be read",
                stderr.getvalue(),
            )
            self.assertNotIn(str(directory), stderr.getvalue())
            self.assertEqual(before, sha256_tree(policy.parent))
            self.assertEqual(other_before, other.read_bytes())
            self.assertTrue(alias.is_symlink())
            self.assertFalse(output.exists())
            self.assertEqual([], list(snapshots.iterdir()))

    def test_alias_outputs_are_rejected_before_either_source_launches(self):
        with self.fixture() as data:
            _directory, corpus, recording, policy, alias, snapshots = data
            before = sha256_tree(policy.parent)
            for root in (policy.parent, alias):
                for output in (root, root / "reports"):
                    with self.subTest(output=output):
                        args = fixtures.CliTests.replay_args(
                            corpus, recording, alias / policy.name, output
                        )
                        stderr = io.StringIO()
                        with (
                            redirect_stderr(stderr),
                            mock.patch.object(
                                policy_sources, "_run_policy_process"
                            ) as run,
                        ):
                            self.assertEqual(2, cli.main(args))
                        run.assert_not_called()
                        self.assertIn("output overlaps", stderr.getvalue())
            self.assertEqual(before, sha256_tree(policy.parent))
            self.assertEqual([], list(snapshots.iterdir()))

    def test_snapshot_overlap_still_rejects_alias_root_without_copy_or_launch(self):
        with self.fixture() as data:
            _directory, _corpus, _recording, policy, alias, _snapshots = data
            with mock.patch.object(cli.tempfile, "gettempdir", return_value=str(alias)):
                source = self.load(alias / policy.name).source
            before = sha256_tree(policy.parent)
            with mock.patch.object(policy_sources, "_run_policy_process") as run:
                result = source.evaluate(fixtures.EVENTS)
            run.assert_not_called()
            codes = [failure.code for failure in result.failures]
            self.assertEqual(["process-snapshot-overlaps-input"], codes)
            self.assertEqual(before, sha256_tree(policy.parent))

    def test_internal_directory_aliases_remain_unsupported(self):
        with self.fixture() as data:
            directory, corpus, recording, policy, alias, snapshots = data
            outside = directory / "outside"
            outside.mkdir()
            self.link(policy.parent / "internal-alias", outside)
            output = directory / "reports"
            args = fixtures.CliTests.replay_args(
                corpus, recording, alias / policy.name, output
            )
            stderr = io.StringIO()
            with (
                redirect_stderr(stderr),
                mock.patch.object(policy_sources, "_run_policy_process") as run,
            ):
                self.assertEqual(2, cli.main(args))
            run.assert_not_called()
            self.assertNotIn(str(directory), stderr.getvalue())
            self.assertFalse(output.exists())
            self.assertEqual([], list(snapshots.iterdir()))

    def test_resolution_failure_is_bounded_without_mutation(self):
        with self.fixture() as data:
            directory, corpus, recording, policy, alias, snapshots = data
            original_resolve = Path.resolve
            injected = []

            def fail_root(path, *args, **kwargs):
                if path == alias.absolute():
                    injected.append(path)
                    raise OSError(f"private path {directory}")
                return original_resolve(path, *args, **kwargs)

            output = directory / "reports"
            args = fixtures.CliTests.replay_args(
                corpus, recording, alias / policy.name, output
            )
            stderr = io.StringIO()
            with (
                redirect_stderr(stderr),
                mock.patch.object(
                    Path, "resolve", autospec=True, side_effect=fail_root
                ),
                mock.patch.object(policy_sources, "_run_policy_process") as run,
            ):
                self.assertEqual(2, cli.main(args))
            self.assertEqual([alias.absolute()], injected)
            run.assert_not_called()
            self.assertNotIn(str(directory), stderr.getvalue())
            self.assertFalse(output.exists())
            self.assertEqual([], list(snapshots.iterdir()))

    def test_broken_and_cyclic_root_links_fail_before_execution(self):
        for broken in (True, False):
            with self.subTest(broken=broken), self.fixture() as data:
                directory, corpus, recording, policy, alias, snapshots = data
                before = sha256_tree(policy.parent)
                alias.unlink()
                target = directory / "missing" if broken else alias
                self.link(alias, target)
                output = directory / "reports"
                args = fixtures.CliTests.replay_args(
                    corpus, recording, alias / policy.name, output
                )
                stderr = io.StringIO()
                with (
                    redirect_stderr(stderr),
                    mock.patch.object(policy_sources, "_run_policy_process") as run,
                ):
                    self.assertEqual(2, cli.main(args))
                run.assert_not_called()
                self.assertIn("replay input invalid:", stderr.getvalue())
                self.assertNotIn(str(directory), stderr.getvalue())
                self.assertEqual(before, sha256_tree(policy.parent))
                self.assertFalse(output.exists())
                self.assertEqual([], list(snapshots.iterdir()))

    def test_file_hash_and_tree_hash_use_the_same_resolved_parent(self):
        with self.fixture() as data:
            directory, _corpus, _recording, policy, alias, snapshots = data
            direct = self.load(policy)
            foreign = directory / "foreign"
            foreign.mkdir()
            (foreign / policy.name).write_text(
                fixtures.CliTests.policy_script("regression"), encoding="utf-8"
            )
            original_hash = cli.sha256_file
            bound_policy = policy.parent.resolve() / policy.name
            retargeted = []

            def retarget_at_hash(path):
                if not retargeted:
                    self.assertEqual(bound_policy, path)
                    alias.unlink()
                    self.link(alias, foreign)
                    retargeted.append(True)
                return original_hash(path)

            with mock.patch.object(cli, "sha256_file", side_effect=retarget_at_hash):
                linked = self.load(alias / policy.name)
            self.assertEqual([True], retargeted)
            self.assertEqual(direct.identity, linked.identity)
            result = linked.source.evaluate(fixtures.EVENTS)
            self.assertFalse(result.failures)
            effects = [d["effect"] for d in result.decisions]
            self.assertEqual(["deny", "allow"], effects)
            self.assertEqual([], list(snapshots.iterdir()))


if __name__ == "__main__":
    unittest.main()
