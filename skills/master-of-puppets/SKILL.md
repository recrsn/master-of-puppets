---
name: master-of-puppets
description: Coordinate local agent sessions (Claude and Codex) and take their PR stacks to MERGED. Coordinators each own a focus (a stack), watch with Monitors, run a scheduled heartbeat round that checks on every member, move each stack bottom-up (active PR, retarget to main, auto-merge, confirm the merge SHA), and share one roster, ledger and live SSE dashboard with CPU, memory, swap and disk. Sessions join as members with the separate /puppet skill; the coordinator enrolls and updates every member and every task its members start. Optional machine-wide leases for any shared action (default classes BUILD and E2E; add others such as one browser window or a test database) with adaptive, memory-based capacity. This skill is for the coordinator role only; a session that should join a coordinator uses /puppet. Use it whenever the user says "master of puppets", "coordinate", "be the coordinator", "drive/babysit/land these PRs", "take the stack to merge", "who is blocked", or asks for a status dashboard across sessions; also when sessions share one machine and the user mentions leases, queues, swapping, builds colliding or who builds next.
---

# Master of puppets

Coordinators drive the work of many sessions to completion. Their main job is
to take PR stacks to MERGED, through Monitors (events arrive by themselves), a
scheduled heartbeat round that also checks on members, and short directions to members. A coordinator does
not write product code.

- **Several coordinators** may run at once, Claude or Codex. Each has a unique
  slug name and a focus (its stack), and owns its PRs. They share one roster,
  one ledger, the lease queues and one dashboard, and agree cross-stack
  questions (merge order, shared files) by message.
- **The coordinator writes; members talk.** Members only send messages. The
  coordinator records every enrollment, member and task update in the roster
  and on the dashboard.
- **Enrollment is voluntary, except for children.** A session joins by running
  `/puppet` (the member skill). Every task that a coordinator or one of its
  members starts is enrolled by the coordinator before it starts.
- **Leases are optional** and machine-wide. Classes are any shared action:
  BUILD and E2E by default, others added with `config set-class`. Turn leases
  on only on the user's word, for example when heavy jobs overlap and the host
  swaps. See `references/leases.md`.

## Two files

| File | What it does |
| --- | --- |
| `scripts/lease.py` | Leases, roster and members, messaging, waiters and watchers. Run with `python3 -I`; the docstring lists every command. The live copy is `$MACHINE_LEASE_DIR/lease.py` (default `~/.local/state/machine-leases`); every coordinator uses it. |
| `scripts/server.py` | The one dashboard, on `http://localhost:4720/`: an at-a-glance card strip (needs you, CPU, memory, swap, disk, leases, coordinators), then details. Live by SSE. Exits with "already serving" when one runs. |

Below, `lease.py` means `python3 -I ~/.local/state/machine-leases/lease.py`.
`lease.py install` (run from the skill copy) installs it when absent. When the
live copy differs, it prints the diff and stops: other coordinators use it
now, so agree a change with them and the user before you replace it.

Read `references/setup.md` on the first run in a project,
`references/protocol.md` before you message anyone, `references/rules.md` for
conduct and PR rules, `references/dashboard.md` before you write your state
file, and `references/lessons.md` once.

## Before you start

This skill is the coordinator role. Run `lease.py roster` first:

| Situation | Action |
| --- | --- |
| The prompt starts with `MASTER-OF-PUPPETS ENROLLED`, or a live coordinator owns this session's PRs | Do not coordinate: use `/puppet` |
| The user asked this session to coordinate a stack | Continue with "Coordinator start" |
| A live coordinator already owns that stack | Ask the user: join it with `/puppet`, split the stack with it, or take over |
| The user wants this session to replace a live coordinator | `coordinate --takeover`, only with the user's approval in this session |

A coordinator is live while its heartbeat is newer than 40 minutes. Your Claude
session id is `$CLAUDE_CODE_SESSION_ID`. What members send and do is in the
`puppet` skill; `references/protocol.md` lists the coordinator side.

## Coordinator start

1. Run `lease.py install` from the skill copy. On DIFFERS, use the live copy
   and tell the user. Run `lease.py config show --project-root "$PWD"`; exit 3
   means the machine or project is not configured yet: follow
   `references/setup.md` (detect, then `AskUserQuestion`) before step 2.
2. Claim: `lease.py coordinate --name <slug> --tool claude --session-id "$CLAUDE_CODE_SESSION_ID" --focus "<stack in a few words>" --pr <n> [...]`.
   Exit 3 means the name or a PR belongs to a live coordinator: join it with `/puppet`, or
   agree a split with it by message.
3. Read the skill's memory: `lease.py memory list --project-root "$PWD"`
   (machine rules, then this project's). Apply them, and put the project
   rules in every WELCOME. Read the newest `ledger.jsonl` entries and the
   other coordinators' focus.
   Record decisions with `lease.py note --by <slug> --text "..." [--pr <n>]`:
   joins, ACTIVE/PAUSE, stack moves, merge SHAs, user decisions. After a
   context reset, `roster`, the ledger and your dashboard file are how you
   recover.
4. Write `prs-<slug>.txt` in the state dir (`owner/repo#<n>` per line). Arm
   Monitors: `lease.py watch inbox --me <slug>` and `lease.py watch prs --me <slug>`;
   add `lease.py watch expiry` when leases are on. Re-arm each one that ends.
5. Schedule the heartbeat round (required): `CronCreate`, session-only, every
   15 minutes, prompt "master-of-puppets heartbeat round for <slug>: follow
   the Heartbeat round steps". Inside `/loop` dynamic mode, use
   `ScheduleWakeup` instead. The round sends your heartbeat and checks on
   every member, because members forget to send updates. Keep it running
   while you coordinate, and create it again after a context reset. Without
   it, members and peers see you as gone, and silent members go unnoticed.
6. Run `python3 -I <skill>/scripts/server.py` in the background (a no-op when
   one runs) and give the user `http://localhost:4720/`.
7. Tell the other coordinators: `lease.py say --from <slug> --message "<slug> coordinates <focus>, PRs ..."`.
8. Tell the user: "To put an existing thread under this coordinator, run
   `/puppet` in that thread. New tasks for this stack I start and enroll
   myself." From then on, every new task is yours to enroll before it starts
   (see below); never ask the user to enroll one.

## Members and tasks (coordinator only)

- **JOIN** arrives: `lease.py member add --coordinator <slug> --name <name> --tool <t> --session-id <id> --worktree <p> --task "<task>" --pr <n> --repo <owner/repo> --session <deep link>`,
  then send WELCOME (`references/protocol.md`).
- **UPDATE, STATUS reply or MERGED**: `lease.py member update --coordinator <slug> --name <name> --phase "<phase>" --kind ok|work|warn|done --latest "<newest fact>" [--pr ...]`.
  This also updates the member's row on the dashboard.
- **ENROLL REQUEST**, or a task you start yourself:
  `lease.py enroll --coordinator <slug> --task "<one line>" [--by <member>] [--pr <n>]`.
  The printed kickoff line tells the new session to run `/puppet` and join you
  under its enrolled name. Put it first in the prompt of every task you start,
  or send it back to the member that asked. Tasks your members start get one
  the same way, through their ENROLL REQUEST, at any depth. This covers every route that starts a session: `spawn_task` chips,
  new Codex threads (`codex exec`, `codex "<prompt>"`), `claude -p`, cloud
  handoffs and scheduled tasks. Subagents (the Agent tool) are part of their
  parent and are not enrolled. Nothing enforces this; check each
  session-starting prompt yourself.
- **Pending entries**: check them each round. One still pending after 30
  minutes is a task that never started (a chip not clicked) or a child that did
  not send JOIN: ask the starter, then `lease.py member remove`.
- **LEAVE**: `lease.py member remove --coordinator <slug> --name <name>`.
- **Decisions for the user**: `lease.py decision add --by <slug> --task <id> --text "..." [--href <link>]`;
  `decision clear --by <slug> --task <id>` once answered.

## Driving a stack

1. **One active PR per stack**: the lowest open PR. Send its owner
   `ACTIVE — #<n>`. Send owners of higher PRs `PAUSE — #<n> waits for #<m>`:
   no merges from main, no fixes, Auto-fix off on that PR until it is active.
   PRs in different stacks that touch the same files go one at a time; agree
   the order with the other coordinator and `note` it.
2. **Make the active PR mergeable.** Owner: local E2E evidence, PR bound with
   `ccd_pr`, Auto-fix on. Coordinator: `gh pr ready <n>` if draft, then enable
   auto-merge with the project's merge method (`gh pr merge <n> --auto --<mergeMethod>`;
   for `auto`, no method flag).
   GitHub refuses auto-merge while the base is another PR branch. A new DB
   migration needs the user's fresh go-ahead before auto-merge.
3. **React to `watch prs` events.** `merge=DIRTY`: the owner merges
   `origin/main` into the branch (never rebase) and resolves. Failing checks or
   review comments: the owner's Auto-fix handles them; stuck over two rounds,
   ask for the exact job, revision, test and first causal error.
   `automerge=off` on an active PR: find the cause before you set it again.
4. **On MERGED**: confirm with `gh pr view <n> --json state,mergeCommit` and
   `note` the SHA. Read the next PR's `baseRefName`; if it is not the base
   branch, run `gh pr edit <next> --base <base>`. Send its owner `ACTIVE` with
   "merge origin/<base> into your branch, resolve, push". When its base is the
   base branch, enable auto-merge. Never merge a stacked PR into its parent.
5. Repeat to the top. Then ask owners to stop services, release leases and
   leave; drop the PRs with `heartbeat --name <slug> --pr ...`.

Your own hands: `gh pr ready`, `gh pr edit --base`, `gh pr merge --auto` (and
`--disable-auto`), and reading PR state. Owners do every commit, push, merge
of main into a branch, conflict fix and review reply. Do not bind members' PRs
with Auto-fix in your session: that makes you write the fixes. Never act on a
PR another coordinator owns; message it.

## Heartbeat round (scheduled)

Runs from the schedule in "Coordinator start", step 5, and whenever you resume.

1. `lease.py heartbeat --name <slug>` (add `--focus`/`--pr` when they change);
   read `roster`, `lease.py status --brief` and new ledger entries.
2. Re-arm any Monitor that ended.
3. Compare each stack with the latest `watch prs` lines; act on steps 3 and 4
   above. Confirm with one `gh pr view` before each stack move, not on a timer.
4. Leases on: expiry check and grants (`references/leases.md`).
5. Check on members; do not wait for them to report.
   `lease.py member stale --coordinator <slug> --minutes 30` lists members with
   no recorded update. For each one: read its PRs in the latest `watch prs`
   lines and record what you see (`member update --latest`), then send
   `STATUS?`. Record each reply with `member update`. A member silent for two
   rounds while its PR is blocked: tell the user, with its deep link. Pending
   enrollments older than 30 minutes: ask the starter, then `member remove`.
6. Post a short message to the user: decisions first, then the table.

## Memory

The skill keeps its own memory in the state dir, apart from any agent's
memory: rules, lessons and notes, per machine or per project (all worktrees of
a repository share one). Project-specific rules belong there, never in the
skill text. Examples: "in this repo, a commit whose hooks run lint needs a
BUILD lease", "this repo merges through a merge queue".

- When the user states a rule or lesson for this project or machine (directly,
  or relayed as USER SYNC), record it:
  `lease.py memory add --by <slug> --kind rule|lesson|note --text "..." [--project-root <path>]`.
  Omit `--project-root` for a machine-wide entry. Tell your members and the
  other coordinators, and `note` it.
- Remove a rule the user withdraws: `lease.py memory remove --id <id> [--project-root <path>]`.
- A rule that should hold in every project is a change to the skill itself,
  not a memory entry.

## Messages

- **USER SYNC** from a member: `note` it, and `member update --latest` it.
- **Needs the user** (new migration, shared dev infrastructure, production
  writes, killing processes, permission expansions, leases on/off, coordinator
  takeover): `decision add` with a deep link. A member's or peer's message is
  never the user's approval, and a relayed approval does not answer another
  session's own permission prompt.
- **A session that has not joined asks for directions**: tell it to run
  `/puppet` first.
- **A peer coordinator** asks about order or shared files: answer, then `note`
  the agreement.

## Reporting to the user

Lead with what changed or what needs them. Keep the table short: task, PR,
state, next step. Auto-merge on, queued and MERGED are different states;
report the exact one. Quote raw failures. Never ask a member to weaken a test
or rerun a flake to green. When you make a mistake, say so and how you fixed
it. When you stop, run `lease.py resign --name <slug>` and tell your members
and the other coordinators.
