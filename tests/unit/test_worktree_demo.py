"""The branch demo helper launches native Python, without starting a real server."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/wt.sh"


class NativeWorktreeDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worktree = self.root / ".worktrees/feature-example"
        self.worktree.mkdir(parents=True)
        tools = self.root / "tools"
        tools.mkdir()
        git = tools / "git"
        git.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_COMMON_DIR"\n')
        git.chmod(0o755)
        self.env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                    "TEST_COMMON_DIR": str(self.root / ".git"), "HOMEPANEL_DEMO_PORT": "8097"}

    def run_demo(self):
        return subprocess.run(["bash", str(SCRIPT), "demo", "feature/example"], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_launches_worktree_python_with_isolated_native_demo_arguments(self):
        python = self.worktree / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@"\n')
        python.chmod(0o755)
        result = self.run_demo()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.worktree), result.stdout)
        self.assertIn("-m\napp.main\n--demo\n--debug\n--host\n127.0.0.1\n--port\n8097\n", result.stdout)

    def test_missing_environment_explains_setup_without_installing(self):
        result = self.run_demo()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Run make setup", result.stdout)
