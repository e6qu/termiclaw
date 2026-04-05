---
name: PR workflow discipline
description: Always check if a PR is already merged before trying to update it; create new PRs for new changes
type: feedback
---

Always check `gh pr view <id> --json state` before updating a PR. If it's MERGED, create a new branch and a new PR instead of trying to add commits to the old one.

**Why:** The user was frustrated when I kept adding commits to an already-merged PR branch. The commits were lost because the PR was squash-merged before the new commits landed.

**How to apply:** Before any PR operation (edit, push to branch), check the PR state first. If merged, start fresh from main.
