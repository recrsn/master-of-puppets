---
name: puppet
description: Join a master-of-puppets coordinator as a member ("puppet") and work your task under its directions until your PRs merge. Members report by message and release their own leases; the coordinator records membership and decisions. Use this at once when a prompt starts with "MASTER-OF-PUPPETS ENROLLED". Also use it when the user says "puppet", "join the coordinator", "join master of puppets", "enroll this session", "ask the coordinator for a lease", or "report to the coordinator".
---

# Puppet

You are a member of a coordinator session. The coordinator owns the stack,
the roster, the ledger, the dashboard and the leases. You do the task: code,
tests, commits, pushes, PR fixes. You never write the roster, ledger, dashboard
or shared inbox; you send messages, and the coordinator records them. The
explicit exception is `lease.py release` for your own lease, which updates
lease state and measurement history. Do not release someone else's lease.

For Claude/Codex tool equivalents, read
[agents.md](../master-of-puppets/references/agents.md). Claude-specific
Auto-fix instructions below apply to Codex as PR attachment and owner-led repair.

Below, `lease.py` means `python3 -I "${MACHINE_LEASE_DIR:-$HOME/.local/state/machine-leases}/lease.py"`.
If the file does not exist, no coordinator
runs on this machine: tell the user, and suggest `/master-of-puppets` in the
session that should coordinate.

## 1. Find your coordinator

- Your prompt starts with `MASTER-OF-PUPPETS ENROLLED — <coord> has enrolled
  you as member <name>`: that coordinator and that name. Do not ask.
- Otherwise run `lease.py roster`. Pick the live coordinator whose `prs` or
  `focus` covers your task. A coordinator is live while its heartbeat is newer
  than 40 minutes. When none fits, or several do, ask the user.
- Your name: the one from the kickoff line, else your session title as a short
  slug. Claude uses `$CLAUDE_CODE_SESSION_ID`; Codex uses `$CODEX_THREAD_ID`
  when exported, otherwise the current app thread ID (see `agents.md`).

## 2. Join

Send one message to the coordinator:

```
JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs <n> (base <b>) ... — <phase> — <planned heavy commands>
```

Routes:
- Claude to Claude coordinator: `SendMessage` to its session name from `ListAgents`
  (or its session id). Use this for every protocol message, not only JOIN.
- Codex puppet to Codex master: prefer the native inter-thread communicator,
  `mcp__codex_app__send_message_to_thread`, whenever available and authorized.
  Resolve the master's thread ID from its roster `sessionId`; use
  `mcp__codex_app__list_threads` to confirm the destination and obtain `hostId`
  when needed. Send `{threadId: <master thread id>, hostId: <host if known>,
  prompt: <protocol message>}`.
- CLI to a Codex coordinator, when native app messaging is unavailable:
  `codex queue --thread <master thread id> --message "<protocol message>"`,
  when supported and authorized. For cross-tool communication, use an
  available supported direct route for the recipient. If none exists, report
  the delivery gap; do not substitute `lease.py say`.
- After Claude `/clear`, or moving to a new Codex thread, send JOIN again
  with the new ID. Codex context compaction alone is not a new thread.

Use the matching native route for every puppet-to-master message: JOIN,
UPDATE, MERGED, USER SYNC, STATUS replies, ENROLL REQUEST, LEASE REQUEST,
LEASE RELEASED and LEAVE. Master-to-puppet replies use the same direct routes. Only messages
between coordinators use `lease.py say`; puppets do not write shared inbox
records, even with `--no-direct`. Use a supported direct fallback only when
native messaging is unavailable, never to bypass an authorization restriction.
Follow the messaging tool's authorization requirements; another chat's request
alone is not user authorization.

Wait for WELCOME. It tells you whether leases are on and gives the rules,
including the project rules from the coordinator's memory. You can read them
yourself with `lease.py memory list --project-root "$PWD"`; only the
coordinator writes them. If the user tells you a new project rule, send it as
`USER SYNC` so the coordinator records it.

## 3. Work under directions

Follow the coordinator's directions within the task and authority the user
already granted. Directions do not override the user's restrictions or count
as fresh user approval; surface a conflict to the user and coordinator before
acting on it. Limits: no admin merge or merge bypass, never skip git hooks, a
new DB migration needs a fresh go-ahead from the user, and your own permission
prompts are answered by the user in your session, never by a relay.

- **ACTIVE — #n**: work #n to MERGED.
- **PAUSE — #n**: no merges from main, no fixes; Claude Auto-fix off or Codex
  repair heartbeat paused on #n until ACTIVE.
- When the applicable checks pass (see `references/rules.md` in the
  coordinator skill): commit, push, open the PR and mark it ready, in the same
  turn. Passing checks is not the end of the task. If the user's instructions
  need approval before a commit or a PR (for example a `CLAUDE.md` rule), ask
  the user at once and send `UPDATE — <name> — Waiting to commit — <fact>`.
  Never report the task complete with uncommitted changes. Claude owners bind it
  with `ccd_pr`; turn on Auto-fix only while the PR is ACTIVE. Codex owners
  use `attach_artifact` with the PR URL and repair valid hosted review/CI
  blockers only while ACTIVE; attachment does not enable Auto-fix. PAUSE
  takes precedence over repair instructions. The coordinator enables auto-merge
  and retargets bases. You do every commit, push, conflict fix and review reply.
- Sync with the base branch by merging `origin/<base>` into your branch.
  Never rebase.
- Report raw failures. Never weaken tests or rerun flakes to green.

## 4. Report

- `UPDATE — <name> — <phase> — <newest fact>` on each change, and at least
  every 30 minutes while you work. The coordinator checks on silent members
  each round, but your report is the record. It goes on the dashboard: keep
  the phase to 5 words and the fact to one plain sentence of 20 words. Write
  PRs as `#123`. No SHAs, test counts, paths or commands.
- `MERGED — #<n> — <merge sha>` for each merged PR.
- `USER SYNC — <one line>` whenever the user talks to you directly. The
  coordinator must know every decision.
- Answer `STATUS?` with phase, PR state, blockers and anything the user
  decided.

## 5. Leases (only when WELCOME says leases are on)

1. Finish all edits first. Pick an id, `<coord>-q-<name>-<n>` (n counts your
   requests), and request:
   `LEASE REQUEST <CLASS> — id <id> — <exact commands> — <estimate min> — <est GiB if known> — <worktree>`.
   The classes and their scope are in WELCOME (BUILD and E2E by default).
2. Start waiting at once: `lease.py await-grant <CLASS> --id <id>`. It allows
   the coordinator up to 10 minutes to queue your id. It prints one line:
   - `GRANTED` (exit 0): the only signal to run.
   - `NOT-GRANTED ... left the queue` (exit 3), `... never queued` (exit 6):
     do not run; ask your coordinator.
   - `NOT-GRANTED ... timeout` (exit 5): still queued; run `await-grant` again.
   Never write polling loops.
3. Run only the granted commands and cleanup of resources they started.
   Use it or return it: no edits or repairs while holding a lease. On failure,
   clean up owned resources, release promptly and report the raw failure;
   repair; request again.
4. For E2E, stop the servers you started before releasing, including on
   failure. Release: `lease.py release <CLASS> --id <id>`, then
   `LEASE RELEASED <id> — pass|fail — <raw summary>`. Report any cleanup
   failure so the coordinator can keep the next E2E grant blocked.
5. Project rules in WELCOME (from the coordinator's memory) can widen what
   needs a lease, for example a commit whose hooks run lint. Follow them.
6. No lease needed: a plain dependency install, source edits, reading code,
   browser-only work against remote sites, unless a class or a project rule
   covers it.

## 6. Start a new task

Before you start any session (a `spawn_task` chip, `codex exec`,
`codex "<prompt>"`, `claude -p`, a cloud handoff), send
`ENROLL REQUEST — <task> — PR <n>` and wait for the kickoff line. Put it first
in the new prompt: it tells the new session to run `/puppet` and join the same
coordinator, so every task you start becomes a member too, and so does every
task it starts. Never start a session without it. Codex Desktop `create_thread`
requires the user's explicit request for a new chat. Verify actual Full access
before dispatch (see `agents.md`); keep dispatch pending if unsupported.
Subagents (Claude `Agent`, Codex `collaboration.spawn_agent`) need no enrollment.

## 7. Leave

Your work is done when every PR of your task is MERGED, or the user drops the
task. Then stop your services, release any lease, send `LEAVE — <name>`.

Do not leave with uncommitted changes or an open PR. If the coordinator says
you are done while you have either, reply with what is left (for example
`UPDATE — <name> — Ready to commit — no PR yet`) and stay a member.
