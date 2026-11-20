# Hosts

A host is the app that runs a session: T3 Code, Claude Desktop, the Claude
Code CLI, Codex Desktop or the Codex CLI. The provider (Claude or Codex) is a
different thing. The host decides which tools a session has to send a
message, list sessions, schedule a turn and start a session. A Codex thread in
T3 Code sends with `t3_thread_send`, not with Codex Desktop's
`send_message_to_thread`. Never assume a tool from the provider.

Every coordinator, puppet and scout finds its own host first, then reads
only that host's guide.

## Find your host

1. When `puppet.py --help` (or `coordinator.py --help`) lists `host`, run
   `puppet.py host`. It prints your host, provider, session id and guide.
2. Else, read your environment once (`env`), and use the first line that
   matches:

   | Marker | Host | Guide |
   | --- | --- | --- |
   | `CLAUDE_CODE_ENTRYPOINT=t3-code`, a `T3CODE_THREAD_ID` variable, `__CFBundleIdentifier=com.t3tools.t3code`, or `CODEX_INTERNAL_ORIGINATOR_OVERRIDE` that starts with `T3` | T3 Code | [t3-code.md](t3-code.md) |
   | `CLAUDE_CODE_ENTRYPOINT=claude-desktop` | Claude Desktop | [claude-desktop.md](claude-desktop.md) |
   | Another `CLAUDE_CODE_ENTRYPOINT` (`cli`, `sdk-ts`, `sdk-cli`, an IDE) | Claude Code CLI, IDE or SDK | [claude-code.md](claude-code.md) |
   | `CODEX_INTERNAL_ORIGINATOR_OVERRIDE=Codex Desktop`, or `__CFBundleIdentifier=com.openai.codex` | Codex Desktop | [codex-desktop.md](codex-desktop.md) |
   | `CODEX_THREAD_ID` and none of the above | Codex CLI | [codex-cli.md](codex-cli.md) |

   A Codex thread started from a Claude session can inherit
   `CLAUDE_CODE_ENTRYPOINT`. When you are Codex, skip the Claude rows.
3. Check against your tool list: `t3_thread_send` means T3 Code;
   `send_message_to_thread` (prefix `mcp__codex_app__`) means Codex Desktop;
   `SendMessage` with no T3 tools means a Claude host. A tool can be
   deferred: search for it by name before you decide it is missing. Tool
   prefixes differ by provider (`mcp__t3-code__` in Claude,
   `mcp__t3_code__` in Codex): match the bare name.
4. When nothing matches, your host is unknown: use the inbox routes only
   ("No shared route", below) and tell the user.

Find your host again after a context summary, a `/clear`, or a move to
another app. When it changed, send JOIN (or SCOUT JOIN) again.

## Who reaches whom

Each send tool reaches only some receivers. `puppet.py route` (and the
coordinator's printed app routes) list only the routes from your host to the
receiver's host. Without the command, use this table:

| From (host, provider) | To | Route |
| --- | --- | --- |
| T3 Code, either | a T3 Code thread | `t3_thread_send` by thread id |
| any Claude host | a Claude session on this machine, in any host | `SendMessage` to the session id or the `ListAgents` name |
| Codex Desktop | a Codex Desktop thread | `send_message_to_thread` |
| Codex CLI | a Codex CLI thread | `codex queue --thread <id>`, when `codex queue --help` exists |
| any | anything else | "No shared route", below |

## No shared route

When no app route connects the two hosts, use the shared inbox:

- A member to its coordinator: `puppet.py tell --text "..."`, when
  `puppet.py --help` lists it. The coordinator's `watch` shows it.
- A coordinator to a coordinator: `coordinator.py send --to <name>`.
- A coordinator to a member: no inbox reaches a member. Tell the user which
  member waits for which message, and ask them to paste it.

Never use GUI automation (pasting into another app's window) as a route.
