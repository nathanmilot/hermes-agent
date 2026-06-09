---
name: hermetic-squash
description: "Slash command: squash commits into hermetic feature commits (zero file overlap). Creates backup branch, groups commits by file-touch analysis, rebuilds via git reset --soft, and prompts to clean up backup. Use when asked to squash/clean history."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [git, squash, hermetic, cleanup, history]
    related_skills: [git-rebase-diverged, proxxied-cli]
---

# /hermetic-squash — Squash Intermediate Commits into Hermetic Features

## Overview

Takes all commits reachable from HEAD but not from `upstream/main`, analyzes
file-touch overlap to identify intermediate-state commits, and rebuilds them
into hermetic feature commits (commits that never touch overlapping files).

Creates a `backup/squash-<branch>` before making any changes, verifies the
final diff matches the backup after the squash, then asks the user whether to
delete the backup branch.

## Trigger

User says: "squash these commits", "clean up history", "make hermetic commits",
"remove intermediate state commits", or runs `/hermetic-squash`. Optionally
specify a base ref: `/hermetic-squash upstream/develop` (default: auto-detect
branch fork-point via `git merge-base --fork-point`).

**Do NOT use** when the branch has uncommitted working-tree changes (stash first).
The base ref must be reachable locally before proceeding.

## Workflow

### Step 0: Determine base ref

If the user specified a base ref explicitly (e.g., `/hermetic-squash origin/main`),
use that. Otherwise auto-detect the branch fork-point:

```bash
# For a named branch, find where it diverged:
base=$(git merge-base --fork-point upstream/main HEAD 2>/dev/null \
       || git merge-base upstream/main HEAD)

# Or explicitly prompt the user for a base if auto-detect seems wrong.
```

The base is the ref that all commits will be squashed ON TOP OF — it's the
shared ancestor, not the target of a future rebase. Typically `upstream/main`.

If the base ref isn't reachable locally, fetch it first and re-derive.

### Step 1: Identify commits

```bash
commits=$(git log --oneline $base..HEAD)
```

Verify commits are clean (no WIP, no fixup commits that reference code outside
the range). Check for uncommitted changes and bail if present.

### Step 2: Create backup branch

```bash
git branch backup/squash-$(git branch --show-current)
```

### Step 3: Analyze file-overlap groups

For each commit, extract its file list and build a file→commit mapping.
Identify which pseudo-commits share files. A file touched by multiple commits
means those commits must be squashed together.

Group the commits into features by starting with the file-touch assignment and
using semantic grouping (same feature area = same squash target).

**Key rule:** After grouping, a file must appear in AT MOST ONE group's file list.
This guarantees hermetic commits with zero file overlap.

### Step 4: Rebuild commits

```bash
git reset --soft $base
git reset HEAD .
```

Stage files for each feature group and commit with a descriptive message.
Use `git add <files>` + `git commit -m "<type>: <scope> — <summary>"`.

Suggested commit order: smallest/scoped-first, largest/most-impact-last.

### Step 5: Verify

Compare the diff before and after the squash:

```bash
# Before-squash diff (from backup branch)
git diff $base..backup/squash-<branch> | git hash-object --stdin

# After-squash diff
git diff $base | git hash-object --stdin
```

The content hash MUST be identical. If not, the working tree was altered during
the squash — investigate before telling the user.

Also verify zero file overlap between new commits:

```bash
for commit in $(git rev-list $base..HEAD); do
  echo "$(git rev-list --oneline -1 $commit) — $(git diff-tree --no-commit-id --name-only -r $commit | tr '\n' ' ')"
done
```

### Step 6: Report + cleanup prompt

Show the user:
- The new commit log (oneline)
- Confirmation that the diff hash matches the backup
- Ask: "Backup branch `backup/squash-<branch>` preserved. Delete it? [y/N]"

If they say yes, delete. If no or unclear, leave it.

## Common Pitfalls

1. **Untracked files vanish with git reset --soft.** They won't be staged — they
   stay as untracked files but won't be part of any commit unless explicitly
   `git add`-ed. Always check `git status --short` before reset so you know about
   untracked files in advance.

2. **New files (untracked) still need `git add`.** They won't come along with
   `git reset --soft $base`. Track them manually when staging their group.

3. **Squashing on the base branch.** `git reset --soft $base` while on the base
   branch is fine as long as you haven't pushed those commits yet. If commits
   were pushed, warn the user that a force-push will be required.

4. **Backup branch is local-only.** The backup branch is not pushed anywhere. If
   the user needs remote backup, they should push it manually before running the
   squash step.

5. **`git reset HEAD .` vs `git reset`.** The `.` is critical — without it only
    staged files are unstaged, but the index remains pointing at the last reset's
    tree. `git reset HEAD .` unstages everything by resetting the index to HEAD
    for all files in the working tree.

## Verification Checklist

- [ ] Base ref determined and reachable locally
- [ ] Backup branch created: `backup/squash-<name>`
- [ ] No uncommitted working tree changes
- [ ] `git diff $base..backup/squash-<name>` hash == `git diff $base` hash
- [ ] Zero file overlap across new commits
- [ ] User prompted about backup branch deletion
