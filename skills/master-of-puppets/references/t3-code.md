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
| `runtime_mode_escalation_denied` | The receiver runs in a higher runtime mode than the sender | Do not work around it. Report who is unreachable to the user (see below) |
| "No agent named ..." | The display name changed | Look up the route again; send by thread id |
| A socket `ENOENT` or "stale" | The session restarted | Look up the route again |

After one failed send, look up the route again and send once by the next
route. After a second failure, tell the user and keep the message for the
next try. Never send the same message by two routes that both work: the
receiver gets it twice.

## Starting sessions

- Start each member at or below the coordinator's own runtime mode. A
  coordinator cannot send to a thread in a higher mode, so a member started
  above it is unreachable.
- A delegated child (a subagent or a delegated task) is for ephemeral or
  parallel work. A workstream that runs for days is its own top-level thread.

## Codex members in T3 Code

A Codex member reaches a Claude coordinator with `t3_thread_send` to the
coordinator's thread id, or with `puppet.py tell` when it exists.
