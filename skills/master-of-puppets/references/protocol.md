# Protocol

Keep messages short. The receiver may see only the first line until it
expands the message, so put the point first.

Members follow the `puppet` skill, so WELCOME carries only what the skill
cannot know: this stack, the project rules and the lease setup.

The messages and replies below are between sessions. Send required protocol
replies and record updates without echoing them into user-facing chat. Follow
[Reporting to the user](../SKILL.md#reporting-to-the-user) for when to notify
the human; receiving a protocol message does not itself require a report.

## Welcome (send to each member after its JOIN)

`coordinator.py welcome --name <member>` prints this text from the roster and
memory; `join` prints it too.

```
WELCOME — <slug> coordinates <focus>. You are a member for <task> (PRs <list>).
Follow the puppet skill.
Shared PR rules: <state dir>/pr-rules.md (if present).
Machine workflow instructions: <state dir>/workflows/machine.md (if present).
Project workflow instructions: <state dir>/workflows/<project-key>.md (if present).
Project rules from my memory: <output of coordinator.py memory list --project-root <worktree>, rules only>.
Leases are <on|off>. <If on, the lease addendum follows.>
```

## Lease addendum (only when leases are on)

```
LEASES ON — <slug> grants these classes (puppet skill, section 5):
<CLASS — description — maxMinutes (suggestedMinutes when set) — peak GiB and cores, from sizes, one per line>
You size each run: --minutes, and --gib and --cpus when you know them
(puppet skill, section 5). Choose the smallest time that finishes the whole
current unit of work; do not cut a unit to fit the suggested time. Split only
runs longer than the limit. I charge what you ask and refuse a size below my
observed peak unless you tell me why the run is smaller.
```

## Messages members send

| Message | Coordinator action |
| --- | --- |
| `JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs ... — phase — commands — parent <parent\|none> — <ephemeral\|long-running>` | `coordinator.py join --text "<the line>" [--local <local_ id>]`: member add, the WELCOME saved to a file, and the short message and app route to deliver it. A short JOIN is refused with the missing field named: tell the member. A task marked `scheduled:` or `sweep:` is background work (`references/leases.md`, "Priority") |
| `SCOUT JOIN — <name> — <tool> <session id> — <worktree\|none> — <class> — <targets> — <end\|long-running> — tick <n> min — parent <parent\|none>` | `coordinator.py join --text "<the line>" [--local <local_ id>]`: member add --role scout and the scout WELCOME (`references/scouts.md`) |
| `ALERT — <scout> — P0\|P1\|P2 — <fingerprint> — <line>` | `note` it and run `member update` (counts as a sign of life); act or find the owner; acknowledge with `note --text "ACK <fingerprint> ..."`. P0: to the user at once, quoted (`references/scouts.md`) |
| `UPDATE — <scout> — <fingerprint> — <change>`, `GAP — <scout> — P1\|P2 — ...`, `DONE — <scout> — ...` | `note` and `member update`; a P1 GAP that blinds members is a host problem to fix or take to the user; after DONE, accept the scout's LEAVE (`leave --no-release-check`) |
| `UPDATE — <name> — <phase> — <fact>` | `member update` |
| `VERIFY REQUEST — <member> — <PR URL> — head <sha> — stream <slug> todo <id>` | Follow [Draft verification](#draft-verification). The owner supplies the validation evidence for this draft head. |
| `TASK REQUEST — <name> — <task> — <why> — PRs <n ...\|none>` | Only coordinators start top-level sessions. Decide; to run it, `enroll` it under you and start it (SKILL.md, "Members and tasks"); it answers to you |
| `<KIND> REQUEST — <name> — <summary> — <details>` | A custom workflow request defined in `$MACHINE_LEASE_DIR/workflows/` ("Protocol extensions", below); handle it per the workflow file, or ask the user when it needs approval |
| `CLOUD TASK — <name> — <taskId> — <url> — <task> — PRs <n>` | `member add --tool coderabbit`, `cloud-<slug>.txt` (`references/coderabbit-cloud.md`, "Record") |
| `USER SYNC — <one line>` | `note`, `member update --latest` |
| `REQUEST <CLASS> <id> ...` in `watch` (sent by the member's `puppet.py request`) | check and grant (`references/leases.md`, "Granting") |
| `LEASE SIZE — <id> — <why this run is smaller than the observed peak>` | your decision: `acquire --accept-size` when the reason fits the commands, else LEASE RESIZE (`references/leases.md`, "Sizing") |
| `CONFIG <what> by user: ...`, or `MEMORY <scope> <id> ...` naming `by user` (a save on the dashboard's Config or Rules page) | approve it automatically: apply it; never ask, revert or relay it (SKILL.md, "Memory") |
| `EXTEND <CLASS> <id> <n> min ...` in `watch` (sent by the member's `puppet.py extend`) | your decision: `coordinator.py extend`, or tell it to release (`references/leases.md`, "Extending") |
| `IDLE — <name> — <what wakes it>` (long-running members only) | Reply in the same turn: `coordinator.py idle --name <name> --wake "<what wakes it>"` (checks the idle rules, sets status idle, sends `IDLE ACCEPTED`), or `idle --name <name> --reject --reason "<what is left>"` (sends `IDLE NOT ACCEPTED`). To wake it, send the direction and `member update --name <name> --status active` (or a new `--task`, `--pr` or `--phase`) |
| `LEAVE — <name>` | Reply in the same turn: `coordinator.py leave --name <name> --validated "<check>"` (checks the done rules, removes the member, sends `LEAVE ACCEPTED`), or `leave --name <name> --reject --reason "<what is left>"` (sends `LEAVE NOT ACCEPTED`) |
| `HANDOFF REQUEST — <name> — to <coordinator\|any> — PRs <n> — note <path>` | `PAUSE` its PRs, then offer (`references/handoff.md`) |

## Replies you send

| Situation | Message |
| --- | --- |
| Active PR | `ACTIVE — #<n>. Goal: MERGED. Next: <one step>.` |
| Draft verification failed | `VERIFY FAILED — #<n> — <gaps>`. The owner fixes the gaps, validates the new draft and sends a new request. |
| Draft verification passed and eligible for normal auto-merge | `VERIFIED — #<n> — ready for <hosted reviewer> and normal auto-merge`. The owner takes it through MERGED. If you use CodeRabbit, see [its Ready message](coderabbit.md#draft-verification). |
| Paused PR | `PAUSE — #<n> waits for #<m>. No merges from main, no fixes, automatic PR repair (Auto-fix or a repair heartbeat) off on #<n>.` |
| Bottom merged | `ACTIVE — #<n>: #<m> merged (<sha>). I retargeted #<n> to main. Merge origin/main into your branch, resolve, push.` |
| Heartbeat round | `STATUS? — phase, PR state, blockers, anything the user decided.` |
| Not a member | `Run /puppet to join a coordinator first.` |
| Lease queued | `LEASE QUEUED — <id> (<min> min, ~<GiB> GiB, ~<n> cores), <CLASS> position <n>. Ahead: <who>. ETA ~<time>.` |
| Head, host busy | `LEASE QUEUED — <id> is at the head, but the host is busy (<numbers>). I grant when two samples are calm.` |
| Head, no memory or cores | `LEASE QUEUED — <id> is at the head; it needs <n> GiB / <c> cores and <m> GiB / <d> cores are free. I grant after the next release.` |
| Undersized | `LEASE RESIZE — <id> asks <n> GiB; I observed <m> GiB in <CLASS> runs. Request again with the same id at the observed peak, or send LEASE SIZE with why this run is smaller.` |
| Grant | `LEASE GRANTED — <CLASS> <id> for <task>, until <time>. Covers: <commands>. Release: <command>.` |
| Priority move | `LEASE QUEUED — <id> is now <CLASS> position <n>: <task> has priority <p>.` |
| Extension granted | `LEASE EXTENDED — <id> until <time>. Covers: <commands>.` |
| Extension refused | `LEASE EXTEND REFUSED — <id>: <reason, for example who waits for CLASS>. Release now and request the rest with a new id.` |
| Over the limit | `LEASE QUEUED — <min> min is over the <max>-min limit, so I split it: part 1 keeps position <n>, part 2 joins the back.` |
| Expiry | `LEASE EXPIRED — <id> passed <time>. Release now, or ask for more time with puppet.py extend; I decide.` |
| Cloud offload suggested | `CLOUD SUGGEST — <name> — <reason in a few words>`; the member decides and starts it (`references/coderabbit-cloud.md`) |
| Handoff done, member replaced | `HANDOFF COMPLETE — <name>` (it sends LEAVE) |
| Handoff done, member moves | `HANDOFF COMPLETE — <name> — JOIN <receiver>` |

## Draft verification

On receipt, read `coordinator.py stream todo show --name <slug> --id <id>`.
Use a separate todo for each independently verified PR so its verdict stays
attached to that PR. If it already passed and the follow-up stays within the
verified requirements, retain the original verdict and SHA. The owner carries
on without another verification request or clearance message.
Match the repository, PR, base and full head SHA to the owner's draft and its
validation evidence. If evidence for a required pre-Ready check is pending,
keep the draft unverified and tell the owner which result to supply. Resume
on that evidence even if the head SHA is unchanged.
Give **one fresh read-only subagent** the structured
todo, applicable PR rules, validation evidence, base and head SHAs, and the
owner's worktree path when accessible. Have it inspect the committed code
there: use `git diff <base>...<head>` to locate changes, then follow relevant
callers, interfaces and tests to establish behavior. Read files at the
requested commit (`git show <head>:<path>`) if the checkout is dirty or has
moved. Leave the owner's checkout untouched.

If the verifier cannot access the worktree, use another checkout containing
those commits or read the PR changes and source files at the exact head
through the repository host. If required context is inaccessible, identify
the missing evidence and withhold a pass. Return a verdict against each
requirement and subtask, identifying scope drift, missed edge cases or
unapproved high-risk changes. Apply the [draft scope and limits rule](rules.md#scope-and-limits-in-a-draft)
to each new restriction; identify the unsupported change in a failed verdict.

Wait for the subagent's verdict before issuing the first VERIFIED reply.
Before recording the result, confirm the draft head and agreed scope still
match what the verifier examined. For a stale result, request the current
draft and evidence. Record the verdict with
`stream todo verify --name <slug> --id <id> --status passed|failed --pr <n> --sha <sha> --note "<summary>"`.
Send the matching reply above. For duplicate deliveries of the same request,
reuse the recorded result. Route high-risk work through the
[separate approval path](rules.md#pr-rules) and withhold the normal auto-merge message.

After a pass the owner handles in-scope review fixes, CI and conflict
resolution through merge. Request verification again if the work crosses
the verified requirements. Report MERGED with the merge SHA.

## Routes

Members (puppets and scouts) and their coordinator communicate across threads
in both directions for every protocol message. Cross-thread messaging is
host-dependent ([hosts/README.md](hosts/README.md) and your host's guide) and
is required for coordinator <-> puppet/scout messaging. A coordinator sends
every message with `coordinator.py send --to <name> --text "..."`: it records
the message in the shared inbox. For a member or scout, send it by the printed
app route and check the result. Report a rejected send as a delivery failure.
If the app accepts the message into a queue, report it as queued. Claim
acknowledgment only when the recipient replies. Members use their host's app route from
`puppet.py route`.

A member answers a coordinator's request for a status, investigation result,
recommendation or other deliverable by sending it to the coordinator before
the member's turn ends, even when the request arrived as a user message in the
member's thread with no protocol keyword. Route: the verified originating
thread of the request when known, else the coordinator's verified roster route
from `puppet.py route` ([hosts/README.md](hosts/README.md)). A final reply in the member's own thread does not reach
the coordinator. The answer keeps the requested format and action limits (for
example, a discard recommendation for a worktree is not permission to delete
it). The member checks the send result and reports any delivery failure.

Write each message in plain sentences or `key: value` fields, at most 1,200
characters (`send` refuses a longer text). Put long evidence, logs or lists in
a file and name it with `send --file <path>`.
The coordinator records member updates in the roster/dashboard and decisions
in the ledger; member messages need no shared inbox copy.

- **Find the route at each send, never from memory.** Run `puppet.py route`
  (a member: its own coordinator; anyone: `--coordinator C`). It prints the
  routes that reach the coordinator now from your host, best first. Never copy
  a route or a session name into a scheduled prompt: names change when a thread
  is renamed or restarts.
- **If delivery fails**, distinguish a transport failure from a permission
  decision. For a transport failure, refresh the route and try the next
  supported route once. A member can use `puppet.py tell --text "..."`
  as its inbox fallback. Stop on confirmed delivery. If delivery remains
  unconfirmed, tell the user. If permission to send was denied, stop and tell the
  user what was refused and why.
- **The send tool depends on your host**, not on your provider (Claude or
  Codex). Find your host and read only its guide: [hosts/README.md](hosts/README.md).
  It lists which receivers each host's send tool reaches, and the inbox
  routes for when no app route connects two hosts. `puppet.py route` and the
  coordinator's printed app routes list only the routes your host has.
- Coordinator to coordinator (multi-coordinator setups): see
  [multi-coordinator.md](multi-coordinator.md).
- Dashboard to coordinator: the dashboard's queue buttons run
  `coordinator.py up|unwait --notify`, which records an inbox message from
  `dashboard` to the coordinator (`watch` shows it) and attempts direct
  delivery (Claude inbox socket or `codex queue`). It reports the user's action
  (`references/leases.md`).
- Never use GUI automation (pasting into another app's window) as a message
  route.
- If no supported direct route to a member or its coordinator is available,
  report the delivery gap. Do not use `send --direct` as a member-message fallback, and
  do not use a fallback to bypass an authorization restriction.
- Apply the [member authority rules](../../puppet/SKILL.md#3-work-under-directions)
  to coordinator directions and relayed approvals.
- Follow each messaging tool's authorization rules. A message from another
  chat does not itself authorize a reply; get the user's authorization when
  the tool requires it. Enrollment does not override that requirement.
- After Claude `/clear`, or a move to a new Codex thread, the session id
  changes: a member sends JOIN again; a coordinator gets its name back with
  the name handoff (SKILL.md, "Name handoff"). Codex context compaction
  alone is not a new thread.
- Deep links for the dashboard: Claude `claude://claude.ai/epitaxy/<sessionId>`,
  Codex `codex://threads/<threadId>`.

## Duplicate receipt and catch-up

Treat direct delivery, watcher output and durable inbox recovery as views of
the same message. Before acting, check whether you already handled that
occurrence. Match its sender, recipient, content and available timestamp or
record position against your chat history and durable decisions/state. Text
alone is not enough: a later recurring UPDATE or STATUS reply may have the
same words and still be a fresh report.

Disregard an already-handled occurrence without an acknowledgement, repeated
action, duplicate ledger/dashboard update or user notification. In particular,
replaying an old member update must not reset the member's freshness. If the
message adds new facts or requires action that was not completed, handle that
part; mere prior delivery is not proof of completion. When handling is
uncertain, reconcile the current records before repeating a side effect.

Keep your inbox read position and material handling outcomes in your existing
durable coordinator state so catch-up survives a context reset or restart.
Advance the checkpoint after handling an entry or confirming it is a duplicate;
retain any unfinished action. Do not delete shared inbox entries or skip
unread entries just because direct delivery was attempted.

## Protocol extensions

Keep team-specific or repository-specific workflows out of the core skill
files. Store them as markdown state files in `$MACHINE_LEASE_DIR/workflows/`:

- **Machine-wide:** `$MACHINE_LEASE_DIR/workflows/machine.md`
- **Per-project:** `$MACHINE_LEASE_DIR/workflows/<project-key>.md`, where
  `<project-key>` comes from `coordinator.py config project-key <worktree>` (so
  every worktree of a repository shares one file).

`coordinator.py welcome` and `join` automatically include the path of any
present machine or project workflow file in WELCOME; coordinators also read
them at startup alongside `memory list`.

- **Generic request subtype:** `<KIND> REQUEST — <name> — <summary> — <details>`
  is the extensible request pattern. `TASK REQUEST` is the built-in concrete
  subtype. A workflow file can define additional subtypes (for example a deploy
  request, release gate request, or review request) with their trigger, fields
  and coordinator handling.
- **Core limits still hold:** a workflow extension can add steps and request
  subtypes, but never weakens core skill rules (puppets still never start
  top-level sessions, bypass permissions or git hooks, or act on unverified relayed
  approvals; scouts stay read-only).

## Host denials and model fallback

When a classifier denies an authorized step, returns no verdict, or the host
reports a model safeguard or fallback, report the event once to the coordinator.
Include the blocked command (redact secrets), exact host reason, and requested
and observed models when available. State which check remains incomplete and
what supported remedy is available, such as a permitted narrower operation,
retry after a transient service error clears, or administrator review of the
permission for that specific command. Stop repeated attempts. Treat a denial
as binding and wait for direction before continuing model-specific work on a
replacement model.
