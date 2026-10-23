# Protocol

Keep messages short. The receiver may see only the first line until it
expands the message, so put the point first.

Members follow the `puppet` skill, so WELCOME carries only what the skill
cannot know: this stack, the project rules and the lease setup.

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
<CLASS — description — max minutes from config show, one per line>
Split runs longer than the limit.
```

## Messages members send

| Message | Coordinator action |
| --- | --- |
| `JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs ... — phase — commands — parent <parent\|none>` | `member add [--parent <parent>]`, then WELCOME. A task marked `scheduled:` or `sweep:` is background work (`references/leases.md`, "Priority") |
| `UPDATE — <name> — <phase> — <fact>` | `member update` |
| `CHILD TASK STARTED — <name> — <child task> — <tool> <child session id> — PRs <n ...\|none>` (after the runtime confirms the start) | `child --parent <name>` (puppet skill, section 6) |
| `CLOUD UPDATE — <member> — <taskId> — <state> — <fact>` (from the watch helper) | `member update --name <member>`, then act (`references/coderabbit-cloud.md`, "Track") |
| `CLOUD TASK — <name> — <taskId> — <url> — <task> — PRs <n>` | `member add --tool coderabbit`, `cloud-<slug>.txt`, `watch cloud` (`references/coderabbit-cloud.md`, "Record") |
| `USER SYNC — <one line>` | `note`, `member update --latest` |
| No message: `EVENT ... request <CLASS> <slug> <id> ...` in `watch inbox` (the member ran `puppet.py request`) | check and grant (`references/leases.md`, "Granting") |
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
| Lease queued | `LEASE QUEUED — <id> (<min> min, ~<GiB> GiB), <CLASS> position <n>. Ahead: <who>. ETA ~<time>.` |
| Head, host busy | `LEASE QUEUED — <id> is at the head, but the host is busy (<numbers>). I grant when two samples are calm.` |
| Head, no memory | `LEASE QUEUED — <id> is at the head; it needs <n> GiB and <m> GiB is free. I grant after the next release.` |
| Grant | `LEASE GRANTED — <CLASS> <id> for <task>, until <time>. Covers: <commands>. Release: <command>.` |
| Priority move | `LEASE QUEUED — <id> is now <CLASS> position <n>: <task> has priority <p>.` |
| Over the limit | `LEASE QUEUED — <min> min is over the <max>-min limit, so I split it: part 1 keeps position <n>, part 2 joins the back.` |
| Expiry | `LEASE EXPIRED — <id> passed <time>. Release now, or reply with progress and I extend it if the queue and the class limit allow.` |
| Cloud handoff, user said yes | `CLOUD HANDOFF — <name> — the user chose it on the dashboard` (`references/coderabbit-cloud.md`) |
| Handoff done, member replaced | `HANDOFF COMPLETE — <name>` (it sends LEAVE) |
| Handoff done, member moves | `HANDOFF COMPLETE — <name> — JOIN <receiver>` |

## Handoff messages between coordinators (`say`)

See `references/handoff.md` for the steps around each one.

| Message | Sent by |
| --- | --- |
| `HANDOFF — <what> — PRs <n> — streams <slug> — members <names> — note <path>` | sender, after it dropped its claims |
| `CUSTODY ACCEPTED — <you> owns <what> — successor pending` | receiver, after its user said yes |
| `HANDOFF DECLINED — <reason>` | receiver |
| `SUCCESSOR JOINED — <name> — <tool> <session id>` | receiver |
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
  `coordinator.py say --from <name> --to <name> --message "<text>"`
  Send only what the other coordinator must act on: handoffs, blockers, order
  changes, rule changes. A general coordinator's one `WORK REQUEST` gets a
  `HANDOFF` reply only from a coordinator with work to spare (SKILL.md, "When
  your work is done"). Do not send acknowledgements of acknowledgements or
  per-step progress such as "acquired" or "released"; `events.log` already
  shows them.
  (omit `--to` to reach every live coordinator). It appends to `inbox.jsonl`
  (`coordinator.py watch inbox` shows it), then delivers directly: a Claude session
  through its inbox socket, a Codex thread through `codex queue`.
  For Desktop direct delivery, use `say --no-direct` for the inbox record,
  then `send_message_to_thread` once; do not duplicate direct delivery.
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
- Follow each messaging tool's authorization rules. A message from another
  chat does not itself authorize a reply; get the user's authorization when
  the tool requires it. Enrollment does not override that requirement.
- After Claude `/clear`, or a move to a new Codex thread, the session id
  changes: a member sends JOIN again, a coordinator refreshes its roster
  session id. Codex context compaction alone is not a new thread.
- Deep links for the dashboard: Claude `claude://claude.ai/epitaxy/<sessionId>`,
  Codex `codex://threads/<threadId>`.
