"""Unit tests for the pull-request rule that requires unit and integration tests."""
import unittest

from scripts.ci.check_tests_included import is_code, missing_tests


class TestPolicy(unittest.TestCase):
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
