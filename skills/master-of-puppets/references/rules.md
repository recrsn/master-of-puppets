# Rules

These rules apply within the user's authorized scope; explicit user instructions
take precedence. Project and machine rules go in the skill's memory
(SKILL.md, "Memory"), never in the skill or the `lease.py` docstring.

## Coordinator conduct

- Direct only your own members, and act only on PRs you own. For another
  coordinator's PR or member, message that coordinator.
- One owner per PR. Agree splits and cross-stack merge order by message, then
  `note` the agreement in the shared ledger.
- Never kill processes. Never take over an expired lease or a live
  coordinator's role without the user's approval.
- Prefer fix tasks over investigations when two needs tie.

## Member limits

The member side, including its limits, is the `puppet` skill. Do not ask a
member to cross those limits.

## PR rules

1. Run the smallest checks covering the changed behavior and affected
   boundaries, including local E2E when applicable or explicitly required.
   Preserve required CI, security, data-integrity and release checks. Reuse
   passing evidence for unchanged code: a new SHA from a mechanical merge or
   formatter churn does not need a new E2E. Expand checks for concrete risk or
   failures. Once applicable checks pass, open the PR and mark it ready
   (`isDraft` false). Publish exact evidence and any material gaps.
2. The PR description follows the repository's template. Keep mock, type and
   unit results separate from real E2E.
3. Normal auto-merge only. No bypass and no admin merge.
4. Verify each review finding against the source. Fix valid ones, explain
   skipped ones, resolve threads only after the fix is pushed.
5. Keep repairing real blockers until MERGED. Before calling a failure
   unrelated, find the exact job, revision, test and first causal error.
6. Sync with the base branch the way the project's rules or the user say.
   Ordinary push; `--force-with-lease` only when history must be replaced.
7. Auto-merge enabled, queued and MERGED are separate states. Continue until
   the host shows MERGED with a merge SHA.
