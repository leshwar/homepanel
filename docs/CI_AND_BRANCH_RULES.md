# CI pipeline and branch rules

## What runs automatically

| When | What runs | Where |
|---|---|---|
| Every pull request | **Lint** (ruff, shell syntax) | `.github/workflows/ci.yml` |
| | **Tests included**: code changes under `app/` or `web/` must add or change a `tests/unit/test_*.py` **and** a `tests/integration/test_*.py`, otherwise the PR fails | `scripts/ci/check_tests_included.py` |
| | **Unit tests** on Python 3.11 and 3.13 (the versions on Raspberry Pi OS) | `tests/unit/` |
| | **Integration tests**: real server over HTTP, adapters against simulated devices, the touch UI in headless Chromium (never skipped in CI) | `tests/integration/` |
| | **Native startup smoke** (inside integration): real server starts, answers health/commands/static UI, and all supported brand libraries load | `tests/integration/test_api.py` |
| | **All checks passed**: one summary check that's green only if everything above passed | — |
| Every push to `main` (i.e. a merged PR) | Everything above, then **Publish source**: a source archive attached to the run | Actions run page |

Run the same checks locally before opening a PR:

```bash
make lint
REQUIRE_UI_TESTS=1 make test   # one complete final pass; targeted checks while developing
make check-tests      # would the "tests included" rule pass?
```

## Branch rules for `main` (owner sets these once)

Goal: every change goes through a pull request; CI must pass for everyone,
including the owner; anyone else needs the owner's approval; the owner can merge
their own PRs without an approval.

GitHub doesn't let you approve your own PR, so the owner gets a *bypass* — but a
bypass skips every rule in its ruleset. So we use **two rulesets**: one that
nobody can bypass (pull request + CI), and one that only adds the approval
requirement, which you can bypass.

Repository → **Settings** → **Rules** → **Rulesets** → **New ruleset** → **New branch ruleset**.

### Ruleset 1: `main: PR and CI required` (no bypass)

1. **Enforcement status:** Active. **Bypass list:** leave empty.
2. **Target branches** → **Add target** → **Include default branch**.
3. Turn on:
   - **Restrict deletions**
   - **Block force pushes**
   - **Require a pull request before merging** — Required approvals: **0**;
     **Require conversation resolution before merging**
   - **Require status checks to pass** — **Require branches to be up to date
     before merging**; add check **All checks passed** (it appears in the list
     after CI has run once on a PR)
4. **Create**.

### Ruleset 2: `main: owner approval` (owner can bypass)

1. **Enforcement status:** Active.
2. **Bypass list** → **Add bypass** → **Repository admin**, mode **For pull requests only**.
3. **Target branches** → **Include default branch**.
4. Turn on **Require a pull request before merging** with:
   - Required approvals: **1**
   - **Dismiss stale pull request approvals when new commits are pushed**
   - **Require review from Code Owners** (`.github/CODEOWNERS` makes @leshwar the
     owner of everything, so only your approval counts)
   - **Require approval of the most recent reviewable push**
5. **Create**.

Result:

| Who | Push directly to main | Merge a PR |
|---|---|---|
| You (owner) | Blocked | Once CI is green. No approval needed: choose "Merge without waiting for requirements to be met", which skips only ruleset 2 |
| Collaborators and forks | Blocked | Only after CI is green **and** you approve |

Tip: under Settings → General → Pull Requests, turn on **Automatically delete
head branches** to keep the branch list tidy.

### Inviting friends

Settings → **Collaborators** → **Add people**. Give them the **Write** role so
they can push branches and open PRs in this repo (or they can fork). They still
can't merge without your approval.

## Published source

After a merge to `main` passes all required checks, its Actions run contains a
`homepanel-<commit>` source archive. The panel runs natively with Python; update
the native checkout/interpreter and restart its existing supervisor.
