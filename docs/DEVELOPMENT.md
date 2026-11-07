# Developing on your own computer

## One project folder, one folder per branch

```
~/Documents/homepanel/                 ← the main clone, always on `main` (git pull here)
├── data/                              ← settings and device keys for real-device runs (git-ignored)
└── .worktrees/                        ← one folder per branch (git-ignored)
    ├── ui-glass-look/
    └── feature-photo-frame/
```

Git *worktrees* let several source branches be checked out at once, each in its own
folder, sharing one repository. They are editing/rollback copies, not separate apps.
The user-facing application stays on the single native service at port 8080.

### First time (macOS)

```bash
git clone https://github.com/leshwar/homepanel.git ~/Documents/homepanel
cd ~/Documents/homepanel
```

Install Python 3.11+ (3.14 for the Ecovacs integration), then run `make setup` in
the worktree to create its virtual environment. No container runtime is needed.

### Everyday commands

| Task | Command (run in `~/Documents/homepanel`) |
|---|---|
| Update main | `git pull` |
| Start a change | `./scripts/dev/wt.sh new feature/my-change` (or `make wt-new b=feature/my-change`) |
| Go to its folder | `cd "$(./scripts/dev/wt.sh path feature/my-change)"` |
| Try someone's branch / PR | `./scripts/dev/wt.sh get ui/glass-look` |
| First native startup | `make setup` once, then `make run` → http://localhost:8080 (only when no service already runs) |
| Check a feature | targeted tests in its source worktree; deploy to the existing native service when authorized |
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

## Updating a running native deployment

Use its existing supervisor (systemd on the Pi, or its installed launchagent on
macOS); do not start a second process on 8080. Back up `data/` and the supervisor
configuration before upgrading. When deploying a feature revision locally without
changing protected `main`, use a pinned detached worktree and point the supervisor's
working directory at it. Keep the existing interpreter and supply explicit
`--data /absolute/live/data --logs /absolute/live/logs` paths so the new worktree
does not create an empty household. Keep the old revision/configuration for rollback.
This does not merge or push the feature to `main`.

All user-facing previews come from the deployed 8080 application and its actual
profile, layout, theme and font size. Never make real data match test fixtures.
A normal page refresh revalidates HTML/CSS/JS; already-open tabs keep loaded JS
until refreshed. Record the viewport and selected profile when comparing captures:
portrait/landscape arrangements and distinct profile layouts can legitimately differ.

Internal tests still use temporary simulated devices and free loopback ports.
They run the same application implementation, not a second product or household.
There is no `make dev`/`wt-demo` preview workflow. The hidden subprocess fixture
switch is rejected on 8080, non-loopback interfaces and existing household data.

## Private access

Tailscale on the host can serve the native loopback port over tailnet-only HTTPS:
`tailscale serve --bg 8080`. Restrict tailnet access to the intended people/devices.
Password-free profiles are personalization, not an authentication barrier. Do not
use public Funnel or router port forwarding. Serve does not close an existing LAN
listener; decide separately whether the wall panel still needs LAN access.
See [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).

### With Claude Code

The repo includes a skill, `.claude/skills/homepanel-dev/`, that teaches Claude
Code this workflow. Run `claude` inside `~/Documents/homepanel` and ask, for
example, "start a new branch for a Roku adapter" or "show me the demo of the
photo frame PR".
