---
name: homepanel-dev
description: Use when working on HomePanel locally — isolated source worktrees, targeted tests, safe updates to the single native 8080 application, and requested pull requests.
---

# HomePanel development workflow

## Where things live

- The project folder is `$HOMEPANEL_HOME` (default `~/Documents/homepanel`). It is the
  main clone of https://github.com/leshwar/homepanel and **always stays on `main`**.
  Update it with `git -C "$HOMEPANEL_HOME" pull`; never commit there.
- Every branch gets its own folder under `$HOMEPANEL_HOME/.worktrees/<branch-with-dashes>`
  (git-ignored), created with `scripts/dev/wt.sh`. These are source/rollback copies,
  not extra user-facing app instances.
- The one native application runs on 8080 through its existing supervisor.
  Real-device settings stay in `$HOMEPANEL_HOME/data` (git-ignored).

If the project folder doesn't exist yet:

```bash
git clone https://github.com/leshwar/homepanel.git ~/Documents/homepanel
```

## Start a change

If the coding app already supplied an isolated worktree and feature branch, use
that worktree; do not create a second worktree or modify the main clone.

```bash
cd ~/Documents/homepanel
./scripts/dev/wt.sh new <type>/<short-name>      # e.g. feature/roku-adapter, fix/lg-volume, ui/remote-layout
cd "$(./scripts/dev/wt.sh path <type>/<short-name>)"
```

The new branch starts from the latest `origin/main`. Do all edits, tests and commits
inside that worktree folder.

## Check a branch or a pull request

```bash
./scripts/dev/wt.sh get ui/glass-look            # check out an existing branch in its own folder
```

Run `make setup` if the worktree lacks test dependencies, then focused tests.
When live deployment is authorized, update the existing native service with a
validated pinned revision and its existing data/log paths (see docs/DEVELOPMENT.md).
Do not launch a demo or another preview server. User-facing captures must be
from actual 8080 with its current profile/settings, never fabricated fixtures.

## Final validation before merge

Use targeted tests while developing. Once the final revision is ready, run inside
the worktree once (not after every edit or commit):

```bash
make lint
REQUIRE_UI_TESTS=1 make test   # unit + integration, including the browser
make check-tests      # app/ or web/ changes need a test in tests/unit AND tests/integration
```

Do not also run the individual full suites: `make test` already includes both.
Fix failures and rerun affected checks; revalidate behavior changed after this pass.
When a PR is requested, `git push -u origin <branch>` and open a PR to `main`. CI runs lint, unit tests,
integration tests (including native startup smoke) and the tests-included rule. Follow `CLAUDE.md` for
architecture rules.

## Clean up

```bash
./scripts/dev/wt.sh prune          # removes folders and local branches already merged into main
./scripts/dev/wt.sh remove <branch>  # removes one folder, keeps the branch
```
