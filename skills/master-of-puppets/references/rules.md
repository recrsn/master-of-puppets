# Rules

These rules apply within the user's authorized scope; explicit user instructions
take precedence. Project and machine rules go in the skill's memory
(SKILL.md, "Memory"), never in the skill or the helpers' docstrings. Limits
(GiB, slots, minutes, disk, swap, load) are not rules: they are config numbers
that `coordinator.py` enforces (`references/setup.md`).

## Coordinator conduct

- Never kill processes. Never take over an expired lease or replace a live
  coordinator session without the user's approval.
- Prefer fix tasks over investigations when two needs tie.
- Do an approved action as the user asked it, no more. Do not add steps the
  user did not ask for, such as a backup before an approved delete. When a
  step seems wise, offer it in the question, before the user answers.
- Answer a question about work you took over from the handoff notes and the
  notes files first (`handoffs/`, `notes/` in the state dir, and the note the
  handoff names). Search GitHub or logs only for what they do not say.
- When more than one coordinator runs on the machine, also follow the
  ownership and peer-conduct rules in `references/multi-coordinator.md`.

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
