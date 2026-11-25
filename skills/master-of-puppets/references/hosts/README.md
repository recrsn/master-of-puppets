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

1. Run `puppet.py host` (or `coordinator.py host`). It prints your host,
   provider, session id and guide. When it prints `unknown`, use the steps
   below, then record the answer with `puppet.py host --set <host>` once you
   are in the roster (after `register` for a coordinator, or after WELCOME for
   a member or scout).
2. Check your tool list. It decides over the environment:

   | You have | Host | Guide |
   | --- | --- | --- |
   | `t3_thread_send` | T3 Code | [t3-code.md](t3-code.md) |
   | `send_message_to_thread` (prefix `mcp__codex_app__`) | Codex Desktop | [codex-desktop.md](codex-desktop.md) |
   | `SendMessage` and no T3 tools, and `CLAUDE_CODE_ENTRYPOINT=claude-desktop` | Claude Desktop | [claude-desktop.md](claude-desktop.md) |
   | Claude, none of the above | Claude Code CLI, IDE or SDK | [claude-code.md](claude-code.md) |
   | Codex, none of the above | Codex CLI | [codex-cli.md](codex-cli.md) |

   A tool can be deferred: search for it by name before you decide it is
   missing. Tool prefixes differ by provider (`mcp__t3-code__` in Claude,
   `mcp__t3_code__` in Codex, `mcp_t3-code_` in Antigravity ACP): match the
   bare name. A provider other than Claude or Codex (Antigravity ACP) runs
   only in T3 Code here.
3. The environment gives hints (`env`):
   `CLAUDE_CODE_ENTRYPOINT` (`t3-code`, `claude-desktop`, `cli`, `sdk-ts`)
   for Claude, and `T3CODE_THREAD_ID` for any provider in T3 Code. For Codex,
   `__CFBundleIdentifier=com.t3tools.t3code` or
   `CODEX_INTERNAL_ORIGINATOR_OVERRIDE=T3 Code` point to T3 Code, and
   `CODEX_INTERNAL_ORIGINATOR_OVERRIDE=Codex Desktop` to Codex Desktop. The
   Codex markers are seen on the app's own processes and may be missing in a
   tool shell. A Codex thread started from a Claude session can inherit
   `CLAUDE_CODE_ENTRYPOINT`: when you are Codex, ignore it.
4. When nothing matches, your host is unknown: use the inbox routes only
   ("No shared route", below) and tell the user.

Find your host again after a context summary, a `/clear`, or a move to
another app. When it changed, send JOIN (or SCOUT JOIN) again.

## Who reaches whom

Each send tool reaches only some receivers. `puppet.py route` and the
coordinator's printed app routes list only the routes from your host to the
receiver's host. Reference table:

| From (host, provider) | To | Route |
| --- | --- | --- |
| T3 Code, either | a T3 Code thread | `t3_thread_send` by thread id |
| Reach a remote coordinator | coordinator on another machine | Follow the [remote coordinator protocol](../remote-coordinators.md). For linked T3 Code environments, see [the T3 transport](t3-code.md#remote-coordinators). |
| any Claude host | a Claude session on this machine, in any host | `SendMessage` to the session id or the `ListAgents` name |
| Codex Desktop | a Codex Desktop thread | `send_message_to_thread` |
| Codex CLI | a Codex CLI thread | `codex queue --thread <id>`, when `codex queue --help` exists |
| any | anything else | "No shared route", below |

## No shared route

When no app route connects the two hosts, use the shared inbox:

- A member to its coordinator: `puppet.py tell --text "..."`. The
  coordinator's `watch` shows it.
- A coordinator to a coordinator: `coordinator.py send --to <name>`.
- A coordinator to a member: no inbox reaches a member. Tell the user which
  member waits for which message, and ask them to paste it.

Never use GUI automation (pasting into another app's window) as a route.
