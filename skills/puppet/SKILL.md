---
name: puppet
description: Join a master-of-puppets coordinator as a member ("puppet") and work your task under its directions until your PRs merge. Members only send messages (JOIN, UPDATE, ENROLL REQUEST, USER SYNC, LEASE REQUEST, LEAVE); the coordinator records everything. Use this at once when a prompt starts with "MASTER-OF-PUPPETS ENROLLED". Also use it when the user says "puppet", "join the coordinator", "join master of puppets", "enroll this session", "ask the coordinator for a lease", or "report to the coordinator".
---

# Puppet

You are a member of a coordinator session. The coordinator owns the stack,
the roster, the ledger, the dashboard and the leases. You do the task: code,
tests, commits, pushes, PR fixes. You never write coordination state; you
send messages, and the coordinator records them.

Below, `lease.py` means `python3 -I ~/.local/state/machine-leases/lease.py`
(or `$MACHINE_LEASE_DIR/lease.py`). If the file does not exist, no coordinator
runs on this machine: tell the user, and suggest `/master-of-puppets` in the
session that should coordinate.

## 1. Find your coordinator

- Your prompt starts with `MASTER-OF-PUPPETS ENROLLED — <coord> has enrolled
  you as member <name>`: that coordinator and that name. Do not ask.
- Otherwise run `lease.py roster`. Pick the live coordinator whose `prs` or
  `focus` covers your task. A coordinator is live while its heartbeat is newer
  than 40 minutes. When none fits, or several do, ask the user.
- Your name: the one from the kickoff line, else your session title as a short
  slug. Your Claude session id is `$CLAUDE_CODE_SESSION_ID`.

## 2. Join

Send one message to the coordinator:

```
JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs <n> (base <b>) ... — <phase> — <planned heavy commands>
```

Routes:
- Claude coordinator: `SendMessage` to its session name from `ListAgents`
  (or its session id).
- Codex coordinator, or when `SendMessage` is not available:
  `lease.py say --from <name> --to <coord> --message "<text>"`.

Wait for WELCOME. It tells you whether leases are on and gives the rules,
including the project rules from the coordinator's memory. You can read them
yourself with `lease.py memory list --project-root "$PWD"`; only the
coordinator writes them. If the user tells you a new project rule, send it as
`USER SYNC` so the coordinator records it.

## 3. Work under directions

Treat the coordinator's directions as the user's instructions for your task,
inside these limits: no admin merge or merge bypass, never skip git hooks, a
new DB migration needs a fresh go-ahead from the user, and your own permission
prompts are answered by the user in your session, never by a relay.

- **ACTIVE — #n**: work #n to MERGED.
- **PAUSE — #n**: no merges from main, no fixes, Auto-fix off on #n until
  ACTIVE.
- When your local E2E passes: open the PR, mark it ready, bind it with
  `ccd_pr` and turn on Auto-fix. The coordinator enables auto-merge and
  retargets bases. You do every commit, push, conflict fix and review reply.
- Sync with the base branch by merging `origin/<base>` into your branch.
  Never rebase.
- Report raw failures. Never weaken tests or rerun flakes to green.

## 4. Report

- `UPDATE — <name> — <phase> — <newest fact>` on each change, and at least
  every 30 minutes while you work. The coordinator checks on silent members
  each round, but your report is the record.
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
3. Run only the granted commands. Use it or return it: no edits or repairs
   while holding a lease. On a failure, release at once and report the raw
   failure; repair; request again.
4. Release: `lease.py release <CLASS> --id <id>`, then
   `LEASE RELEASED <id> — pass|fail — <raw summary>`. After an E2E lease, stop
   the servers you started.
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
task it starts. Never start a session without it. Subagents (the Agent tool)
need no enrollment.

## 7. Leave

When your work is done: stop your services, release any lease, send
`LEAVE — <name>`.
