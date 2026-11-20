# Claude Code CLI, IDE or SDK

Read this when you are Claude and `CLAUDE_CODE_ENTRYPOINT` is not
`claude-desktop` or `t3-code` (for example `cli`, `sdk-ts` or an IDE;
[README.md](README.md) tells you how to find your host). These hosts differ in
which tools they load: use only the tools that your session has, and search
for a deferred tool by name before you decide it is missing.

| Purpose | Do this |
| --- | --- |
| Your session id | `$CLAUDE_CODE_SESSION_ID` |
| Find other sessions | `ListAgents`, when you have it. It lists the Claude sessions on this machine, in every host. |
| Send a message | `SendMessage` to the session name from `ListAgents`, or to its session id. It reaches Claude sessions only. Without `SendMessage`: [README.md](README.md), "No shared route". |
| Reach a Codex thread | No app route: [README.md](README.md), "No shared route" |
| Scheduled turn (heartbeat, scout tick) | `CronCreate`. Inside `/loop` dynamic mode, `ScheduleWakeup`. Without either, tell the user: a shell loop gives no agent turns. |
| Watch a command | `Monitor`, else a background command whose output you read each turn |
| Start a subagent | `Agent`. Children stay part of the parent's enrollment. |
| Start an independent session (coordinators only) | Ask the user first, with the task details. They start it with the enrollment line first in the prompt. |
| Ask the user | `AskUserQuestion`, else plain chat |
| Bind a PR and repair blockers | Watch it with `coordinator.py watch`; repair valid review and CI blockers in the owner session |
| Open the dashboard | Give the user `http://localhost:4720/` |

## Send failures

- **Paused** or **"No agent named ..."**: as in
  [claude-desktop.md](claude-desktop.md), "Send failures".
- An SDK session (`sdk-ts`, `sdk-cli`) often has no `ListAgents` and no
  scheduler. Report each missing tool to the user once, and use the inbox
  routes.
