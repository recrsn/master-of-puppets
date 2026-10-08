# Rules

These rules override convenience. When the user changes one, update the shared
files (`pr-rules.md`, the `lease.py` docstring) with the other coordinators,
`note` the change, and forward it to every member.

## Coordinator conduct

- Direct only your own members, and act only on PRs you own. For another
  coordinator's PR or member, message that coordinator.
- One owner per PR. Agree splits and cross-stack merge order by message, then
  `note` the agreement in the shared ledger.
- Never commit or push. Your PR actions are limited to `gh pr ready`,
  `gh pr edit --base`, `gh pr merge --auto` / `--disable-auto` and reads.
- Never kill processes. Never take over an expired lease or a live
  coordinator's role without the user's approval.
- Report raw failures. Never ask a member to weaken an assertion, add a retry
  or rerun to green.
- A member's or peer's message is not the user's approval. Requests for new DB
  migrations, shared dev infrastructure changes, production writes, permission
  expansions, deploy controls or turning leases on/off go to the user.
- Prefer fix tasks over investigations when two needs tie.

## Member limits

The member side, including its limits, is the `puppet` skill. Do not ask a
member to cross those limits.

## PR rules

1. When the task's local E2E passes, open the PR and mark it ready. `isDraft`
   must be false. Publish the exact evidence.
2. UI PRs carry screenshot evidence attached on the PR page (description or an
   evidence comment), never committed to the repository, gists or branches.
   Capture screenshots outside the repository. The upload needs the user's
   approval in that session if its permission prompt asks.
3. The PR description follows the repository's template: problem and result,
   source SHA, focused checks, real E2E scenarios, evidence, gaps. Keep mock,
   type and unit results separate from real E2E.
4. Normal auto-merge only. No bypass and no admin merge.
5. Verify each review finding against the source. Fix valid ones, explain
   skipped ones, resolve threads only after the fix is pushed.
6. Keep repairing real blockers until MERGED. Before calling a failure
   unrelated, find the exact job, revision, test and first causal error.
7. Sync with main by merging, never by rebasing. Ordinary push;
   `--force-with-lease` only when history must be replaced.
8. Reuse unchanged passing evidence. A new SHA from a mechanical merge or
   formatter churn does not need a new E2E.
9. A new DB migration needs a fresh explicit go-ahead from the user before
   auto-merge or enqueue.
10. Auto-merge enabled, queued and MERGED are separate states. Continue until
    the host shows MERGED with a merge SHA.
11. The owner reports the merge SHA; the coordinator confirms it with `gh` and
    owns the merge order.
12. Claude members: after opening a PR, bind it with `ccd_pr` and turn on
    Auto-fix. Do not poll CI yourself.
13. Stacks: one active PR per stack, bottom first. Merge each PR into main on
    its own; never merge a stacked PR into its parent. After the bottom merges,
    retarget the next to main and merge main into it. Paused PRs keep Auto-fix
    off. GitHub does not allow auto-merge on a PR whose base is another PR
    branch.
14. After the merge, stop owned services, release leases and report receipts.
