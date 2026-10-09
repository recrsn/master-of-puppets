# Protocol

Keep messages short. The receiver may see only the first line until it
expands the message, so put the point first.

Use [agents.md](agents.md) for the sender's available tool routes. Customize
WELCOME for the member's tool: Claude Auto-fix or Codex owner-led repair.

## Welcome (send to each member after its JOIN)

```
WELCOME — <slug> coordinates <focus>. You are a member for <task> (PRs <list>).

1. I give directions: ACTIVE (work this PR to MERGED) or PAUSE (no merges from main,
   no fixes, Claude Auto-fix off / Codex repair heartbeat paused until I say ACTIVE).
2. When the applicable checks pass: open the PR and mark it ready. Claude: ccd_pr;
   Auto-fix on only while ACTIVE. Codex: attach_artifact with the PR URL; handle
   valid hosted review/CI blockers only while ACTIVE. PAUSE takes precedence.
   I enable auto-merge and retarget bases. You do every commit, push, sync with the
   base branch, conflict fix and review reply.
3. Report each MERGED PR with its merge SHA.
4. USER SYNC: when the user talks to you directly, forward "USER SYNC — <one line>".
5. Report raw failures. Do not weaken tests or rerun flakes to green.
6. Shared PR rules: <state dir>/pr-rules.md (if present). Project rules from my memory:
   <output of lease.py memory list --project-root <worktree>, rules only>.
7. Leases are <on|off>. <If on, the lease addendum follows.>
8. You send messages and release your own leases; I record member state and decisions.
   Directions stay within the user's authorized scope and do not override restrictions.
   Send UPDATE — <name> — <phase> — <fact>
   on each change. Before you start an independent session (chip, Codex thread), send
   ENROLL REQUEST — <task> — PR <n>; I reply with a kickoff line for its prompt.
   Subagents remain part of your enrollment and need no separate kickoff.
9. Done means every PR of your task is MERGED, or the user dropped the task.
   Passing checks is not done: commit, push and open the PR. If you need the
   user's permission to commit, ask the user at once and send
   UPDATE — <name> — Waiting to commit — <fact>.
   When done: stop services, release leases, send LEAVE — <name>.
```

## Lease addendum (only when leases are on)

```
LEASES ON — <slug> grants the lease classes for you: <CLASS — description, one per line>.
1. Before an action a class covers (BUILD: builds, typecheck, lint/format, tests, codegen;
   E2E: starting local servers/stacks; others as listed above; plus the project rules
   in WELCOME):
   LEASE REQUEST <CLASS> — id <slug>-q-<name>-<n> — <exact commands> — <estimate min> — <est GiB if known> — <worktree>
2. Start waiting at once: python3 -I <state dir>/lease.py await-grant <CLASS> --id <id>
   Run only on a GRANTED line (exit 0). NOT-GRANTED (exit 3 left the queue, 6 never
   queued): do not run, ask me. Exit 5 (timeout, still queued): wait again. No polling loops.
   Run only the granted commands and cleanup of resources they started.
3. Use it or return it: no edits or repairs while holding a lease. On failure, clean
   up owned resources, release promptly, report the raw failure, repair, and request
   again (back of the queue).
4. For E2E, stop your servers before release, including on failure.
   Release: python3 -I <state dir>/lease.py release <CLASS> --id <id>
   then reply LEASE RELEASED <id> — pass|fail — <raw summary>.
   Report cleanup failures; the next E2E grant stays blocked until drained.
5. No lease: dependency install, source edits, reading code, browser-only work against
   remote sites, unless a class or a project rule covers it.
6. Limits: <per-class max minutes from config show>. Split longer runs.
```

## Messages members send

| Message | Coordinator action |
| --- | --- |
| `JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs ... — phase` | `member add`, then WELCOME |
| `UPDATE — <name> — <phase> — <fact>` | `member update` |
| `ENROLL REQUEST — <task> — PR <n>` | `enroll --by <name>`, reply with the kickoff line |
| `USER SYNC — <one line>` | `note`, `member update --latest` |
| `LEASE REQUEST ...` | see `references/leases.md` |
| `LEAVE — <name>` | `member remove` |

## Replies you send

| Situation | Message |
| --- | --- |
| Active PR | `ACTIVE — #<n>. Goal: MERGED. Next: <one step>.` |
| Paused PR | `PAUSE — #<n> waits for #<m>. No merges from main, no fixes, Claude Auto-fix off / Codex repair heartbeat paused on #<n>.` |
| Bottom merged | `ACTIVE — #<n>: #<m> merged (<sha>). I retargeted #<n> to main. Merge origin/main into your branch, resolve, push.` |
| Heartbeat round | `STATUS? — phase, PR state, blockers, anything the user decided.` |
| Not a member | `Run /puppet to join a coordinator first.` |
| Lease queued | `LEASE QUEUED — <id> (<min> min, ~<GiB> GiB), <CLASS> position <n>. Ahead: <who>. ETA ~<time>.` |
| Head, host busy | `LEASE QUEUED — <id> is at the head, but the host is swapping (<numbers>). I grant when two samples are calm.` |
| Head, no memory | `LEASE QUEUED — <id> is at the head; it needs <n> GiB and <m> GiB is free. I grant after the next release.` |
| Grant | `LEASE GRANTED — <CLASS> <id> for <task>, until <time>. Covers: <commands>. Release: <command>.` |
| Over the limit | `LEASE QUEUED — <min> min is over the <max>-min limit, so I split it: part 1 keeps position <n>, part 2 joins the back.` |
| Expiry | `LEASE EXPIRED — <id> passed <time>. Release now, or reply with progress and I extend it if the queue allows.` |

## Routes

Members and their coordinator communicate directly in both directions for
every protocol message. Only messages between coordinators use `lease.py say`.
The coordinator records member updates in the roster/dashboard and decisions
in the ledger; member messages need no shared inbox copy.

- Claude session to Claude session: `SendMessage` to the session name from
  `ListAgents`, or to its session id. A session-id route can stop after about
  10 messages until the user types in that session; prefer the name route.
- Codex Desktop to a Codex thread: `mcp__codex_app__list_threads` to identify
  it, then `mcp__codex_app__send_message_to_thread` with `threadId` and
  `hostId` when available, and the protocol text in `prompt`. Prefer this native
  inter-thread route for every puppet-to-master message and authorized master
  replies. Follow the tool's user-authorization requirements;
  another chat's request to reply is not that authorization.
- CLI to a Codex thread: `codex queue --thread <thread-id> --message "<text>"`
  when supported by the installed CLI (`codex queue --help`).
- Codex subagents in the same tree: `collaboration.send_message` (or
  `collaboration.followup_task` for new work). These IDs are not app thread IDs.
- Coordinator to coordinator only:
  `lease.py say --from <name> --to <name> --message "<text>"`
  (omit `--to` to reach every live coordinator). It appends to `inbox.jsonl`
  (`lease.py watch inbox` shows it), then delivers directly: a Claude session
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
  - The socket frame names the receiver's current session id. `/clear` mints a
    new one, so a coordinator that clears must refresh its roster session ID.
- Dashboard to coordinator: the dashboard's queue buttons run
  `lease.py up|unwait --notify`, which records an inbox message from
  `dashboard` to each affected coordinator and delivers it directly, as `say`
  does. It reports the user's action (`references/leases.md`).
- If no supported direct route to a member or its coordinator is available,
  report the delivery gap. Do not use `say` as a member-message fallback.
- Deep links for the dashboard: Claude `claude://claude.ai/epitaxy/<sessionId>`,
  Codex `codex://threads/<threadId>`.
