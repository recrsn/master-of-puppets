# Rules

These rules apply within the user's authorized scope; explicit user instructions
take precedence. Project and machine rules go in the skill's memory
(SKILL.md, "Memory"), never in the skill or the helpers' docstrings. Limits
(GiB, slots, minutes, disk, swap, load) are not rules: they are config numbers
that `coordinator.py` enforces (`references/setup.md`).

## Coordinator conduct

- Never kill processes. Never take over an expired lease or replace a live
  coordinator session without the user's approval.
- Act within standing authorization for local or VM checks, read-only production
  queries, assigning fixes to their owners, and cleanup. Ask when a step needs
  new authority or a decision only the user can make.
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
   failures. Open or update the draft and publish the evidence for that head.
   Request [draft verification](protocol.md#draft-verification) before marking it Ready.
   Add a concrete regression test for a reproducible defect and satisfy required
   coverage gates. Omit redundant tests such as assertions that merely repeat
   configuration literals.
2. The PR description follows the repository's template. Keep mock, type and
   unit results separate from real E2E.
3. After `VERIFIED`, the owner marks the draft Ready, handles hosted review,
   CI and conflicts, and enables normal auto-merge within the verified scope.
   Keep explicit user holds, branch protections and repository approval rules.
   Database migrations, infrastructure changes (including Terraform), new
   customer-facing configuration or flags, cross-stream conflicts, and admin
   merges require a separate coordinator decision and the applicable human
   approval. Keep auto-merge off for these PRs. Apply an infrastructure
   exception only when the project's private PR rules explicitly authorize
   it and every affected resource falls within its scope. Migration and infrastructure
   approval here governs the merge of that PR. Once merged, it imposes no hold
   on downstream PRs or releases. Honor any independent release or deployment gate.
   Enabling normal auto-merge completes coordinator clearance within the verified
   scope. The owner follows rule 7 without a second approval or SHA-pinning step.
4. Verify each review finding against the source. Fix valid ones, explain
   skipped ones, resolve threads only after the fix is pushed.
5. Keep repairing real blockers until MERGED. Before calling a failure
   unrelated, find the exact job, revision, test and first causal error.
6. Sync with the base branch the way the project's rules or the user say.
   Ordinary push; `--force-with-lease` only when history must be replaced.
7. Auto-merge enabled, queued and MERGED are separate states. Continue until
   the host shows MERGED with a merge SHA.

## Scope and limits in a draft

For each new cap, budget, fence or gate, the author cites a concrete platform
or API constraint, a measured production failure, or an explicit user requirement.
Explain how the chosen threshold or mechanism follows from that evidence. The
draft verifier rejects unsupported size, depth, count and time limits, session
budgets, extra shadow flags, custom allowlists duplicating OS or sandbox isolation,
and defensive branches for states the interface already excludes. Preserve existing
security boundaries. Keep incident fixes scoped to the defect; propose any
independent policy change separately.
