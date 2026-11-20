# T3 Code

Read this when your host is T3 Code ([README.md](README.md) tells you how to
find your host). T3 Code runs Claude and Codex threads, and both get the same
T3 tools. The prefix differs: `mcp__t3-code__` in Claude, `mcp__t3_code__` in
Codex. T3 tools are often deferred: load one by name before you call it.

| Purpose | Do this |
| --- | --- |
| Your session id | Claude: `$CLAUDE_CODE_SESSION_ID`. Codex: `$CODEX_THREAD_ID`, else run each command as `CODEX_THREAD_ID=<thread id> coordinator.py ...`. |
| Your T3 thread id | Claude: `$T3CODE_THREAD_ID`. Codex has no such variable: find your thread in `t3_thread_list` or `t3_thread_search`. |
| Find other sessions | `t3_thread_list`, `t3_thread_search`; `t3_thread_read` for a thread's latest items |
| Send a message | `t3_thread_send` by thread id ("Routes", below). It reaches every T3 Code thread, Claude or Codex. |
| Reach a Claude session in another host | Claude only: `SendMessage` and `ListAgents`, as in [claude-desktop.md](claude-desktop.md) |
| Reach a Codex Desktop or Codex CLI thread | No app route: [README.md](README.md), "No shared route" |
| Scheduled turn (heartbeat, scout tick) | `schedule_task`, bound to your thread. Claude may also use `CronCreate` or `ScheduleWakeup`. A scheduled turn may not send by `t3_thread_send` ("Failures", below). |
| Watch a command | Claude: `Monitor`. Codex: as in [codex-desktop.md](codex-desktop.md), "Watchers". Wait for your own background command with `t3_background_wait`. |
| Start a subagent | Claude `Agent`, Codex `collaboration.spawn_agent`, or `delegate_task` |
| Start an independent session (coordinators only) | Ask the user first. On yes, `t3_thread_launch` with the enrollment line first in the prompt. Start each member at or below your own runtime mode ("Starting sessions", below). |
| Ask the user | Claude `AskUserQuestion`; Codex `request_user_input_async`; plain chat as the last choice |
| Bind a PR | `link_pull_request` with the full URL; `watch_pull_request` when asked to watch it |
| Open the dashboard | Give the user `http://localhost:4720/` |

## Routes

- Each T3 Code thread has a stable id. The thread's display name, and the
  name `ListAgents` shows, change when the thread is renamed or its session
  restarts. A send to an old name fails with "No agent named ...". Route by
  the thread id, never by a display name.
- A coordinator's `heartbeat` and `register` record its host and, for
  Claude, its thread id (`t3Thread`) in the roster. Every `puppet.py`
  command does the same for a member. `puppet.py route` prints the route.
  Until that command exists on your machine (an install puts it there), take
  the id from your coordinator's WELCOME, from `t3_thread_search`, or ask the
  user.
- A Codex member's thread id is not recorded (Codex has no
  `T3CODE_THREAD_ID`). The coordinator finds it with `t3_thread_search` by
  the member's name and records it in its notes.
- Send with `t3_thread_send`: `threadId` from the route, the protocol text as
  the message, and `mode: "queue"`, which runs it as a new turn after the
  receiver's current one. Add `environmentId` when your thread list gives
  one for that thread.

## Failures

| Error | Meaning | Do this |
| --- | --- | --- |
| `parent_not_active` | Your own turn is not an active run, for example a scheduled turn | Send by the next route (`puppet.py route`), or with `puppet.py tell` when it exists |
| `runtime_mode_escalation_denied` | The receiver runs in a higher runtime mode than the sender, as T3 Code sees it now | Do not work around it, and do not tell the user the mode as a fact. Check the receiver's `runtimeMode` in `t3_thread_list`, tell the user what you see, and retry once by thread id when the user says to |
| "No agent named ..." | The display name changed | Look up the route again; send by thread id |
| A socket `ENOENT` or "stale" | The session restarted | Look up the route again |

After one failed send, look up the route again and send once by the next
route. After a second failure, tell the user and keep the message for the
next try. Never send the same message by two routes that both work: the
receiver gets it twice.

## A member that is stale but has a running thread

A thread can show an active run that has made no output for hours. A send
with `mode: "auto"` then steers into that hung run, and nothing happens.

1. Read the thread with `t3_thread_read`: the latest item and its time.
2. When the active run made no output for more than one tick (a scout) or
   30 minutes (a puppet), send the STATUS or the work with
   `mode: "restart"`. It stops the hung run and starts a new turn.
3. Otherwise send with `mode: "queue"` and wait.

When every Codex thread stops at the same time, the cause is the Codex
provider, not the members. Tell the user once, and restart the members
together when it recovers.

## Starting sessions

- Start each member at or below the coordinator's own runtime mode. A
  coordinator cannot send to a thread in a higher mode, so a member started
  above it is unreachable.
- A delegated child (a subagent or a delegated task) is for ephemeral or
  parallel work. A workstream that runs for days is its own top-level thread.
- Codex threads whose source is `guardian_review` are approval reviewers,
  not members or scouts.

## Codex sandbox

When the Codex sandbox refuses `puppet.py` and escalation is refused too, the
member cannot record its own state. A scout then puts its tick result in its
UPDATE (once per tick that changed something), and the coordinator records
each report with `member update`. That keeps the scout live in `member stale`.
