# Rules

These rules apply within the user's authorized scope; explicit user instructions
take precedence. Record machine or project changes in `lease.py memory` and
`pr-rules.md` when used, `note` them, and forward them to members and peers.
Change the skill or helper only when the user requests a generic rule change;
do not put project-specific rules in the skill or `lease.py` docstring.

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

1. Run the smallest checks covering the changed behavior and affected
   boundaries, including local E2E when applicable or explicitly required.
   Preserve required CI, security, data-integrity and release checks. Reuse
   passing evidence for unchanged code; expand checks for concrete risk or
   failures. Once applicable checks pass, open the PR and mark it ready
   (`isDraft` false). Publish exact evidence and any material gaps. Never run
   or require CodeRabbit local review; hosted reviews remain separate.
2. UI PRs carry screenshot evidence attached on the PR page (description or an
   evidence comment), never committed to the repository, gists or branches.
   Capture screenshots outside the repository. The upload needs the user's
   approval in that session if its permission prompt asks.
3. The PR description follows the repository's template: problem and result,
   source SHA, focused checks, applicable real E2E scenarios, evidence, gaps.
   Keep mock, type and unit results separate from real E2E.
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
    Auto-fix only while ACTIVE. Keep it off while PAUSE applies; do not poll
    CI yourself.
    Codex members: attach the PR with `mcp__codex_app__attach_artifact` when
    available, and handle valid hosted review/CI blockers in the owner chat
    only while ACTIVE. PAUSE takes precedence over these repair instructions.
    Use the coordinator's watcher events or an authorized repair heartbeat
    for later work; PR attachment does not enable Auto-fix. See `agents.md`.
13. Stacks: one active PR per stack, bottom first. Merge each PR into main on
    its own; never merge a stacked PR into its parent. After the bottom merges,
    retarget the next to main and merge main into it. Paused PRs keep Claude
    Auto-fix off and Codex repair heartbeats paused. Enable auto-merge only
    after the PR targets the configured base branch and passes readiness gates.
14. After the merge, stop owned services, release leases and report receipts.
