---
name: homepanel-dev
description: Use when working on the HomePanel repo on a developer's machine — setting up the project folder, starting a new change on its own branch with a git worktree off main, trying a branch or PR in Docker, running tests, and opening a pull request.
---

# HomePanel development workflow

## Where things live

- The project folder is `$HOMEPANEL_HOME` (default `~/Documents/homepanel`). It is the
  main clone of https://github.com/leshwar/homepanel and **always stays on `main`**.
  Update it with `git -C "$HOMEPANEL_HOME" pull`; never commit there.
- Every branch gets its own folder under `$HOMEPANEL_HOME/.worktrees/<branch-with-dashes>`
  (git-ignored), created with `scripts/dev/wt.sh`. Several branches can be open and
  running at the same time.
- Docker files (`Dockerfile`, `docker-compose.yml`) are in the repo, so each worktree
  builds its own image. Real-device settings live in `$HOMEPANEL_HOME/data` (git-ignored).

If the project folder doesn't exist yet:

```bash
git clone https://github.com/leshwar/homepanel.git ~/Documents/homepanel
```

## Start a change

```bash
cd ~/Documents/homepanel
./scripts/dev/wt.sh new <type>/<short-name>      # e.g. feature/roku-adapter, fix/lg-volume, ui/remote-layout
cd "$(./scripts/dev/wt.sh path <type>/<short-name>)"
```

The new branch starts from the latest `origin/main`. Do all edits, tests and commits
inside that worktree folder.

## Try a branch or a pull request

```bash
./scripts/dev/wt.sh get ui/glass-look            # check out an existing branch in its own folder
./scripts/dev/wt.sh demo ui/glass-look           # Docker demo on a free port (8081, 8082, …)
```

Two branches can run side by side for comparison; each gets its own port and
Docker project name. Without Docker: `cd` into the worktree and `make setup && make dev`
(port 8080).

If `make docker-*` says Docker isn't running, open Docker Desktop (`open -a Docker`)
and wait for "Engine running".

## Before opening a pull request

Run inside the worktree:

```bash
make lint
make test-unit
make test-integration
make check-tests      # app/ or web/ changes need a test in tests/unit AND tests/integration
```

Then `git push -u origin <branch>` and open a PR to `main`. CI runs lint, unit tests,
integration tests, the tests-included rule and a Docker build. Follow `CLAUDE.md` for
architecture rules.

## Clean up

```bash
./scripts/dev/wt.sh prune          # removes folders and local branches already merged into main
./scripts/dev/wt.sh remove <branch>  # removes one folder, keeps the branch
```
