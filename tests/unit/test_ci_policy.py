"""Unit tests for the pull-request rule that requires unit and integration tests."""
import unittest
from pathlib import Path

from scripts.ci.check_tests_included import is_code, missing_tests


class TestPolicy(unittest.TestCase):
    def test_native_pipeline_keeps_required_checks_and_source_artifact(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
        self.assertIn("needs: [lint, tests-included, unit, integration]", workflow)
        self.assertIn('python-version: ["3.11", "3.13"]', workflow)
        self.assertIn('REQUIRE_UI_TESTS: "1"', workflow)
        self.assertIn("git archive --format=tar.gz", workflow)
        self.assertNotIn("docker/", workflow)
        self.assertNotIn("docker build", workflow)
        self.assertNotIn("packages: write", workflow)

    def test_docs_only_needs_no_tests(self):
        self.assertEqual(missing_tests(["README.md", "docs/API.md", "scripts/install.sh", ".github/workflows/ci.yml"]), [])

    def test_code_without_tests_is_rejected(self):
        self.assertEqual(missing_tests(["app/adapters/tuya.py"]), ["unit", "integration"])

    def test_code_with_only_unit_tests_is_rejected(self):
        self.assertEqual(missing_tests(["web/js/app.js", "tests/unit/test_service.py"]), ["integration"])

    def test_code_with_both_kinds_passes(self):
        self.assertEqual(missing_tests(["app/core/service.py", "tests/unit/test_service.py",
                                        "tests/integration/test_api.py"]), [])

    def test_helpers_dont_count_as_tests(self):
        self.assertEqual(missing_tests(["app/main.py", "tests/unit/helpers.py", "tests/integration/__init__.py"]),
                         ["unit", "integration"])

    def test_what_counts_as_code(self):
        self.assertTrue(is_code("app/core/net.py"))
        self.assertTrue(is_code("web/app.css"))
        self.assertFalse(is_code("app/adapters/README.md"))
        self.assertFalse(is_code("docs/ARCHITECTURE.md"))


if __name__ == "__main__":
    unittest.main()
