#!/usr/bin/env bash
# Work on several branches at once with git worktrees: one folder per branch,
# all kept inside this project folder under .worktrees/ (git-ignored).
#
#   ./scripts/dev/wt.sh new  ui/better-remote   # new branch from the latest main, in .worktrees/ui-better-remote
#   ./scripts/dev/wt.sh get  ui/glass-look      # check out an existing branch (e.g. a PR) in its own folder
#   ./scripts/dev/wt.sh list                    # all worktrees
#   ./scripts/dev/wt.sh path ui/glass-look      # print the folder (cd "$(./scripts/dev/wt.sh path x)")
#   ./scripts/dev/wt.sh remove ui/glass-look    # delete the folder (the branch itself is kept)
#   ./scripts/dev/wt.sh prune                   # remove folders whose branches were merged into main
#
# The main folder stays on `main`: update it with `git pull`, never commit there.
set -euo pipefail

COMMON="$(git rev-parse --path-format=absolute --git-common-dir)"
ROOT="$(dirname "$COMMON")"           # the main checkout, wherever this is run from
WT_DIR="$ROOT/.worktrees"

slug() { echo "$1" | tr '/ ' '--' | tr -cd 'A-Za-z0-9._-'; }
path_for() { echo "$WT_DIR/$(slug "$1")"; }
need() { [ -n "${1:-}" ] || { echo "Branch name needed. Example: $0 ${2:-new} feature/my-change"; exit 1; }; }

cmd="${1:-help}"; branch="${2:-}"
case "$cmd" in
  new)
    need "$branch" new
    git -C "$ROOT" fetch -q origin main
    dest="$(path_for "$branch")"
    git -C "$ROOT" worktree add -b "$branch" "$dest" origin/main
    git -C "$dest" branch --unset-upstream 2>/dev/null || true   # first push sets the real upstream
    echo
    echo "Ready: $dest  (branch $branch, from the latest main)"
    echo "  cd \"$dest\""
    echo "  make setup        # once, then run targeted tests in this source worktree"
    echo "  Deploy validated changes to the existing native 8080 service; do not start a second app."
    echo "  git push -u origin $branch   # when you're ready to open a PR"
    ;;
  get)
    need "$branch" get
    git -C "$ROOT" fetch -q origin
    dest="$(path_for "$branch")"
    if git -C "$ROOT" show-ref --quiet "refs/heads/$branch"; then
      git -C "$ROOT" worktree add "$dest" "$branch"
    else
      git -C "$ROOT" worktree add --track -b "$branch" "$dest" "origin/$branch"
    fi
    echo "Ready: $dest"
    ;;
  list)
    git -C "$ROOT" worktree list
    ;;
  path)
    need "$branch" path
    path_for "$branch"
    ;;
  demo)
    echo "Branch demos are retired. Use the canonical app at http://localhost:8080." >&2
    echo "Run isolated tests for development; do not start another user-facing instance." >&2
    exit 1
    ;;
  remove)
    need "$branch" remove
    git -C "$ROOT" worktree remove "$(path_for "$branch")"
    echo "Removed the folder. The branch '$branch' still exists (git branch -d $branch to delete it)."
    ;;
  prune)
    git -C "$ROOT" fetch -q origin --prune
    git -C "$ROOT" worktree list --porcelain | awk '/^worktree /{p=$2} /^branch /{print p" "$2}' | while read -r p ref; do
      b="${ref#refs/heads/}"
      [ "$p" = "$ROOT" ] && continue
      if git -C "$ROOT" merge-base --is-ancestor "$ref" origin/main 2>/dev/null; then
        echo "Merged into main: $b → removing $p"
        git -C "$ROOT" worktree remove "$p" && git -C "$ROOT" branch -d "$b" >/dev/null || true
      fi
    done
    git -C "$ROOT" worktree prune
    ;;
  *)
    sed -n '2,14p' "$0"
    ;;
esac
