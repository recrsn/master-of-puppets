# T3 Code

Read this when your host is T3 Code ([README.md](README.md) tells you how to
find your host). T3 Code runs Claude, Codex and other providers, for example
Antigravity ACP (Gemini models). All get the T3 tools, but the prefix and the
set differ: `mcp__t3-code__` in Claude, `mcp__t3_code__` in Codex,
`mcp_t3-code_` in Antigravity ACP. Match the bare name. T3 tools are often
deferred: load one by name before you call it.

| Purpose | Do this |
| --- | --- |
| Your session id | Claude: `$CLAUDE_CODE_SESSION_ID`. Codex: `$CODEX_THREAD_ID`, which T3 Code sets. Check it once with `echo $CODEX_THREAD_ID`; add a `CODEX_THREAD_ID=<thread id>` prefix only when it is empty. Another provider (Antigravity ACP): your T3 thread id, `$T3CODE_THREAD_ID`; the helpers use it when neither of the others is set. |
| Your T3 thread id | `$T3CODE_THREAD_ID`, for every provider (Codex too). A thread that T3 Code launched has an id like `mcp:launch:<hash>` or `thread:mcp:<id>:<label>:<n>`; use it as it is. |
| Find other sessions | `t3_thread_list`, `t3_thread_search`; `t3_thread_read` for a thread's latest items |
| Send a message | `t3_thread_send` by thread id ("Routes", below). For a coordinator on another machine, use the [remote route](#remote-coordinators). |
| Reach a Claude session in another host | Claude only: `SendMessage` and `ListAgents`, as in [claude-desktop.md](claude-desktop.md) |
| Reach a Codex Desktop or Codex CLI thread | No app route: [README.md](README.md), "No shared route" |
| Scheduled turn (heartbeat, scout tick) | `schedule_task`, bound to your thread; Claude may also use `CronCreate` or `ScheduleWakeup`. In Antigravity ACP, use `schedule_task` when present or its own `schedule` tool (`CronExpression` or `DurationSeconds`). A scheduled turn may not send by `t3_thread_send` ("Failures", below). Keep one schedule: note its `scheduledTaskId` and update that task in place. An overdue one-shot task (`nextRunAt` null) is still pending; never make a second one beside it. |
| Watch a command | Claude: `Monitor`. Codex: as in [codex-desktop.md](codex-desktop.md), "Watchers". Antigravity ACP: `run_command` with `WaitMsBeforeAsync` (or `IsDaemon`), then `manage_task` to read it. `t3_background_wait` is not in every provider's set. |
| Start a subagent | Claude `Agent`, Codex `collaboration.spawn_agent`, Antigravity ACP `invoke_subagent`, or `delegate_task` |
| Start an independent session (coordinators only) | Ask the user first. On yes, `t3_thread_launch` with the enrollment line first in the prompt. Start each member at or below your own runtime mode ("Starting sessions", below). |
| Ask the user | Claude `AskUserQuestion`; Codex `request_user_input_async`; Antigravity ACP `ask_question`; plain chat as the last choice |
| Bind a PR | `link_pull_request` with the full URL; `watch_pull_request` when asked to watch it |
| Open the dashboard | Give the user `http://localhost:4720/` |

When reading a PR diff with `pull_request_read`, the patch text is in
`diff.patch`. For a full diff, pass each `diff.nextCursor` as `cursor` on
the next request and read the patch from each page.

PR watch notifications and “Background activity updated” messages can arrive
as user turns. Inspect the result and take any required action. A command
starting or finishing, or a check on an unchanged PR, needs no progress
message or local recap. Report material changes under your role's reporting rules.

## Provider switch in a thread

The user can switch a T3 Code thread to another provider in place (for
example Claude to Antigravity ACP). The session id changes; the thread id
does not. The helpers automatically move the roster entry whose `t3Thread` is
your thread to your new session id and provider at your next command, and print
`identity: <name> now runs as ...`. You keep your coordinator or member name:
run no handoff and send no new JOIN. This works for every provider, Codex
too. Only an entry with no `t3Thread` (a member that joined before an install
recorded it) needs a new JOIN after a switch.

## Sandboxed providers

Some providers' terminal sandboxes (Antigravity ACP, the Codex sandbox) block
`~/.local/state/machine-leases/`, `localhost:4720` and worktrees outside the
project unless a command runs outside the sandbox. Member CLI help runs
locally. Run helper commands that need the lease server
outside the sandbox on the first try (Antigravity ACP: `BypassSandbox: true`;
Codex: per-command escalation); never try it in the sandbox first. Keep each
command in one plain shape so a prefix approval covers the next run:
`python3 -I ~/.local/state/machine-leases/coordinator.py <command> ...` (or
`puppet.py`). Use no `cd ... &&`, `timeout`, pipes or `$VARIABLES` around it.

## Reading a coordinator backlog

Use `t3_queue` with `action: "list"` on your own thread. Page through the
queue and read truncated items before acting on them. Apply the [catch-up
procedure](../protocol.md#duplicate-receipt-and-catch-up). Listing a message
leaves it queued for delivery; track the action in the normal coordinator
records. Keep the original messages available for recovery.

## Routes

- Each T3 Code thread has a stable id. The thread's display name, and the
  name `ListAgents` shows, change when the thread is renamed or its session
  restarts. A send to an old name fails with "No agent named ...". Route by
  the thread id, never by a display name.
- A coordinator's `heartbeat` and `register` record its T3 thread id
  (`t3Thread`) and host in the roster. An enrolled member can record its
  route by running `puppet.py whoami` from its registered session on any
  provider. `puppet.py route` prints the coordinator's route.
- A member that has run no `puppet.py` command since that install has no
  `t3Thread` yet: find its thread with `t3_thread_search` by the member's
  name.
- Send with `t3_thread_send`: `threadId` from the route, the protocol text as
  the message and the delivery mode for that direction. A puppet sending to
  its coordinator uses `mode: "steer"` so an active coordinator can act on
  the message during its current turn. For coordinator assignments to members,
  use `mode: "queue"` except for the stale-thread case below. Scouts use
  `mode: "queue"` for their reports. Add `environmentId` when your thread
  list gives one for that thread.

## Remote coordinators

Use this route between coordinators. Each coordinator manages its own
members. Follow the [remote coordinator protocol](../remote-coordinators.md)
for the message and acknowledgment.

1. Run `t3_environment_links` on the sending machine. Select the intended
   peer by its `environmentId` and check its status and access. To send to
   a pre-existing coordinator thread, the user must pair the outbound link
   with **full access**. A lower-access link can change only threads started
   through that link. The target thread's runtime mode must also be within
   the sender's permissions.
2. Use `t3_thread_read` with the peer's `environmentId` and the remote
   coordinator's `threadId` to verify the thread. Pass the same two values
   to `t3_thread_send`, with the protocol text in `message` and
   `mode: "queue"`. Queue acceptance confirms submission. For a handoff,
   wait for the receiver's `CUSTODY ACCEPTED` before transferring ownership.
3. A link from A to B lets A send to B and read B's thread. With only that
   link, B can reply in its own thread and A can read the reply there.
   For B to send directly to A's pre-existing thread, B also needs an
   outbound full-access link to A. Verify that direction from B using
   A's environment and coordinator thread IDs.

## Failures

| Error | Meaning | Do this |
| --- | --- | --- |
| `parent_not_active` | Your own turn is not an active run, for example a scheduled turn | Send by the next route (`puppet.py route`), or with `puppet.py tell` |
| `runtime_mode_escalation_denied` | The receiver runs in a higher runtime mode than the sender, as T3 Code sees it now | Do not work around it, and do not tell the user the mode as a fact. Check the receiver's `runtimeMode` in `t3_thread_list`, tell the user what you see, and retry once by thread id when the user says to |
| "No agent named ..." | The display name changed | Look up the route again; send by thread id |
| A socket `ENOENT` or "stale" | The session restarted | Look up the route again |
| "automatic permission approval review did not finish before its deadline" | The approval reviewer timed out; nothing was sent | Retry once with the same `clientRequestId`. When it times out again, send with `puppet.py tell` |

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
A thread whose runtime mode does not allow escalation (for example `auto`)
refuses every helper call: only the user can change the thread's mode. Ask
the user once; until they do, use the UPDATE path above.
