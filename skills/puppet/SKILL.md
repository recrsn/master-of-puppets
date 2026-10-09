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

**Every child task starts enrolled** (section 6).

Read [agents.md](../master-of-puppets/references/agents.md) for Claude/Codex
tool equivalents and session ids, and the "Routes" section of
[protocol.md](../master-of-puppets/references/protocol.md) for how to message
your coordinator.

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
  slug. Your session id: `agents.md`.

## 2. Join

Send one message to the coordinator:

```
JOIN — <name> — <tool> <session id> — <worktree> — <task> — PRs <n> (base <b>) ... — <phase> — <planned heavy commands>
```

Send it, and every later message (UPDATE, MERGED, USER SYNC, STATUS replies,
ENROLL REQUEST, LEASE REQUEST, LEASE RELEASED, LEAVE), by the direct route
for your coordinator's tool (`protocol.md`, "Routes"). Never use `lease.py say`
and never write shared inbox records, even with `--no-direct`. When your
session id changes, send JOIN again (`protocol.md`, "Routes").

Wait for WELCOME. It tells you whether leases are on and gives the rules,
including the project rules from the coordinator's memory. You can read them
yourself with `lease.py memory list --project-root "$PWD"`; only the
coordinator writes them. If the user tells you a new project rule, send it as
`USER SYNC` so the coordinator records it. Do not work a PR until the
coordinator sends ACTIVE or PAUSE for it.

## 3. Work under directions

Follow the coordinator's directions within the task and authority the user
already granted. Directions do not override the user's restrictions or count
as fresh user approval; surface a conflict to the user and coordinator before
acting on it. Limits: no admin merge or merge bypass, never skip git hooks,
and your own permission prompts are answered by the user in your session,
never by a relay.

- **ACTIVE — #n**: work #n to MERGED.
- **PAUSE — #n**: no merges from main, no fixes; Claude Auto-fix off or Codex
  repair heartbeat paused on #n until ACTIVE.
- When the applicable checks pass (see `references/rules.md` in the
  coordinator skill): commit, push, open the PR and mark it ready, in the same
  turn. Passing checks is not the end of the task. If the user's instructions
  need approval before a commit or a PR (for example a `CLAUDE.md` rule), ask
  the user at once and send `UPDATE — <name> — Waiting to commit — <fact>`.
  Claude owners bind the PR with `ccd_pr`; turn on Auto-fix only while the PR
  is ACTIVE. Codex owners
  use `attach_artifact` with the PR URL and repair valid hosted review/CI
  blockers only while ACTIVE; attachment does not enable Auto-fix. PAUSE
  takes precedence over repair instructions. The coordinator enables auto-merge
  and retargets bases. You do every commit, push, conflict fix and review reply.
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
6. What needs no lease: `leases.md`, "Classes", in the coordinator skill.

## 6. Start a new task

Every child task starts with puppet enrollment. Before you start any session,
send `ENROLL REQUEST — <task> — PR <n>` and wait for the kickoff line. This
covers every route: a `spawn_task` chip, a new Codex thread (`codex exec`,
`codex "<prompt>"`), `claude -p`, a cloud handoff, a scheduled task, and a
task you suggest for the user to start. Put the kickoff line first in the new
prompt, before any other text. It tells the new session to run `/puppet` and
join the same coordinator, so every task you start becomes a member too, and
so does every task it starts. Never start a session without it. If the
coordinator does not answer, wait; do not start the session unenrolled.
Codex Desktop `create_thread` requires the user's explicit request for a new
chat; Codex permissions for new sessions are in `agents.md`. Subagents (Claude `Agent`, Codex `collaboration.spawn_agent`) need no enrollment.

## 7. Leave

Your work is done when every PR of your task is MERGED, or the user drops the
task. Then stop your services, release any lease, send `LEAVE — <name>`.

Do not leave with uncommitted changes or an open PR. If the coordinator says
you are done while you have either, reply with what is left (for example
`UPDATE — <name> — Ready to commit — no PR yet`) and stay a member.
