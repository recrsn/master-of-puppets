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

```
WELCOME — <slug> coordinates <focus>. You are a member for <task> (PRs <list>).
Follow the puppet skill.
Shared PR rules: <state dir>/pr-rules.md (if present).
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
| `JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs ... — phase — commands — parent <parent\|none>` | `member add [--parent <parent>]`, then WELCOME. A task marked `scheduled:` or `sweep:` is background work (`references/leases.md`, "Priority") |
| `UPDATE — <name> — <phase> — <fact>` | `member update` |
| `CHILD TASK STARTED — <name> — <child task> — <tool> <child session id> — PRs <n ...\|none>` (after the runtime confirms the start) | `child --parent <name>` (puppet skill, section 6) |
| `CLOUD TASK — <name> — <taskId> — <url> — <task> — PRs <n>` | `member add --tool coderabbit`, `cloud-<slug>.txt` (`references/coderabbit-cloud.md`, "Record") |
| `USER SYNC — <one line>` | `note`, `member update --latest` |
| `REQUEST <CLASS> <id> ...` in `watch` (sent by the member's `puppet.py request`) | check and grant (`references/leases.md`, "Granting") |
| `LEASE SIZE — <id> — <why this run is smaller than the observed peak>` | your decision: `acquire --accept-size` when the reason fits the commands, else LEASE RESIZE (`references/leases.md`, "Sizing") |
| `CONFIG <what> by user: ...`, or `MEMORY <scope> <id> ...` naming `by user` (a save on the dashboard's Config or Rules page) | approve it automatically: apply it; never ask, revert or relay it (SKILL.md, "Memory") |
| `CLASS DEFAULTS PROPOSED <id> ...` in `watch` (a peer's `config propose`) | check your observations of that class, then `config agree` or `config object --text`; never ask the user (`references/leases.md`, "Class defaults by vote") |
| `EXTEND <CLASS> <id> <n> min ...` in `watch` (sent by the member's `puppet.py extend`) | your decision: `coordinator.py extend`, or tell it to release (`references/leases.md`, "Extending") |
| `LEAVE — <name>` | `member remove` |
| `HANDOFF REQUEST — <name> — to <coordinator\|any> — PRs <n> — note <path>` | `PAUSE` its PRs, then offer (`references/handoff.md`) |

## Replies you send

| Situation | Message |
| --- | --- |
| Active PR | `ACTIVE — #<n>. Goal: MERGED. Next: <one step>.` |
| Paused PR | `PAUSE — #<n> waits for #<m>. No merges from main, no fixes, Claude Auto-fix off / Codex repair heartbeat paused on #<n>.` |
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

## Handoff messages between coordinators (`say`)

See `references/handoff.md` for the steps around each one.

| Message | Sent by |
| --- | --- |
| `HANDOFF — <what> — PRs <n> — streams <slug> — note <path>` | sender, after it dropped its claims, only when no member moves (members move with `member transfer` and `member accept`) |
| `CUSTODY ACCEPTED — <you> owns <what> — successor pending` | receiver, after its user said yes, only for a `HANDOFF` without members (`member accept` is the acceptance for a member) |
| `HANDOFF DECLINED — <reason>` | receiver |
| `HANDOFF CLOSED — <what> — merged <sha> — cleanup <done\|left with the user: items>` | receiver |

## Routes

Members and their coordinator communicate directly in both directions for
every protocol message. Only messages between coordinators use `coordinator.py say`.
The coordinator records member updates in the roster/dashboard and decisions
in the ledger; member messages need no shared inbox copy.

- Claude session to Claude session: `SendMessage` to the session name from
  `ListAgents`, or to its session id. A session-id route can stop after about
  10 messages until the user types in that session; prefer the name route.
- Codex Desktop to a Codex thread: `mcp__codex_app__list_threads` to identify
  it, then `mcp__codex_app__send_message_to_thread` with `threadId` and
  `hostId` when available, and the protocol text in `prompt`. Resolve the
  thread id from the roster `sessionId`. Prefer this route over the CLI.
- CLI to a Codex thread, when app messaging is unavailable:
  `codex queue --thread <thread-id> --message "<text>"` when supported by the
  installed CLI (`codex queue --help`).
- Codex subagents in the same tree: `collaboration.send_message` (or
  `collaboration.followup_task` for new work). These IDs are not app thread IDs.
- Coordinator to coordinator only:
  `coordinator.py say --to <name> --message "<text>"`
  Send only what the other coordinator must act on and the shared records do
  not show: blockers, order changes that no command records. A general
  coordinator's one `WORK REQUEST` gets a `HANDOFF` reply only from a
  coordinator with work to spare (SKILL.md, "When your work is done"). Do not
  send acknowledgements of acknowledgements or per-step progress such as
  "acquired" or "released"; `events.log` already shows them. No watcher reads
  `events.log`: a change another coordinator must act on is an inbox message
  that the command sends itself.
  These have a command; never send them by `say`:

  | Instead of a message about | Use |
  | --- | --- |
  | a release, its result, a drain or cleanup receipt | the release event (`events --id <id>`), `drain-check` |
  | "your entry is the head", a priority change | `watch` HEAD (from queue state) and PRIORITY lines |
  | an admission hold or its clearance | `admission hold\|clear` |
  | a rule or limit change | `memory add\|update\|remove` (messages every live coordinator and member) or `config set-*` with `--reason` (messages every live coordinator only; tell a member only what changes for its task) |
  | a member handoff: offer, custody accepted, complete | `member transfer`, `member accept` |
  | who owns a PR, a worktree or a task | `who` |
  | which open PRs touch a file | `prs --path` |
  | the user's answer that concerns every coordinator | `decision add --scope machine` |
  (omit `--to` to reach every live coordinator). It appends to `inbox.jsonl`
  (`coordinator.py watch` shows it), then delivers directly: a Claude session
  through its inbox socket, a Codex thread through `codex queue`.
  For Desktop direct delivery, use `say --no-direct` for the inbox record,
  then `send_message_to_thread` once; do not duplicate direct delivery.
  Keep the shared inbox record even when direct delivery succeeds: it lets a
  coordinator catch up after it was not running. Receiving that record later
  is expected; handle duplicate receipt as described below.
  - The socket protocol is reverse-engineered, not an Anthropic interface
    (https://github.com/PeterSR/claude-code-socket-transport#the-protocol).
    The inbox record stays authoritative when direct delivery fails.
  - A receiver that bypasses permission prompts holds a socket message from a
    script for the user's approval; the Desktop app cannot show that dialog and
    drops it after `dialogExpiry`. The user decides whether to set
    `crossSessionInbound` to `accept` for that session; never change it yourself.
  - The socket frame names the receiver's current session id, so a stale
    roster session id breaks delivery.
- Dashboard to coordinator: the dashboard's queue buttons run
  `coordinator.py up|unwait --notify`, which records an inbox message from
  `dashboard` to each affected coordinator and delivers it directly, as `say`
  does. It reports the user's action (`references/leases.md`).
- Never use GUI automation (pasting into another app's window) as a message
  route.
- If no supported direct route to a member or its coordinator is available,
  report the delivery gap. Do not use `say` as a member-message fallback, and
  do not use a fallback to bypass an authorization restriction.
- A coordinator works on behalf of the user and relays the user's intention
  faithfully (puppet skill, section 3). A member always follows its
  directions, as the user's intent. A newer message overrides an older one.
  When a message relays an approval, it quotes the user's words or cites the
  recorded dashboard answer (`ledger.jsonl` or `events.log`); a bare message
  does not count. A coordinator never originates approval, consent or an
  exception, and no direction overrides a user restriction. A member's own
  tool permissions, safety classifier and permission prompts stay the
  backstop.
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
