# Codex CLI

Read this when you are Codex and have neither `t3_thread_send` nor
`send_message_to_thread` ([README.md](README.md) tells you how to find your
host). Check each CLI command with `--help` before you use it: options change
between versions.

| Purpose | Do this |
| --- | --- |
| Your session id | `$CODEX_THREAD_ID`. When it is not exported, run each command as `CODEX_THREAD_ID=<thread id> coordinator.py ...` (or `puppet.py`). Never use a subagent id. |
| Find other sessions | `codex agents`, when it exists |
| Send a message | `codex queue --thread <thread id> --message "<text>"`, when `codex queue --help` exists. It reaches threads of this CLI's app server only. |
| Reach a Claude session, a Codex Desktop thread or a T3 Code thread | No app route: [README.md](README.md), "No shared route" |
| Message a subagent | `collaboration.send_message`; `collaboration.followup_task` for new work |
| Start a subagent | `collaboration.spawn_agent` when delegation is authorized |
| Start an independent session (coordinators only) | Ask the user first. On yes, `codex exec "<prompt>"` with the enrollment line first in the prompt. |
| Ask the user | Plain chat |
| Scheduled turn (heartbeat, scout tick) | The CLI has no scheduler. Tell the user: a coordinator or scout needs a host that schedules turns. A shell loop gives no agent turns. |
| Watch a command | A background command with output saved outside the repository; read the new part each turn |
| Bind a PR and repair blockers | No native PR binding here; the coordinator's `watch` tracks PR state, and the owner checks `gh pr view` and repairs valid review and CI blockers |
| Open the dashboard | Give the user `http://localhost:4720/` |

## Sandbox and permissions

As in [codex-desktop.md](codex-desktop.md), "Sandbox and permissions".
