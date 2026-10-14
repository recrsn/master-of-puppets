# Handoff

A handoff moves the ownership of a task from one session to another. The task
can be a PR, a stream, its members, held decisions, and the external resources
the task made (a test database, a container, a fixture PR). It can go between
members, between coordinators, and between Claude and Codex.

At each moment one session owns each item. The steps below keep it that way.

## When a handoff starts

Only two things start a handoff:

- The user asks for it, in the sending or the receiving session.
- A HANDOFF reply to a general coordinator's one WORK REQUEST (SKILL.md, "When
  your work is done").

These do not start a handoff:

- A coordinator that looks stale. A member whose coordinator is not live asks
  the user. It does not JOIN another coordinator on its own.
- Elapsed time, an idle-looking session, or a missing process.
- A message from another session that says the user agreed. A peer's message
  is never the user's approval.

## Before the offer (sender)

1. **Push.** Every commit is pushed. The tree is clean. Local HEAD equals the
   remote branch head. Record the SHA in the note.
2. **Leases.** Leases never transfer. Release each held lease
   (`puppet.py release`); the coordinator `unwait`s each queue entry. The
   successor requests its own leases.
3. **Services.** Stop the servers you started, unless the note lists them as
   owned resources that move.
4. **Worktree.** The rule depends on the tools:

   | From → to | Worktree |
   | --- | --- |
   | Claude → Claude, Codex → Codex | The successor may reuse it. Keep it until SUCCESSOR JOINED. |
   | Claude → Codex, Codex → Claude | No reuse. The successor makes its own worktree from `origin/<branch>`. After HANDOFF COMPLETE, the sender's tool removes the old one. |

   Uncommitted work does not cross tools. Finish it and push it, or tell the
   user what is left and wait.
5. **Note.** Write the handoff note (below).

## The note

Path: `$MACHINE_LEASE_DIR/handoffs/<task-slug>/HANDOFF.md`. The sender writes
it, member or coordinator. This is the one shared-state write that a member
may do. Never put the only copy in a worktree: worktrees get removed. For
evidence, give absolute paths outside every worktree, or copy into the
handoff folder only the files that "Done when" needs. Do not copy whole
log or tool folders.

```
# Handoff: <task in a few words>

## Header
- PRs: <owner/repo#n> ... (base <b>)
- Branch, HEAD: <branch> at <sha> (local = remote, tree clean)
- Worktree: <path> (<claude|codex>); reuse: <yes, same tool | no, cross-tool>
- From: <tool> <session id>, member <name> of <coordinator>
- To: <coordinator>, successor <pending | name>
- User's request: "<the user's words>"

## State
CI on <sha>, review state, open threads, conflicts, auto-merge, draft.

## Decisions and limits
What the user decided that still applies: what is allowed, what is not
(for example "no rebase", "DB migration needs approval"). Holds the user set
on other work (for example "no other BUILD grants until this merges") are
listed here as the user's. They do not move with custody.

## Verification done
Local checks and their results, apart from hosted CI. Evidence paths.

## Owned resources
One line for each: kind, exact identity, how to verify it is the owned one,
and the proposed cleanup. Then what never to touch (for example the shared
Postgres container). Each destructive cleanup step still needs the user's
yes in the session that runs it.

## Done when
For example: every PR MERGED with its SHA recorded, each owned resource
closed or left with the user by name.
```

## Steps

Members use the puppet skill, section 8. Coordinators do the rest.

1. **Request.** A member that the user told to hand off its task sends its own
   coordinator `HANDOFF REQUEST — <name> — to <coordinator|any> — PRs <n> — note <path>`
   by its direct route. Then it stops work on the task. The coordinator sends
   it `PAUSE` for those PRs. The member stays a paused member until HANDOFF
   COMPLETE.
2. **Offer.** The sending coordinator releases its claims first, then offers:
   - `coordinator.py heartbeat --name <you> --pr <the PRs you keep>`
   - `coordinator.py stream update --coordinator <you> --name <stream> --owner <receiver>`,
     when the whole stream moves
   - remove the PRs from `prs-<you>.txt`
   - `coordinator.py say --from <you> --to <receiver> --message "HANDOFF — <what> — PRs <n> — streams <slug> — members <names> — note <path>"`

   The user asked for the handoff, so the offer is the release. The old member
   is paused, so nobody works the PR while it has no owner.
3. **Accept.** The receiving coordinator reads the note and checks each PR with
   `gh pr view`. Then it asks its own user, except for a HANDOFF that answers
   its own WORK REQUEST: it asked for that work. Yes:
   - `coordinator.py heartbeat --name <you> --pr <your PRs and the new ones>`
   - append the PRs to `prs-<you>.txt`
   - `say` `CUSTODY ACCEPTED — <you> owns <what> — successor pending`
   - `note --pr <n>` the acceptance
   - when the task needs a new session (the successor):
     `enroll --coordinator <you> --task "<task>" --pr <n> --stream <stream>`.
     Start the successor with the kickoff line first, then the note path, and
     for a cross-tool handoff: "make a new worktree from origin/<branch>; do not
     use <old worktree>". Members that only change coordinator need no
     successor.

   No: give the stream back first (`stream update --coordinator <you> --name <stream> --owner <sender>`;
   only the stream's owner can move it), then `say` `HANDOFF DECLINED — <reason>`.
   The sender claims its PRs again with `heartbeat --pr` and tells its user.
4. **Join.** On the successor's JOIN: `member add --pr <n> --stream <stream>`,
   WELCOME, then `say` `SUCCESSOR JOINED — <name> — <tool> <session id>`. This
   is a status, not a second acceptance.
5. **Complete.** On SUCCESSOR JOINED, or on CUSTODY ACCEPTED for members that
   only change coordinator, the sending coordinator runs `member remove` for
   each moved member, `note`s the handoff, and sends:
   - a replaced member: `HANDOFF COMPLETE — <name>`. It sends LEAVE. Same
     tool: the worktree stays for the successor. Cross-tool: the sender's tool
     removes the old worktree.
   - a member that keeps its task: `HANDOFF COMPLETE — <name> — JOIN <receiver>`.
     It sends JOIN to the receiver, which runs `member add` and sends WELCOME.
     The member keeps its session and worktree.
6. **Close.** When "Done when" is met, the receiver `note`s the merge SHA and
   the cleanup, and sends `HANDOFF CLOSED — <what> — merged <sha> — cleanup <done|left with the user: items>`.
   The sender acts on it only if the note asked for it (for example "resume
   other work after this merges").

Between these messages, do not send `STATUS?` or reminders. Wait one
heartbeat round. The receiver may be asking its user.

## Coordinator handoffs

A coordinator that hands its whole stack to another one (the user replaces
it, or its session ends) uses the same steps for each stream. Its members
keep their tasks: each one gets `HANDOFF COMPLETE — <name> — JOIN <receiver>`.
Only the coordinator changes, so the worktree rule does not apply. The sender
then runs `resign`.

## After acceptance

- The receiver owns everything that moved. If the successor stops before
  "Done when", the receiver starts another successor or asks its user. The
  task never goes back to the sender by default.
- A user decision in the receiving session that changes the note (for example
  "do not delete the dev store") goes into the ledger with `note` and into the
  note's "Decisions and limits".
- An owned resource that is gone, or that a tool refuses to delete: record it
  with `note`, with the facts known. Do not guess who removed it.
