"""Bundle destination lookup catches aliases while target names are still absent."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest import mock

import harness
import test_harness as fixtures


class BundleDestinationLookupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def make(self, name, destinations):
        config, home, _bin, args = self.fixture.make_bundle_sync_fixture(name)
        home.mkdir()
        manifest = config / harness.SYNC_GLOBAL_BUNDLE_MANIFEST
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["bundles"]["muse-runtime"]["components"] = [
            {
                "kind": "tree",
                "source": "muse/recipes",
                "destination": {"root": "claude-home", "path": destination},
            }
            for destination in destinations
        ]
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        return config, home, args

    @staticmethod
    def insensitive_lookup(_anchor, longer, shorter):
        # Inject only the native directory-lookup boundary; all bundle parsing,
        # physical-identity checks, preflight ordering and transactions stay real.
        def names(parts):
            return tuple(part.rstrip(". ").casefold() for part in parts)

        return len(longer) >= len(shorter) and names(longer[: len(shorter)]) == names(
            shorter
        )

    def test_absent_colliding_destinations_refuse_before_recovery_or_live_writes(self):
        pairs = (
            ("Tools", "tools"),
            ("Tools", "tools/child"),
            ("tools/child", "Tools"),
            ("Tools", "Tools./child"),
            ("Tools ", "Tools/child"),
        )
        for index, paths in enumerate(pairs):
            for apply in (False, True):
                with self.subTest(paths=paths, apply=apply):
                    config, home, args = self.make(f"collision-{index}-{apply}", paths)
                    args.apply = apply
                    before = harness.tree_digest(config.parent)
                    with (
                        mock.patch.object(
                            harness, "skill_name_chains_alias", self.insensitive_lookup
                        ),
                        redirect_stdout(io.StringIO()),
                        self.assertRaisesRegex(
                            harness.HarnessError, "destinations overlap"
                        ),
                    ):
                        harness.sync_global(args)
                    self.assertEqual(before, harness.tree_digest(config.parent))
                    self.assertEqual([], list(home.iterdir()))

    def test_absent_recovery_spelling_alias_refuses_before_creating_backups(self):
        paths = (
            ".HARNESS-BACKUPS",
            ".harness-backups.",
            ".HARNESS-BACKUPS/sync-global-bundles/nested",
        )
        for index, path in enumerate(paths):
            for apply in (False, True):
                with self.subTest(path=path, apply=apply):
                    config, home, args = self.make(f"recovery-{index}-{apply}", (path,))
                    args.apply = apply
                    before = harness.tree_digest(config.parent)
                    with (
                        mock.patch.object(
                            harness, "skill_name_chains_alias", self.insensitive_lookup
                        ),
                        redirect_stdout(io.StringIO()),
                        self.assertRaisesRegex(
                            harness.HarnessError, "recovery.*overlap"
                        ),
                    ):
                        harness.sync_global(args)
                    self.assertEqual(before, harness.tree_digest(config.parent))
                    self.assertEqual([], list(home.iterdir()))

    def test_unavailable_native_lookup_refuses_without_creating_recovery(self):
        config, home, args = self.make("unavailable", ("Tools", "tools/child"))
        before = harness.tree_digest(config.parent)
        with (
            mock.patch.object(
                harness,
                "skill_name_chains_alias",
                side_effect=PermissionError("injected lookup unavailable"),
            ),
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(harness.HarnessError, "lookup unavailable"),
        ):
            harness.sync_global(args)
        self.assertEqual(before, harness.tree_digest(config.parent))
        self.assertEqual([], list(home.iterdir()))

    def native_overlap(self, home, paths):
        # This independent oracle creates the requested spellings, observes
        # their identities, and then removes all fixture entries before sync.
        probe = home / ".fixture-native-lookup"
        probe.mkdir()
        left, right = (probe / path for path in paths)
        try:
            left.mkdir(parents=True)
            right.mkdir(parents=True, exist_ok=True)
            return any(
                candidate.samefile(outer)
                for inner, outer in ((left, right), (right, left))
                for candidate in (inner, *inner.parents)
            )
        finally:
            shutil.rmtree(probe)

    def test_absent_targets_follow_native_lookup_and_remove_transient_probes(self):
        pairs = (
            ("Tools", "tools"),
            ("Tools", "tools/child"),
            ("tools/child", "Tools"),
            ("Tools", "Tools./child"),
            ("caf\u00e9", "cafe\u0301/child"),
        )
        for index, paths in enumerate(pairs):
            for apply in (False, True):
                with self.subTest(paths=paths, apply=apply):
                    config, home, args = self.make(f"native-{index}-{apply}", paths)
                    before_source = harness.tree_digest(config)
                    overlaps = self.native_overlap(home, paths)
                    args.apply = apply
                    with redirect_stdout(io.StringIO()):
                        if overlaps:
                            with self.assertRaisesRegex(
                                harness.HarnessError, "overlap"
                            ):
                                harness.sync_global(args)
                        else:
                            self.assertEqual(0, harness.sync_global(args))
                    self.assertEqual(before_source, harness.tree_digest(config))
                    self.assertEqual([], list(home.rglob(".harness-name-probe-*")))
                    if overlaps or not apply:
                        self.assertEqual([], list(home.iterdir()))
                    else:
                        for path in paths:
                            self.assertEqual(
                                b"new recipe\n",
                                (home / path / "review.md").read_bytes(),
                            )

    @unittest.skipUnless(os.name == "nt", "native per-directory NTFS case sensitivity")
    def test_native_case_sensitive_home_keeps_distinct_absent_targets(self):
        _config, home, args = self.make("native-sensitive", ("Tools", "tools/child"))
        try:
            harness.skill_directory_case_sensitive(home, True)
        except harness.HarnessError as exc:
            self.skipTest(f"per-directory case sensitivity unavailable: {exc}")
        self.assertFalse(self.native_overlap(home, ("Tools", "tools/child")))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, harness.sync_global(args))
        for path in ("Tools", "tools/child"):
            self.assertEqual(b"new recipe\n", (home / path / "review.md").read_bytes())
