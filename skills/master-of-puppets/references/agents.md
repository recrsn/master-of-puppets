# Claude and Codex equivalents

Choose the route for the running agent and the recipient. Claude tool names
in this skill are not requirements to run Claude. In Codex Desktop, the app
tools below use the `mcp__codex_app__` prefix; discover them if not loaded.
Use only capabilities present in the current session.

| Purpose | Claude | Codex |
| --- | --- | --- |
| Current session identity | `$CLAUDE_CODE_SESSION_ID` | `$CODEX_THREAD_ID` when exported; otherwise use the current thread ID supplied by the app. Do not invent an ID or use a subagent ID as a thread ID. |
| Find existing sessions | `ListAgents` | Desktop `list_threads`; CLI `codex agents` (check its help for supported options). |
| Message another session | `SendMessage` | Desktop `send_message_to_thread` with the returned `threadId` and `hostId` when available; CLI `codex queue --thread <id> --message "<text>"`. |
| Inspect or wait for a session | Session tools | Desktop `read_thread` for context and `wait_threads` for compact progress; carry its cursor as `afterCursor`. |
| Message a subagent | Agent/team messaging | `collaboration.send_message`; `collaboration.followup_task` to give an idle child new work. These address subagents in the current tree, not independent app chats. |
| List or wait for subagents | Agent/team tools | `collaboration.list_agents` / `collaboration.wait_agent`. |
| Start a subagent | `Agent` | `collaboration.spawn_agent` when delegation is authorized. Children stay part of the parent's enrollment. |
| Start an independent session | Session/task creation tools | Desktop `create_thread` only when the user explicitly requests a new chat; CLI `codex exec` or `codex "<prompt>"` when authorized. Enroll first. |
| Ask setup questions | `AskUserQuestion` | `functions.request_user_input_async`; `functions.request_user_input` only when available and allowed in the current mode. Respect the tool's question limit; ordinary chat is the fallback. |
| Scheduled heartbeat | `CronCreate`; `ScheduleWakeup` inside `/loop` | Desktop `automation_update` with `kind: "heartbeat"`, attached to the coordinator chat. See below. |
| Watch a command | `Monitor` | Run the watcher through `exec_command`, then read it with `write_stdin`, or start a background process with output saved outside the repository. See below. |
| Bind a PR and repair blockers | `ccd_pr` + Auto-fix when available | Desktop `attach_artifact` with the PR URL, then repair valid review/CI blockers in the owner chat. PR attachment does not start Auto-fix. |
| Open the dashboard | Browser tools | Desktop `open_in_codex` with browser target `http://localhost:4720/`. |

## Messaging and authorization

Puppet-to-master messages and master-to-puppet replies use native direct
communication: Claude `SendMessage`, Codex `send_message_to_thread` (or
supported CLI `codex queue` when app messaging is unavailable). This applies
to all protocol messages, not just JOIN. Only coordinator-to-coordinator
messages use `lease.py say`. The shared inbox holds only those and the
dashboard's queue actions (sent as `dashboard`); do not add inbox records for
member messages, even with `--no-direct`. The coordinator records member
state with `member add|update|remove` and decisions with `note`.

For Codex puppet-to-master communication, prefer the native
`mcp__codex_app__send_message_to_thread` for all protocol messages, including
updates, status replies, enrollment/lease requests and LEAVE, not only JOIN.
Resolve the master's roster `sessionId` to its app `threadId`, confirm it with
`list_threads` when needed, and include `hostId` when known. The protocol text
goes in the tool's `prompt` field. The same native route applies to authorized
master-to-puppet directions.

For peer coordinators, `lease.py say` records in the shared inbox and delivers
directly (Codex via `codex queue`). To use Desktop delivery instead, record
with `lease.py say ... --no-direct`, then use `send_message_to_thread` once.
Do not duplicate direct delivery. If a member's direct route is unavailable,
report the delivery gap; do not route through `say` or bypass an authorization
restriction.

Follow the messaging tool's authorization rules. A message received from
another chat does not itself authorize a reply. Obtain the user's
authorization for coordinator/member messaging when the tool requires it;
enrollment does not override that requirement.

## Codex heartbeat and watchers

Create or update a thread heartbeat with `automation_update`: every 15
minutes (`FREQ=MINUTELY;INTERVAL=15`), ACTIVE, named for the coordinator slug.
The prompt must say to follow the skill's Heartbeat round, check every member,
and notify only on meaningful changes, completion, failure or required user
action. Do not request a new chat for each run. Inspect existing automations
and reuse the matching one after a context reset; pause it when coordination
stops. Do not replace it with a standalone cron job unless the user requests
that mode. If scheduling is unavailable, report that gap; a shell watcher
does not supply scheduled agent turns.

Codex has no required `Monitor` tool. Run `lease.py watch inbox`, `watch prs`
and (when leases are on) `watch expiry` as long-lived commands. Save watcher
output outside the repository and track how much was read so each heartbeat
can consume new events. `write_stdin` reads a live `exec_command` session;
check background logs and process liveness when using detached processes.
Command output alone does not wake the agent. On resume, check watcher and
server liveness before starting replacements, and recover unread messages
from the durable inbox/ledger: an inbox watcher starts at the end of the file.

For a Codex member, attach its PR and handle valid hosted review/CI
blockers in that chat only while ACTIVE, using an authorized heartbeat if
later turns are needed. On PAUSE, stop repair work for that PR and pause its
repair heartbeat.
Never claim Auto-fix is enabled merely because a PR is attached.

## New Codex sessions and permissions

Keep the enrollment kickoff first in every independent session's prompt.
Use supported permission controls to start it with actual
`sandbox_mode="danger-full-access"` and `approval_policy="never"`, and verify
the first turn's execution context. For CLI launches, use
`--sandbox danger-full-access` and `-c 'approval_policy="never"'` (check the
installed command's help). Retain this mode for follow-ups and heartbeats.
Prompt wording and saved defaults are not proof. If the creation path cannot
ensure it, keep dispatch pending and report the capability gap; do not launch
a restricted replacement. Full access does not broaden task authorization.
