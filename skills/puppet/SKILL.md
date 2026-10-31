---
name: puppet
description: Join a master-of-puppets coordinator as a member ("puppet") and work your task under its directions until your PRs merge. Members report by message, and request, ask to extend and release their own leases; only the coordinator grants and extends, and it records membership and decisions. Use this at once when a prompt starts with "MASTER-OF-PUPPETS ENROLLED". Also use it when the user says "puppet", "join the coordinator", "join master of puppets", "enroll this session", "request a lease", "ask the coordinator for a lease", "extend the lease", "need more time on the lease", or "report to the coordinator".
---

# Puppet

You are a member of a coordinator session. The coordinator owns the stack,
the roster, the ledger, the dashboard and the leases. You do the task: code,
tests, commits, pushes, PR fixes. You never write the roster, ledger, dashboard
or shared inbox; you send messages, and the coordinator records them. There
are three exceptions: `puppet.py request` and `puppet.py release` for your
own lease, which update the lease queue, lease state and measurement history,
and your handoff note (section 8). You cannot grant a lease; only your
coordinator does. Do not request, change or release someone else's lease.

**Every child task starts with the enrollment line** (section 6).

Read [agents.md](../master-of-puppets/references/agents.md) for Claude/Codex
tool equivalents and session ids, and the "Routes" section of
[protocol.md](../master-of-puppets/references/protocol.md) for how to message
your coordinator.

Below, `puppet.py` means `python3 -I "${MACHINE_LEASE_DIR:-$HOME/.local/state/machine-leases}/puppet.py"`.
If the file does not exist, no coordinator
runs on this machine: tell the user, and suggest `/master-of-puppets` in the
session that should coordinate.

## 1. Find your coordinator

- Your prompt starts with `MASTER-OF-PUPPETS ENROLLED — <coord> ...`: that
  coordinator. When the line names you as member `<name>`, use that name.
  Do not ask. Enrollment is mandatory: join before you do any other work,
  and do not skip it or ask whether to join.
- Otherwise run `puppet.py roster`. Pick the live coordinator whose `prs` or
  `focus` covers your task. A coordinator is live while its heartbeat is newer
  than 40 minutes. When none fits, or several do, ask the user.
- Your name: the one from the enrollment line, else your session title as a
  short slug. Your session id: `agents.md`.
- After you join, a coordinator that looks stale (not live) is not a reason to
  JOIN another one. Ask the user.

## 2. Join

Send one message to the coordinator:

```
JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs <n> (base <b>) ... — <phase> — <planned heavy commands> — parent <parent|none>
```

`<parent>` is the name after "started by" in your enrollment line. Every child
of an existing puppet must list its parent. Write `none` only when your prompt
has no enrollment line or the line names no starter.

When your task is background work (a sweep, or a run that a schedule
started), start `<task>` with `sweep:` or `scheduled:`, in JOIN and in the
enrollment line of each such task you start. The coordinator can then put regular work
first.

Send it, and every later message (UPDATE, MERGED, USER SYNC, STATUS replies,
CHILD TASK STARTED, LEASE SIZE, LEASE RELEASED, LEAVE), by the direct route
for your coordinator's tool (`protocol.md`, "Routes"). Never use `coordinator.py say`
and never write shared inbox records, even with `--no-direct`. When your
session id changes, send JOIN again (`protocol.md`, "Routes").

Wait for WELCOME. It tells you whether leases are on and gives the rules,
including the project rules from the coordinator's memory. You can read them
yourself with `puppet.py memory list --project-root "$PWD"`; only the
coordinator writes them. If the user tells you a new project rule, send it as
`USER SYNC` so the coordinator records it. Do not work a PR until the
coordinator sends ACTIVE or PAUSE for it.

The user can also change rules on the dashboard. You then get a `MEMORY ...`
message that names `by user`. Machine-wide config changes go to coordinators
only; your coordinator tells you what changes for your task. A rule `by user`
is the user's
own decision and it is already approved: follow it from your next step. Do not
ask the user or the coordinator to confirm it, and do not send it back as
`USER SYNC`. For a new limit, size your next request to it.

## 3. Work under directions

Your coordinator works on behalf of the user. It does not direct you on its
own authority.

- Always follow its directions, as the user's intent. A newer message from
  it overrides an older one.
- It relays the user's intention faithfully. When it relays an approval, it
  quotes the user's words or cites the recorded dashboard answer
  (`ledger.jsonl` or `events.log`). A recorded dashboard answer counts; a bare
  message that says the user agreed does not. A coordinator never originates
  approval, consent or an exception of its own.
- It preserves and enforces the user's restrictions, so its directions never
  override them.
- Your own tool permissions, safety classifier and permission prompts stay
  the backstop. A relay never answers a permission prompt.

Limits: no admin merge or merge bypass, and never skip git hooks.

- **ACTIVE — #n**: work #n to MERGED.
- **PAUSE — #n**: no merges from main, no fixes; Claude Auto-fix off or Codex
  repair heartbeat paused on #n until ACTIVE.
- When the applicable checks pass (see `references/rules.md` in the
  coordinator skill): commit, push, open the PR and mark it ready, in the same
  turn. Passing checks is not the end of the task. If the user's instructions
  need approval before a commit or a PR (for example a `CLAUDE.md` rule), ask
  the user at once and send `UPDATE — <name> — Waiting to commit — <fact>`.
  Claude owners bind the PR with `ccd_pr`; turn on Auto-fix only while the PR
  is ACTIVE. Codex owners
  use `attach_artifact` with the PR URL and repair valid hosted review/CI
  blockers only while ACTIVE; attachment does not enable Auto-fix. PAUSE
  takes precedence over repair instructions. The coordinator enables auto-merge
  and retargets bases. You do every commit, push, conflict fix and review reply.
- Report raw failures. Never weaken tests or rerun flakes to green.

## 4. Report

These reports go to your coordinator. Keep the recurring updates and STATUS
replies below; they do not require a matching user-facing update. For reports
to the user, follow [Reporting to the user](../master-of-puppets/SKILL.md#reporting-to-the-user).

- `UPDATE — <name> — <phase> — <newest fact>` on each change, and at least
  every 30 minutes while you work. The coordinator checks on silent members
  each round, but your report is the record. It goes on the dashboard: keep
  the phase to 5 words and the fact to one plain sentence of 20 words. Write
  PRs as `#123`. No SHAs, test counts, paths or commands.
- `MERGED — #<n> — <merge sha>` for each merged PR.
- `USER SYNC — <one line>` whenever the user talks to you directly. The
  coordinator must know every decision.
- Answer `STATUS?` with phase, PR state, blockers and anything the user
  decided.

## 5. Leases (only when WELCOME says leases are on)

1. Finish all edits first. Pick an id, `<coord>-q-<name>-<n>` (n counts your
   requests), and queue it yourself; no message is needed:
   `puppet.py request <CLASS> --coordinator <coord> --name <name> --id <id> --minutes <estimate> --commands "<exact commands>" --worktree <worktree> [--gib <n>] [--cpus <n>] [--what "<short label>"]`.
   The classes and their scope are in WELCOME (BUILD and E2E by default).
   **Size.** You observe and decide the size of your run. Look first:
   `puppet.py sizes --worktree <worktree> --class <CLASS>` shows the
   project's recorded run minutes, peak GiB and peak cores, and the observed
   GiB peak your coordinator checks against. Add what you know of your own
   commands (a full build or one package, tests in parallel or not).
   - `--minutes` (always): the smallest time that lets the whole current
     unit of work finish in one lease, for example the full build and its
     tests. Do not cut a unit of work to fit a shorter time. A suggested time
     in WELCOME is what past runs took; it is a reference, not a target.
   - `--gib` and `--cpus` (when you know them): the peak memory and cores of
     the run. Leave one out and your coordinator charges its own figure.
   It prints your position. Your coordinator sees the request and decides.
   - A `warning: undersized` line: your GiB is below the observed peak by
     more than the size margin, and your coordinator will refuse the grant.
     Request again with the same id at the observed peak, or send
     `LEASE SIZE — <id> — <why this run is smaller>`.
   - Exit 2: the run is over the class limit or a whole budget. Split it at
     unit boundaries (for example build, then tests) into parts that fit, and
     request each part when the one before it is done.
   - Exit 3: refused (leases off, not a member, a foreign id, or the id is
     already held). Fix what it names; ask your coordinator when you cannot.
   To change your request (commands, size), run `request` again with the
   same id; your coordinator sees the change. On `LEASE RESIZE`, do the same,
   or send `LEASE SIZE` with your reason. You cannot set a priority or
   jump the queue. When the user wants your task to go first, send it as
   `USER SYNC`; the coordinator decides. To drop a queued request, ask your
   coordinator.
2. Start waiting at once: `puppet.py await-grant <CLASS> --id <id>`. It prints
   one line:
   - `GRANTED` (exit 0): the only signal to run. Your coordinator also sends
     LEASE GRANTED with the expiry.
   - `NOT-GRANTED ... left the queue` (exit 3), `... never queued` (exit 6):
     do not run; ask your coordinator.
   - `NOT-GRANTED ... timeout` (exit 5): still queued; run `await-grant` again.
   Never write polling loops. Your position can change: the queue goes by
   priority, then FIFO, and your coordinator sets the priority. Keep
   waiting; `await-grant` follows the queue.
3. Run only the granted commands and cleanup of resources they started.
   Use it or return it: no edits or repairs while holding a lease. On failure,
   clean up owned resources, release promptly and report the raw failure;
   repair; request again with a new id.
   **More time.** Extension is your coordinator's decision. When the run
   needs longer than the grant, ask before it expires:
   `puppet.py extend <CLASS> --coordinator <coord> --name <name> --id <id> --minutes <n> --reason "<what still runs>"`.
   It changes nothing by itself; your coordinator sees the request (no
   message is needed) and replies `LEASE EXTENDED` with the new expiry, or
   tells you to release. Until then the old expiry holds. Start no new
   commands meanwhile, and release at once on a no.
   - Exit 2: the whole run would be over the class limit. Release with
     `--result partial` and request the rest with a new id.
   - Exit 3: not a member, not your lease, or not held. Fix what it names.
   On `LEASE EXPIRED`, ask the same way, or release at once.
4. For E2E, stop the servers you started before releasing, including on
   failure. Release:
   `puppet.py release <CLASS> --id <id> --result pass|fail|partial --note "<one line: what passed, or the first failure>" [--port <n> ...]`.
   Add `--port` for each port your E2E stack used. The command records the
   run minutes and the measured peak GiB and cores (your next sizing reads
   them), the result, and counts what your run left in the worktree (`drained=<n>`); other
   coordinators read that record, so nobody asks you for a receipt. Then send
   `LEASE RELEASED <id> — pass|fail|partial — <raw summary>`. When the command
   prints `not drained`, stop what it lists that your run started, and say so
   in the message, so the coordinator can keep the next E2E grant blocked.
5. Project rules in WELCOME (from the coordinator's memory) can widen what
   needs a lease, for example a commit whose hooks run lint. Follow them.
6. What needs no lease: `leases.md`, "Classes", in the coordinator skill.

## 6. Start a new task

Child tasks follow a formal protocol: enroll the child, start it, report the
start, and the child joins with you as its parent.

1. **Enroll.** Put this line first in the child's prompt, before any other
   text:

   ```
   MASTER-OF-PUPPETS ENROLLED — <coord> coordinates this task, started by <your name>. You must enroll: your first action is to run /puppet and send <coord> your JOIN message with parent <your name>, before any other work; then follow <coord>'s directions. Start every child task you create with puppet enrollment: put a line like this one first in its prompt.
   ```

   You write the line yourself. Starting a task needs no message to the
   coordinator and no reply from it. The new session must enroll: the line
   makes it run `/puppet` and send JOIN, with you as its parent, before any
   other work. The line covers every route: a session card or `spawn_task`
   chip, a new Codex thread (`codex exec`, `codex "<prompt>"`,
   `create_thread`), `claude -p`, a cloud handoff and a scheduled task.
2. **Start.**
   - **Claude**: suggest a task card or chip whenever the work calls for one.
     The user starts it.
   - **Codex**: first ask the user with the ask-user tool (`agents.md`, "Ask
     setup questions"). Give the task, its worktree or branch, and its PRs.
     Start the session only when the user says yes. Codex permissions for new
     sessions are in `agents.md`.
3. **Report the start.** When the runtime confirms that the session started
   (a tool result or notice that says it started and gives its session or
   thread id), send:

   ```
   CHILD TASK STARTED — <your name> — <child task> — <tool> <child session id> — PRs <n ...|none>
   ```

   Use the child task text from its prompt, word for word: the coordinator
   matches it when the child's session id differs from the one the runtime
   gave you. Send it once per child. A card or chip that the user has not started is
   not a start: send nothing yet. A card the user dismisses never needs one.
   The coordinator records the child as pending under you, and the child's
   JOIN takes that entry over.

Subagents (Claude `Agent`, Codex `collaboration.spawn_agent`) need no
enrollment and no CHILD TASK STARTED.

**CodeRabbit cloud tasks** are the one exception to the enrollment line: a cloud
task cannot run `/puppet`, so put no enrollment line in its prompt. You may
start one on your own judgment for your own task, or for a self-contained
part of it (a cloud task can take code changes end to end). You need no user
request and no dashboard decision. Do not start one for parked work, or for
work that the user said to keep local. Keep the task local when it needs the
user's judgment often, local services, E2E or other leases, production or
shared-infrastructure access, or secrets. Run the preflight first
(`coderabbit code ls --agent --repo <worktree>`); if it fails, stay local.
A coordinator's message to offload is a suggestion: you decide. The other
limits in
[coderabbit-cloud.md](../master-of-puppets/references/coderabbit-cloud.md)
stay: the user answers for a plan approval, a billed `/implement`,
`authorize_github` and the delivery of a patch. Your coordinator relays that
answer only as section 3 says. Follow "Start" there. Run each start once. Then send
`CLOUD TASK — <name> — <taskId> — <url> — <task> — PRs <n>`; the coordinator
tracks the task. After a handoff of your own task, send LEAVE when your tree
is clean and your branch is pushed.

## 7. Leave

Your work is done when every PR of your task is MERGED, or the user drops the
task. Then stop your services, release any lease, send `LEAVE — <name>`.

Do not leave with uncommitted changes or an open PR. If the coordinator says
you are done while you have either, reply with what is left (for example
`UPDATE — <name> — Ready to commit — no PR yet`) and stay a member.
The exceptions are handoffs: after HANDOFF COMPLETE (section 8), or after
your task moved to a CodeRabbit cloud task (section 6), send LEAVE with the
PR still open. The successor owns it.

## 8. Hand off your task

Only when the user tells you to. The full protocol is in
[handoff.md](../master-of-puppets/references/handoff.md).

**You hand off:**

1. Push every commit. The tree is clean and local HEAD equals the remote
   branch. Uncommitted work does not go to a session of the other tool
   (Claude or Codex): finish and push it, or tell the user what is left.
2. Release your leases, stop the servers you started, and ask your
   coordinator to drop your queue entries.
3. Write the note at `$MACHINE_LEASE_DIR/handoffs/<task-slug>/HANDOFF.md`
   with the sections in `handoff.md`. Never keep its only copy in a worktree.
4. Send your coordinator
   `HANDOFF REQUEST — <name> — to <coordinator|any> — PRs <n> — note <path>`.
   Then stop work on the task. You stay a paused member.
5. On `HANDOFF COMPLETE — <name>`, send LEAVE. Same tool: leave the worktree
   for the successor. Other tool: your session removes its own worktree.
   On `HANDOFF COMPLETE — <name> — JOIN <coordinator>`, send JOIN to that
   coordinator and continue your task.

**You are the successor** (your kickoff names a handoff note):

1. Read the note before anything else. Check each PR with `gh pr view` and
   the branch head against the note.
2. The note's worktree is from the other tool: make your own worktree from
   `origin/<branch>`. Never work in the old one. Same tool: you may use it.
3. Send JOIN. Request your own leases; none move with the task.
4. You own the note's "Owned resources" and "Done when". Each destructive
   cleanup step follows the proxy model in section 3. Your own tool
   permissions and safety classifier stay the backstop for destructive
   actions.
