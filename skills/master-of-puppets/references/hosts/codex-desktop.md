# Codex Desktop

Read this when your host is Codex Desktop (`CODEX_INTERNAL_ORIGINATOR_OVERRIDE=Codex Desktop`
or `__CFBundleIdentifier=com.openai.codex`; [README.md](README.md) tells you
how to find your host). The app tools have the `mcp__codex_app__` prefix;
discover them when they are not loaded. Use only the tools that your session
has.

| Purpose | Do this |
| --- | --- |
| Your session id | `$CODEX_THREAD_ID` when exported. Else the current thread id that the app gives you: run each command as `CODEX_THREAD_ID=<thread id> coordinator.py ...` (or `puppet.py`). Never invent an id or use a subagent id. |
| Find other sessions | `list_threads` |
| Send a message | `send_message_to_thread` with `threadId` (the roster `sessionId`), `hostId` when `list_threads` gives one, and the protocol text in `prompt`. It reaches Codex Desktop threads only. |
| Reach a Claude session or a T3 Code thread | No app route: [README.md](README.md), "No shared route" |
| Read or wait for a session | `read_thread` for context; `wait_threads` for progress (carry its cursor as `afterCursor`) |
| Message a subagent | `collaboration.send_message`; `collaboration.followup_task` for new work. These ids are not app thread ids. |
| Start a subagent | `collaboration.spawn_agent` when delegation is authorized. Children stay part of the parent's enrollment. |
| Start an independent session (coordinators only) | Ask the user first with the ask-user tool (task, worktree or branch, PRs). On yes, `create_thread`, with the enrollment line first in the prompt. |
| Ask the user | `request_user_input_async`; `request_user_input` only when the mode allows it; plain chat as the last choice |
| Scheduled turn (heartbeat, scout tick) | `automation_update` with `kind: "heartbeat"`, attached to your thread ("Heartbeat", below) |
| Watch a command | `exec_command`, then read it with `write_stdin` ("Watchers", below) |
| Bind a PR and repair blockers | `attach_artifact` with the PR URL, then repair valid review and CI blockers in the owner thread. Attaching a PR does not start Auto-fix. |
| Open the dashboard | `open_in_codex` with the browser target `http://localhost:4720/` |

## Heartbeat

Create or update a thread heartbeat with `automation_update`: every 15
minutes (`FREQ=MINUTELY;INTERVAL=15`), ACTIVE, named for your slug. The prompt
says to follow the skill's round (or tick), check every member, and notify
only on real changes, completion, failure or a needed user action. Do not
request a new chat for each run. After a context reset, find the matching
automation and reuse it. Pause it when you stop. When scheduling is not
available, tell the user: a shell watcher gives no agent turns.

## Watchers

Run `coordinator.py watch` as a long-lived `exec_command`. Save its output
outside the repository and record how much you read, so each turn reads only
new events. Command output alone does not wake you. On resume, check that the
watcher and the server run before you start new ones, and recover unread
messages from the inbox and ledger: an inbox watcher starts at the end of the
file. Apply protocol.md, "Duplicate receipt and catch-up", to a message that
comes by two routes.

## Sandbox and permissions

Run `puppet.py`, `coordinator.py` and other commands that need the network
or the lease server with per-command escalation. Ask the user only when the
escalation is refused. When `puppet.py` stays refused, a scout puts its tick
result in its UPDATE and the coordinator records it with `member update`.
There is no Full access requirement for new threads, heartbeats or cloud
tasks. Execution permissions do not widen task authorization.
