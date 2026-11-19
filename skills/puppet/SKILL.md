---
name: puppet
description: Join a master-of-puppets coordinator as a member ("puppet") and work your task under its directions until your PRs merge. Members report by message, and request, ask to extend and release their own leases; only the coordinator grants and extends, and it records membership and decisions. Use this at once when a prompt starts with "MASTER-OF-PUPPETS ENROLLED" (a prompt that starts with "MASTER-OF-PUPPETS SCOUT ENROLLED" uses the scout skill instead). Also use it when the user says "puppet", "join the coordinator", "join master of puppets", "enroll this session", "request a lease", "ask the coordinator for a lease", "extend the lease", "need more time on the lease", or "report to the coordinator".
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

**Puppets cannot have children.** You never start another session; ask your
coordinator with `TASK REQUEST` (section 6).

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
JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs <n> (base <b>) ... — <phase> — <planned heavy commands> — parent none — <ephemeral|long-running>
```

The parent field is always `parent none`: you answer to the coordinator, even
when another member's session started yours.

The last field is your lifetime:

- `ephemeral` (the usual case): you exist for this one task. When it is done,
  you send LEAVE (section 7).
- `long-running`: the user gave you a standing role (for example "answer all
  questions about X, do not leave"). You take task after task, go idle between
  them, and LEAVE only when the user tells you to (section 7).

Pick `long-running` only when the user's instructions say so. Otherwise send
`ephemeral`. The coordinator refuses a JOIN without this field.

When your task is background work (a sweep, or a run that a schedule
started), start `<task>` with `sweep:` or `scheduled:` in JOIN. The
coordinator can then put regular work first.

Send it, and every later message (UPDATE, MERGED, USER SYNC, STATUS replies,
TASK REQUEST, LEASE SIZE, LEASE RELEASED, IDLE, LEAVE), by the direct route
for your coordinator's tool (`protocol.md`, "Routes"). Never use `coordinator.py send`
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
  takes precedence over repair instructions. The coordinator retargets bases.
  You do every commit, push, conflict fix and review reply.
- **Auto-merge.** Your coordinator's `OK for auto-merge — #<n> — <method>`
  means your work is done and meets the agreed requirements. It comes once
  per PR. Then enable plain auto-merge: `gh pr merge <n> --auto --<method>`
  (no method flag for `auto`), never with `--match-head-commit`. Never enable
  it without the OK.
  - Keep it on across pushes that only fix review findings or CI.
  - Before a push that changes scope or behavior beyond the agreed
    requirements, turn it off (`gh pr merge <n> --disable-auto`), push, and
    ask again: `UPDATE — <name> — OK for auto-merge? — <what changed>`.
  - When it turns off for another reason (for example the host dropped it),
    enable it again with the same command.
- Report raw failures. Never weaken tests or rerun flakes to green.

## 4. Report

These reports go to your coordinator. Keep the recurring updates and STATUS
replies below; they do not require a matching user-facing update. For reports
to the user, follow [Reporting to the user](../master-of-puppets/SKILL.md#reporting-to-the-user).

- `UPDATE — <name> — <phase> — <newest fact>` on each change, and at least
  every 30 minutes while you work. While you are idle (section 7), send
  none. The coordinator checks on silent members each round, but your report
  is the record. It goes on the dashboard: keep
  the phase to 5 words and the fact to one plain sentence of 20 words. Write
  PRs as `#123`. No SHAs, test counts, paths or commands.
- `MERGED — #<n> — <merge sha>` for each merged PR.
- `USER SYNC — <one line>` whenever the user talks to you directly. The
  coordinator must know every decision.
- Answer `STATUS?` with phase, PR state, blockers and anything the user
  decided.
- When your coordinator asks you for a status, investigation result,
  recommendation, or other deliverable, send the requested answer directly
  to the coordinator before ending your turn, even if the request arrives as
  a user message in your thread and uses no protocol keyword. Use the
  verified originating thread when available, or the coordinator's verified
  roster route (`protocol.md`, "Routes"). A final reply in your own thread
  does not deliver the answer. Preserve the requested format and action
  limits. Check the send result, and report any delivery failure.
  Example: for a disk-cleanup request, send one line per worktree with what
  it contains, whether it is still needed, and push or discard. A discard
  recommendation does not authorize you to delete the worktree.

## 5. Leases (only when WELCOME says leases are on)

1. Finish all edits first. Queue the request yourself; no message is needed:
   `puppet.py request <CLASS> --coordinator <coord> --name <name> --minutes <estimate> --commands "<exact commands>" --worktree <worktree> [--gib <n>] [--cpus <n>] [--what "<short label>"]`.
   It picks the next id, `<coord>-q-<name>-<n>`, and prints it first as
   `ID <id>`; use that id in every later command. Give `--id <id>` only to
   change a request you already queued.
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
   - `--min-free-gib <n>` (pool classes, such as a VM pool): the free disk on the
     resource that your run needs. The pool grants only a resource with that
     much free, and cleans one first when it is under. Give it instead of
     releasing a grant for disk alone.
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
2. Start waiting at once: `puppet.py await-grant <CLASS> --id <id>`. It ends
   with one final line, and each line has its own exit code:

   | Final line | Exit | Do |
   | --- | --- | --- |
   | `GRANTED` | 0 | Run. This is the only grant. Your coordinator also sends LEASE GRANTED with the expiry. |
   | `DENIED` | 4 | Do not run and do not retry. Ask your coordinator why. |
   | `LEFT-QUEUE` | 3 | Do not run. Ask your coordinator. |
   | `TIMEOUT` | 5 | Do not run. You are still queued (or not queued yet): run `await-grant` again. |
   | `NEVER-QUEUED` | 6 | Do not run. Check the id with your coordinator. |

   **Run only on exit 0.** Gate the command on the exit code of the bare
   `await-grant`, for example `puppet.py await-grant BUILD --id <id> && <command>`.
   Never put `await-grant` in a pipe (`| tail`, `| tee`, `| grep`): the pipe
   returns the exit code of its last command, so a TIMEOUT can look like exit
   0. Never decide from a text match on the output. If you must read the
   text, only a final line that starts with `GRANTED ` is a grant.
   - Pool class with a recycle command (for example a VM pool): before `GRANTED`
     it resets the resource (`RECYCLING`, then `RECYCLED`). `RECYCLE-FAILED`
     (destroyed) or `RECYCLE-UNREACHABLE` (kept, marked failed) means you do
     not get that resource: your entry is queued again at the front
     (`REQUEUED`), so keep waiting. `release` resets the resource again.
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
   On `LEASE EXPIRED` (the server sends it to you at the expiry, once),
   ask the same way, or release at once. When a lease
   is expired for the class's reclaim time (default 10 min) and no process
   runs in your worktree, the server releases it as `fail`
   (`AUTO-RECLAIMED`). You then hold nothing: do not run under it, and
   request again with a new id.
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
   A process that started before the grant does not count. For one your run
   did not start (for example your own wait loop on a remote run), add
   `--ignore-pid <pid>` and say why in `--note`. `await-grant`, `extend` and
   `release` find the class from `--id`, so `<CLASS>` is optional there.
   On a pool class (a VM), each release checks the VM's free disk and
   memory; a VM under the floors is retired and deleted. `--result fail` alone
   keeps a healthy VM. When the VM itself is dirty or unusable, add
   `--retire-vm "<reason>"`: it is never granted again and the pool deletes it.
5. Project rules in WELCOME (from the coordinator's memory) can widen what
   needs a lease, for example a commit whose hooks run lint. Follow them.
6. What needs no lease: `leases.md`, "Classes", in the coordinator skill.

## 6. New tasks: ask your coordinator

Puppets cannot have children (user rule, 5 Nov: "puppets cannot have
children and all child sessions should be answering to coordinator
instead"). You never start, suggest or enroll another session yourself: no
task card or chip, no Codex thread, no `claude -p`, no scheduled task.

When part of your work should run as its own task, send:

```
TASK REQUEST — <your name> — <task, one line> — <why it is separate> — PRs <n ...|none>
```

Your coordinator decides. When it agrees, it enrolls the task under itself
and starts or suggests it; the new session answers to the coordinator, not to
you. A session that you started before this rule answers to the coordinator
too: it reports to the coordinator, never to you.

Subagents (Claude `Agent`, Codex `collaboration.spawn_agent`) are not
sessions: they stay inside your task and need no request.

**CodeRabbit cloud tasks** (only when your setup uses CodeRabbit): a cloud
task is not a session and has no enrollment line. Before you start one, read
[coderabbit-cloud.md](../master-of-puppets/references/coderabbit-cloud.md),
"Members": when you may start one, the preflight, the limits, and the
`CLOUD TASK` message you send.

## 7. Leave, or go idle

Your work is done when every PR of your task is MERGED, or the user drops the
task. Then stop your services and release any lease.

**Long-running member** (your JOIN said `long-running`): do not LEAVE. Send
`IDLE — <name> — <what wakes you>`, for example `IDLE — gw — a new question
from the user`. The coordinator checks that every PR of yours is MERGED or
CLOSED, your tree is clean and pushed, and you hold no lease or queue entry.

- `IDLE ACCEPTED`: you are idle. Send no UPDATE, and stop your watchers. The
  coordinator does not flag you as silent.
- `IDLE NOT ACCEPTED — <reason>`: you stay active. Do what the reason names.
- Any direction from the coordinator, or new work from the user, wakes you.
  Send `UPDATE` with the new task and phase; that makes you active again.
- LEAVE only when the user tells you to. Then follow the steps below.

**Ephemeral member**: send `LEAVE — <name>`.
Wait for the reply. `LEAVE ACCEPTED` ends your membership; only then archive.
`LEAVE NOT ACCEPTED — <reason>` means you stay a member: do what the reason
names, or ask the user. When no reply comes within 30 minutes, send `STATUS?
— LEAVE` once more; do not archive without an acceptance.

Do not leave with uncommitted changes or an open PR. If the coordinator says
you are done while you have either, reply with what is left (for example
`UPDATE — <name> — Ready to commit — no PR yet`) and stay a member.
The exceptions are handoffs: after HANDOFF COMPLETE (section 8), or after
your task moved to a cloud task (section 6), send LEAVE with the
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
   coordinator and continue your task. When your coordinator handed its whole
   stack to another one, this line comes from the new coordinator (it ran
   `adopt`): follow it as well. It is not a reason to ask the user.

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
