---
name: puppet
description: Join a master-of-puppets coordinator as a member ("puppet") and work your task under its directions until your PRs merge. Members report by message, and request, ask to extend and release their own leases; only the coordinator grants and extends, and it records membership and decisions. Use this at once when a prompt starts with "MASTER-OF-PUPPETS ENROLLED" (a prompt that starts with "MASTER-OF-PUPPETS SCOUT ENROLLED" uses the scout skill instead). Also use it when the user says "puppet", "join the coordinator", "join master of puppets", "enroll this session", "request a lease", "ask the coordinator for a lease", "extend the lease", "need more time on the lease", or "report to the coordinator".
---

# Puppet

You are a member of a coordinator session. The coordinator owns the stack,
the roster, the ledger, the dashboard and the leases. You do the task: code,
tests, commits, pushes, PR fixes. You never write the roster, ledger, dashboard
or shared inbox; you send messages, and the coordinator records them. The only
state you write directly is through `puppet.py request`, `puppet.py extend`,
`puppet.py release` (your own lease queue, state and measurement history),
`puppet.py tell` (an inbox fallback when no app route works), and your handoff
note (section 8). You cannot grant or extend a lease; only your coordinator
does. Do not request, change or release someone else's lease.

**Delegate independent parts of your assignment to subagents** (section 6).
You own the combined result and report it to the coordinator.

**On a watcher, schedule, or coordinator message, work quietly by default.**
Check the event against current state, take the required action, and send any
required protocol report to the coordinator. End the turn quietly if the user
has nothing new to act on or learn under
[Reporting to the user](../master-of-puppets/SKILL.md#reporting-to-the-user).
This applies to progress commentary and the final reply. Skip local check
tallies and recaps for an older head, an already-resolved thread, or another
passing check while a PR still waits for review. Answer a direct human
question in this thread even when the answer is “still waiting.”

**Find your host first** ([hosts/README.md](../master-of-puppets/references/hosts/README.md),
"Find your host"; run `puppet.py host`), then read only your host's guide.
In T3 Code, send to your known coordinator thread with `mode: "auto"`. If the
ID is missing or T3 rejects the route, refresh with `puppet.py route`, then send
once with `auto`. Follow the host guide for inbox fallback and the
permission-denial stop. Use the verified destination and
failure handling in [Protocol routes](../master-of-puppets/references/protocol.md#routes)
for JOIN and all later messages. To recover a message from your coordinator,
read `puppet.py inbox --from <coordinator> --to <member>`. Use only member routes. Direct writes to
the shared inbox, including through helper modules, bypass member identity.

Below, `puppet.py` means `python3 -I "${MACHINE_LEASE_DIR:-$HOME/.local/state/machine-leases}/puppet.py"`.
In a sandboxed session (Codex, Antigravity ACP), use the host’s per-command approval for
`puppet.py` calls that need the helper server, including `host`. Explicit
`--help` and `-h` use the local parser. In a shell, define it as a function, not a variable (zsh does not split a
variable into words): `puppet() { python3 -I "${MACHINE_LEASE_DIR:-$HOME/.local/state/machine-leases}/puppet.py" "$@"; }`.
If the file does not exist, no coordinator
runs on this machine: tell the user, and suggest `/master-of-puppets` in the
session that should coordinate.

## 1. Find your coordinator

- Your prompt starts with `MASTER-OF-PUPPETS ENROLLED — <coord> ...`: that
  coordinator. When the line names you as member `<name>`, use that name.
  Do not ask. Enrollment is mandatory: join before you do any other work,
  and do not skip it or ask whether to join.
- Otherwise run `puppet.py roster` and join the live coordinator (a
  coordinator is live while its heartbeat is newer than 40 minutes). When none
  is live, ask the user. When more than one coordinator runs, pick the one
  whose `prs` or `focus` covers your task, or ask the user when none or
  several fit.
- Your name: the one from the enrollment line, else your session title as a
  short slug. Your session id: your host guide.
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

On re-enrollment, keep your standing workstream lifetime until the user ends the role.
Completing a task or release moves a standing owner to IDLE (section 7).

Pick `long-running` only when the user's instructions say so. Otherwise send
`ephemeral`. The coordinator refuses a JOIN without this field.

When your task is background work (a sweep, or a run that a schedule
started), start `<task>` with `sweep:` or `scheduled:` in JOIN. The
coordinator can then put regular work first.

Outside T3 Code, when your session id
changes (a `/clear`, a new thread, or a move from Claude to Codex or back),
send JOIN again from the new session and stop the old one (`protocol.md`,
"Routes").

**After a context handoff, a summary or a provider switch, run `puppet.py whoami` first,** before any other work. Count as a switch any sign that your provider or model changed: a "provider context handoff" message, a model name you did not start with, or a coordinator that asks you to run it. In T3 Code a provider switch keeps the thread, and that command moves your roster entry to the new session (hosts/t3-code.md, "Provider switch in a thread"). The handoff text may not say that you are a member: trust `whoami`, not the summary. Its note that the helpers are older than the skill copy is for your coordinator: do not report it. Send JOIN again only when it says you are not in the roster.

Wait for WELCOME: after you send JOIN, end your turn; WELCOME arrives as a message. Do not poll for it with `sleep` or thread reads. WELCOME tells you whether leases are on and gives the rules,
including the project rules from the coordinator's memory and any machine or
project workflow instruction files (`$MACHINE_LEASE_DIR/workflows/`). Read any
workflow files named in WELCOME before you work; they can add workflow steps
and custom `<KIND> REQUEST` subtypes (`protocol.md`, "Protocol extensions"). If
`puppet.py host` reported `unknown`, run `puppet.py host --set <host>` now that
you are in the roster. You can read memory rules yourself with
`puppet.py memory list --project-root "$PWD"`; only the coordinator writes
them. If the user tells you a new project rule, send it as `USER SYNC` so the
coordinator records it. Do not work a PR until the coordinator sends ACTIVE or
PAUSE for it.

The user can also change rules on the dashboard. You then get a `MEMORY ...`
message that names `by user`. Machine-wide config changes go to the
coordinator only; your coordinator tells you what changes for your task. A rule `by user`
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

Use standing authorization for assigned builds, read-only checks and cleanup.
Report a host denial or unexpected model fallback once using the
[host denial protocol](../master-of-puppets/references/protocol.md#host-denials-and-model-fallback).
Preserve required checks, branch protections and git hooks.

- **ACTIVE — #n**: work #n to MERGED. The coordinator retargets stacked PRs.
- **PAUSE — #n**: stop repairs, updates from the base branch and automatic
  PR repair on #n until ACTIVE. Disable auto-merge if it was enabled.
- **Prepare the draft.** Run the [applicable local checks](../master-of-puppets/references/rules.md).
  Commit, push, and open or update the **draft** PR. If the user requires
  permission before a commit or PR, ask and report the blocker. Bind the PR
  as your host guide directs.
- **Request verification before marking Ready.** Before sending the draft, check
  every new limit or gate against the [scope and evidence rule](../master-of-puppets/references/rules.md#scope-and-limits-in-a-draft).
  Remove unsupported restrictions and move unrelated policy proposals out of
  an incident fix. Send your coordinator
  `VERIFY REQUEST — <member> — <PR URL> — head <sha> — stream <slug> todo <id>`
  once the checks required before Ready have passed. Include the PR worktree
  path when available and the evidence for that head. If a required check is
  blocked, report the blocker and keep the PR in draft. On `VERIFY FAILED — #<n> — <gaps>`,
  keep the PR in draft, address the gaps, validate the corrections, push and
  send a new request.
- **Deliver the verified ordinary PR.** On
  `VERIFIED — #<n> — ready for <hosted reviewer> and normal auto-merge`,
  mark the PR Ready. Handle hosted review findings, CI and merge conflicts.
  Enable normal auto-merge yourself when the applicable gates allow it.
  Use the configured method, or omit the method for a merge queue. If your
  setup uses CodeRabbit, see [the reviewer guidance](../master-of-puppets/references/coderabbit.md).
  - Keep ownership through routine follow-up pushes. A review fix, CI repair
    or conflict resolution within the verified requirements needs no further
    coordinator read or approval. If normal auto-merge drops, restore it
    when the same conditions hold.
  - Before pushing a substantive change beyond the verified requirements,
    disable auto-merge and return the PR to draft. Agree on the new scope,
    push and validate the revised head, then request verification again.
  - For database migrations, Terraform or infrastructure outside any
    exception in the project’s PR rules, new customer-facing config or flags,
    cross-stream conflicts, or an admin merge request, keep auto-merge off.
    Send the risk to the coordinator for separate explicit approval and
    follow the [manual approval rules](../master-of-puppets/references/rules.md).
  - An app watch may end at merge without a merged event. Check PR state at
    each wake until MERGED. In the turn you see the merge, send `MERGED` and
    any workflow follow-up defined in WELCOME.
- Report raw failures. Never weaken tests or rerun flakes to green.

## 4. Report

Send reports through your coordinator route. Check who originated the turn:
a host can deliver a coordinator request in a message labeled “user.”

- Send `UPDATE — <name> — <phase> — <newest fact>` when the work changes
  phase, a blocker changes, or a result affects the next step. While actively
  working, send a heartbeat UPDATE at least every 30 minutes. Combine routine
  CI progress for the same PR into the next due update when it leaves the
  next action unchanged. Send blockers, decisions and required protocol
  requests promptly. Idle members
  send none (section 7).
- On a scheduled wake, send any due report even if the wake prompt omits the
  send step. Otherwise finish quietly. Sending a report also completes the
  reporting step; do not copy it into local chat.
- Apply instruction-only broadcasts quietly. Reply to the sender if it asks
  for confirmation or the change blocks your work.
- The UPDATE appears on the dashboard. Keep its phase to five words and its
  fact to one plain sentence of at most 20 words. Use `#123` for a PR. Omit
  SHAs, test counts, paths and commands from this message.
- `MERGED — #<n> — <merge sha>` for each merged PR.
- `USER SYNC — <one line>` whenever the user talks to you directly. The
  coordinator must know every decision.
  When a send of it is refused or rejected (for example an approval reviewer
  says the coordinator's earlier direction conflicts), do not drop the
  user's request in silence: tell the user in your thread what was refused
  and why, and ask how to go on.
- Answer `STATUS?` with phase, PR state, blockers and anything the user
  decided.
- When you catch yourself saying “I would,” “I recommend,” or “we could,”
  send the coordinator the concrete next step and why it matters. If it is
  yours to take and already authorized, take it and report the result.
  Otherwise, say what decision or help you need.
- Deliver requested results to the coordinator before ending the turn, using
  Protocol routes above. If work continues, send what is ready, what remains
  and when you expect it.

## 5. Leases

If a brief asks for a lease and the local mode is unclear, check `puppet.py roster`.
With leases off, run authorized local checks directly using the repository's CPU-budget
commands where available. With leases on, follow the request procedure below.

Command card (use these; do not guess commands or read the helper source):

```
puppet.py request <CLASS> --coordinator C --name N --minutes M --commands "..." --worktree W [--gib G] [--cpus K]
puppet.py await-grant <CLASS> --id ID          # waits; prints QUEUED position, GRANTED, or TIMEOUT
puppet.py await-grant <CLASS> --id ID --timeout-min 0   # the request's state now, without waiting
puppet.py extend <CLASS> --coordinator C --name N --id ID --minutes M --reason "..."
puppet.py release <CLASS> --id ID --result pass|fail|partial [--note "..."]   # a request not granted yet: no --result; WITHDRAWN
puppet.py events --id ID                       # what happened to your request or lease
```

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
   - Exit 3 with `leases are off; run the commands without a lease`: proceed directly.
   - Other exit 3 refusals (not a member, a foreign id, or the id is
     already held). Fix what it names; ask your coordinator when you cannot.
   To change your request (commands, size), run `request` again with the
   same id; your coordinator sees the change. On `LEASE RESIZE`, do the same,
   or send `LEASE SIZE` with your reason. You cannot set a priority or
   jump the queue. When the user wants your task to go first, send it as
   `USER SYNC`; the coordinator decides. To drop a request that was not
   granted yet, run `release` with its id: it prints `WITHDRAWN`.
2. Start waiting at once: `puppet.py await-grant <CLASS> --id <id>`. It ends
   with one final line, and each line has its own exit code:

   | Final line | Exit | Do |
   | --- | --- | --- |
   | `GRANTED` | 0 | Run. This is the only grant. Your coordinator also sends LEASE GRANTED with the expiry. |
   | `DENIED` | 4 | Do not run and do not retry. Ask your coordinator why. |
   | `EXPIRED` | 3 | Start no work. Ask for an extension or release the expired lease. |
   | `LEFT-QUEUE` | 3 | Do not run. Ask your coordinator. |
   | `TIMEOUT` | 5 | Do not run. You are still queued (or not queued yet): run `await-grant` again. With nothing else to do, wait with the default timeout (30 min), not `--timeout-min 1` in a loop: each short poll costs a turn and changes nothing. |
   | `NEVER-QUEUED` | 6 | Do not run. Check the id with your coordinator. |

   **Run only on exit 0.** Gate the command on the exit code of the bare
   `await-grant`, for example `puppet.py await-grant BUILD --id <id> && <command>`.
   Run unrelated lookups in separate tool calls. A pipeline or a later
   command in the same shell invocation can replace the waiter's exit 5 with
   its own exit 0. A queued-position line alone never authorizes work.
   - Pool class with a recycle command (for example a VM pool): before `GRANTED`
     it resets the resource (`RECYCLING`, then `RECYCLED`). `RECYCLE-FAILED`
     (destroyed) or `RECYCLE-UNREACHABLE` (kept, marked failed) means you do
     not get that resource: your entry is queued again at the front
     (`REQUEUED`), so keep waiting. `release` resets the resource again.
   Never write polling loops. Your position can change: the queue goes by
   priority, then FIFO, and your coordinator sets the priority. Keep
   waiting; `await-grant` follows the queue and prints `QUEUED ... position
   <n> of <m>` each time your place changes. Do not read the lease files
   yourself, and send no message about the wait.
3. Run only the granted commands and cleanup of resources they started.
   Use it or return it: no edits or repairs while holding a lease. On failure,
   clean up owned resources, release promptly and report the raw failure;
   repair; request again with a new id. When cleanup cannot finish (for
   example the resource is unreachable), release it yourself with
   `--result fail --note "cleanup blocked: <why>"`; never ask the coordinator
   to release it for you. The coordinator handles the resource's recovery.
   **More time.** Extension is your coordinator's decision. When the run
   needs longer than the grant, ask before it expires:
   `puppet.py extend <CLASS> --coordinator <coord> --name <name> --id <id> --minutes <n> --reason "<what still runs>"`.
   It changes nothing by itself; your coordinator sees the request (no
   message is needed) and replies `LEASE EXTENDED` with the new expiry, or
   tells you to release. Until then the old expiry holds. When no answer comes
   in 5 minutes, check `puppet.py events --id <id>`: an `extend` line there
   means it was extended and the message was lost. Start no new
   commands meanwhile, and release at once on a no.
   - Exit 2: the whole run would be over the class limit. Release with
     `--result partial` and request the rest with a new id.
   - Exit 3: not a member, not your lease, or not held. Fix what it names.
   On `LEASE EXPIRED` (the server sends it to you at the expiry, once),
   ask the same way, or release at once. For a delayed notice, check
   `puppet.py events --id <id>` first. A later release or reclaim closes
   the notice; a later extension supplies the current expiry. When a lease
   is expired for the class's reclaim time (default 10 min) and no process
   runs in your worktree, the server releases it as `fail`
   (`AUTO-RECLAIMED`). You then hold nothing: do not run under it, and
   request again with a new id.
4. For E2E, stop the servers you started before releasing, including on
   failure. Release:
   `puppet.py release <CLASS> --id <id> --result pass|fail|partial --note "<one line: what passed, or the first failure>" [--port <n> ...]`.
   Add `--port` for each port your E2E stack used. The command records the
   run minutes and the measured peak GiB and cores (your next sizing reads
   them), the result, and counts what your run left in the worktree (`drained=<n>`),
   so nobody asks you for a receipt. Then send
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
6. What needs no lease: [leases.md](../master-of-puppets/references/leases.md), "Classes".

## 6. Delegate independent work and request new tasks

Start subagents when two or more parts of your assignment can proceed
independently. For example, have one trace a request through the code while
another checks read-only logs or SQL, or divide an audit by component.
Keep dependent steps together.

Give each subagent a concrete question or file scope, the expected result,
and the applicable repository instructions (for example `FRONTEND.md` or
`DESIGN.md`). Pass on read-only restrictions, approval limits and any
ACTIVE or PAUSE direction. A subagent works under your enrollment.

For concurrent implementation, assign disjoint files and give each editing
subagent a separate worktree and branch from the intended base. When edits
overlap, integrate them sequentially. Collect and inspect the changes,
resolve integration issues, and run the combined checks. When BUILD leases
are on, serialize heavy local builds, tests and push hooks under your
granted BUILD lease within its command scope. Queue a new lease if needed.
You own integration, delivery and the report to the coordinator.

When part of your work should run as its own task, send `TASK REQUEST` (the
built-in subtype of the generic `<KIND> REQUEST` form in `protocol.md`,
"Protocol extensions"; workflow files in WELCOME may define additional request
subtypes for your setup):

```
TASK REQUEST — <your name> — <task, one line> — <why it is separate> — PRs <n ...|none>
```

Only the coordinator enrolls and starts a new top-level session. Subagents
within your assignment need no separate enrollment or TASK REQUEST.

**CodeRabbit cloud tasks** (only when your setup uses CodeRabbit): a cloud
task is not a session and has no enrollment line. Before you start one, read
[coderabbit-cloud.md](../master-of-puppets/references/coderabbit-cloud.md),
"Members": when you may start one, the preflight, the limits, and the
`CLOUD TASK` message you send.

## 7. Leave, or go idle

Your work is done when every PR of your task is MERGED, or the user drops the
task. Then stop your services and release any lease.

**Long-running member** (your JOIN said `long-running`): when your assignment
finishes, send your coordinator
`IDLE — <name> — <what wakes you>`, for example `IDLE — gw — a new question
from the user`. A standby note in your own thread leaves your roster status active.
Wait for the coordinator’s IDLE reply. The coordinator checks that every PR of yours is MERGED or
CLOSED, your tree is clean and pushed, and you hold no lease or queue entry.

- `IDLE ACCEPTED`: stop your watchers and end the turn quietly. The
  coordinator already recorded your idle status.
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
