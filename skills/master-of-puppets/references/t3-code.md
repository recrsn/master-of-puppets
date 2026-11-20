# T3 Code

Read this only when your sessions run in T3 Code (`CLAUDE_CODE_ENTRYPOINT=t3-code`,
or a `T3CODE_THREAD_ID` variable in the shell). Other setups skip it.

## Routes

- Each T3 Code thread has a stable id, `T3CODE_THREAD_ID`. The thread's display
  name, and the name `ListAgents` shows, change when the thread is renamed or
  its session restarts. A send to an old name fails with "No agent named ...".
  Route by the thread id, never by a display name.
- The coordinator's `heartbeat` and `register` record its thread id in the
  roster (`t3Thread`) when the coordinator runs in T3 Code. A member runs
  `puppet.py route` to print it. Until that command exists on your machine
  (an install puts it there), take the id from your coordinator's WELCOME
  or ask the user.
- Send with `t3_thread_send`: `threadId` from the route, the protocol text as
  the message, and `mode: "queue"`, which runs it as a new turn after the
  coordinator's current one. Add `environmentId` when your thread list gives one
  for that thread.

## Failures

| Error | Meaning | Do this |
| --- | --- | --- |
| `parent_not_active` | Your own turn is not an active run, for example a scheduled turn | Send by the next route (protocol.md, "Routes"), or with `puppet.py tell` when it exists |
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

## Starting sessions

- Start each member at or below the coordinator's own runtime mode. A
  coordinator cannot send to a thread in a higher mode, so a member started
  above it is unreachable.
- A delegated child (a subagent or a delegated task) is for ephemeral or
  parallel work. A workstream that runs for days is its own top-level thread.

## Codex members in T3 Code

A Codex member reaches a Claude coordinator with `t3_thread_send` to the
coordinator's thread id, or with `puppet.py tell` when it exists.

When the Codex sandbox refuses `puppet.py` and escalation is refused too, the
member cannot record its own state. A scout then puts its tick result in its
UPDATE (once per tick that changed something), and the coordinator records
each report with `member update`. That keeps the scout live in `member stale`.
