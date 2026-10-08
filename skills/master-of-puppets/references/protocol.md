# Protocol

Keep messages short. The receiver may see only the first line until it
expands the message, so put the point first.

## Welcome (send to each member after its JOIN)

```
WELCOME — <slug> coordinates <focus>. You are a member for <task> (PRs <list>).

1. I give directions: ACTIVE (work this PR to MERGED) or PAUSE (no merges from main,
   no fixes, Auto-fix off on that PR until I say ACTIVE).
2. When your local E2E passes: open the PR, mark it ready, bind it and turn on Auto-fix.
   I enable auto-merge and retarget bases. You do every commit, push, merge of main
   into your branch (never rebase), conflict fix and review reply.
3. Report each MERGED PR with its merge SHA.
4. USER SYNC: when the user talks to you directly, forward "USER SYNC — <one line>".
5. Report raw failures. Do not weaken tests or rerun flakes to green.
6. Shared PR rules: <state dir>/pr-rules.md (if present). Project rules from my memory:
   <output of lease.py memory list --project-root <worktree>, rules only>.
7. Leases are <on|off>. <If on, the lease addendum follows.>
8. You only send messages; I record everything. Send UPDATE — <name> — <phase> — <fact>
   on each change. Before you start any task (new session, chip, Codex thread), send
   ENROLL REQUEST — <task> — PR <n>; I reply with a kickoff line for the first line of its prompt.
9. When done: stop services, release leases, send LEAVE — <name>.
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
   Run only the granted commands.
3. Use it or return it: no edits or repairs while holding a lease. On failure, release
   at once, reply with the raw failure, repair, and request again (back of the queue).
4. Release: python3 -I <state dir>/lease.py release <CLASS> --id <id>
   then reply LEASE RELEASED <id> — pass|fail — <raw summary>.
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
| Paused PR | `PAUSE — #<n> waits for #<m>. No merges from main, no fixes, Auto-fix off on #<n>.` |
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

- Claude session to Claude session: `SendMessage` to the session name from
  `ListAgents`, or to its session id. A session-id route can stop after about
  10 messages until the user types in that session; prefer the name route.
- To a Codex thread: `codex queue --thread <thread-id> --message "<text>"`.
- Any session or script to a coordinator or member, or coordinator to
  coordinator: `lease.py say --from <name> --to <name> --message "<text>"`
  (omit `--to` to reach every live coordinator). It appends to `inbox.jsonl`
  (`lease.py watch inbox` shows it), then delivers directly: a Claude session
  through its inbox socket, a Codex thread through `codex queue`.
  - The socket protocol is reverse-engineered, not an Anthropic interface
    (https://github.com/PeterSR/claude-code-socket-transport#the-protocol).
    The inbox record stays authoritative when direct delivery fails.
  - A receiver that bypasses permission prompts holds a socket message from a
    script for the user's approval; the Desktop app cannot show that dialog and
    drops it after `dialogExpiry`. The user decides whether to set
    `crossSessionInbound` to `accept` for that session; never change it yourself.
  - The socket frame names the receiver's current session id. `/clear` mints a
    new one, so a member that clears must send JOIN again.
- Deep links for the dashboard: Claude `claude://claude.ai/epitaxy/<sessionId>`,
  Codex `codex://threads/<threadId>`.
