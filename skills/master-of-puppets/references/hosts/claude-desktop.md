# Claude Desktop

Read this when your host is Claude Desktop (`CLAUDE_CODE_ENTRYPOINT=claude-desktop`;
[README.md](README.md) tells you how to find your host). Use only the tools
that your session has; search for a deferred tool by name before you decide it
is missing.

| Purpose | Do this |
| --- | --- |
| Your session id | `$CLAUDE_CODE_SESSION_ID` |
| Find other sessions | `ListAgents`. It lists the Claude sessions on this machine, in every host. App ids look like `local_...`. |
| Send a message | `SendMessage` to the session name from `ListAgents`, or to its session id. It reaches Claude sessions only. |
| Reach a Codex thread | No app route: [README.md](README.md), "No shared route" |
| Scheduled turn (heartbeat, scout tick) | `CronCreate`, session-only. Inside `/loop` dynamic mode, `ScheduleWakeup`. |
| Watch a command | `Monitor` |
| Start a subagent | `Agent`. Children stay part of the parent's enrollment. |
| Start an independent session (coordinators only) | Suggest a task card or chip with the enrollment line first; the user starts it |
| Ask the user | `AskUserQuestion` |
| Bind a PR and repair blockers | `ccd_pr`, and Auto-fix while the PR is ACTIVE |
| Open the dashboard | Browser tools, `http://localhost:4720/` |

## Send failures

- **Paused:** a session that gets 10 messages from other sessions with no
  user message in between pauses. Further sends return "Paused" until the
  user types in that session. A name route resets less often than a
  session-id route: prefer the name. Tell the user which session is paused.
- **"No agent named ...":** the name changed. Run `ListAgents` again, or
  send by session id.
- **A script's socket message is held:** a receiver that bypasses
  permission prompts holds a socket message from a script for the user's
  approval. The app cannot show that dialog and drops the message after
  `dialogExpiry`. The user decides whether to set `crossSessionInbound` to
  `accept` for that session; never change it yourself.
