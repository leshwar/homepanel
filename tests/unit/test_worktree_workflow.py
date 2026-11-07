"""Source worktrees remain available, but never launch a separate preview app."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/wt.sh"


class WorktreeWorkflowTests(unittest.TestCase):
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
                    "TEST_COMMON_DIR": str(self.root / ".git")}

    def run_demo(self):
        return subprocess.run(["bash", str(SCRIPT), "demo", "feature/example"], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_retired_demo_command_does_not_launch_python(self):
        python = self.worktree / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@"\n')
        python.chmod(0o755)
        result = self.run_demo()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical app at http://localhost:8080", result.stderr)
        self.assertNotIn("app.main", result.stdout)

    def test_source_worktree_path_lookup_still_works(self):
        result = subprocess.run(["bash", str(SCRIPT), "path", "feature/example"], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.worktree))
