"""Doctor's rule-2 model uses the selected product as its session cwd (#258)."""

from pathlib import Path
import unittest

import harness
import test_harness as fixtures


class DoctorDownwardCwdTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HarnessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def adapter(self):
        pin = harness.normalized_text_sha256(
            Path(harness.__file__).resolve().parent / "templates/hooks/dispatch.py"
        )
        return self.fixture.wrapper_adapter_text(
            pin, ".codex/invoke_deny_floor.sh", ".codex/invoke_deny_floor.ps1"
        )

    def test_product_relative_wrapper_matches_direct_product_inspection(self):
        checkout = self.fixture.make_repo()
        product = self.fixture.declare_logical_root(checkout / "products/app")
        self.fixture.write_hooks(product, self.adapter())
        for requested in (checkout, product):
            with self.subTest(requested=requested):
                code, output = self.fixture.run_doctor_with_fixture_globals(requested)
                self.assertEqual(code, 0, output)
                self.assertIn("[ok] project Codex floor: 1 project floor handler(s)", output)
                self.assertIn("only for sessions started in", output)
                self.assertIn(f"modeled session cwd: {product.resolve()}", output)

    def test_inherited_checkout_relative_wrapper_is_not_certified_for_product(self):
        checkout = self.fixture.make_repo()
        product = self.fixture.declare_logical_root(checkout / "products/app")
        self.fixture.write_hooks(checkout, self.adapter())
        for requested in (checkout, product):
            with self.subTest(requested=requested):
                code, output = self.fixture.run_doctor_with_fixture_globals(requested)
                self.assertEqual(code, 1, output)
                self.assertIn("[FAIL] project Codex floor: 0 project floor handler(s)", output)
                self.assertIn(f"session cwd {product.resolve()}", output)
                self.assertIn("session-cwd-relative wrapper", output)

    def test_linked_product_does_not_borrow_primary_checkout_relative_wrapper(self):
        checkout, linked = self.fixture.make_linked_worktree()
        primary_product = self.fixture.declare_logical_root(checkout / "products/app")
        linked_product = self.fixture.declare_logical_root(linked / "products/app")
        self.fixture.write_hooks(primary_product, self.adapter())
        self.fixture.write_hooks(linked_product, self.adapter())
        for requested in (linked, linked_product):
            with self.subTest(requested=requested):
                code, output = self.fixture.run_doctor_with_fixture_globals(requested)
                self.assertEqual(code, 1, output)
                self.assertIn("[FAIL] project Codex floor: 0 project floor handler(s)", output)
                self.assertIn(f"session cwd {linked_product.resolve()}", output)
                self.assertIn("session-cwd-relative wrapper", output)
