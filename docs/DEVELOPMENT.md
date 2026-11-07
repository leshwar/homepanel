# Developing on your own computer

## One project folder, one folder per branch

```
~/Documents/homepanel/                 ← the main clone, always on `main` (git pull here)
├── data/                              ← settings and device keys for real-device runs (git-ignored)
└── .worktrees/                        ← one folder per branch (git-ignored)
    ├── ui-glass-look/
    └── feature-photo-frame/
```

Git *worktrees* let several branches be checked out at once, each in its own
folder, sharing one repository. You can run the demo of two branches side by side
and compare them, and switching tasks never needs a `git stash`.

### First time (macOS)

```bash
git clone https://github.com/leshwar/homepanel.git ~/Documents/homepanel
cd ~/Documents/homepanel
```

Install Docker Desktop, **open it once** (it installs its command-line tools on
first launch) and wait for "Engine running". `make docker-check` confirms it's
ready, and finds Docker even if `docker` isn't on your PATH yet.

### Everyday commands

| Task | Command (run in `~/Documents/homepanel`) |
|---|---|
| Update main | `git pull` |
| Start a change | `./scripts/dev/wt.sh new feature/my-change` (or `make wt-new b=feature/my-change`) |
| Go to its folder | `cd "$(./scripts/dev/wt.sh path feature/my-change)"` |
| Try someone's branch / PR | `./scripts/dev/wt.sh get ui/glass-look` |
| Run a branch's demo in Docker | `./scripts/dev/wt.sh demo ui/glass-look` → prints its URL (8081, 8082, …) |
| Run without Docker | inside the branch folder: `make setup` once, then `make dev` → http://localhost:8080 |
| Final validation | inside the branch folder: `make lint`, `REQUIRE_UI_TESTS=1 make test`, `make check-tests` |
| See all branch folders | `./scripts/dev/wt.sh list` |
| Clean up merged branches | `./scripts/dev/wt.sh prune` |

Then push the branch and open a pull request to `main` (see
[CI_AND_BRANCH_RULES.md](CI_AND_BRANCH_RULES.md)).

During development, run the smallest relevant test selection, not both full suites
after each edit. Run the complete unit/integration pass once when the final revision
is ready for merge; fix failures and rerun affected checks if code changes afterwards.
`make test` includes both suites, so do not follow it with `make test-unit` and
`make test-integration`. Required PR CI remains the merge gate, not an optional
replacement for checking the final code. See [tests/README.md](../tests/README.md).

An app-managed worktree is already an isolated branch folder. Work there directly
instead of creating another worktree or modifying the main clone.

### With Claude Code

The repo includes a skill, `.claude/skills/homepanel-dev/`, that teaches Claude
Code this workflow. Run `claude` inside `~/Documents/homepanel` and ask, for
example, "start a new branch for a Roku adapter" or "show me the demo of the
photo frame PR".
