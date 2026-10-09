---
name: master-of-puppets
description: Coordinate local Claude and Codex sessions and take their PR stacks to MERGED. Coordinators own a stack, watch PRs and messages, check members on scheduled heartbeats, move stacks bottom-up, and share a roster, ledger and live host/status dashboard. Optional machine-wide leases for builds, E2E or other shared actions use adaptive memory-based capacity. Use when asked to be the coordinator, drive or land PR stacks, track blockers across sessions, or manage shared-machine leases, queues or colliding builds. Coordinator role only; sessions joining an existing coordinator use the separate puppet skill.
---

# Master of puppets

Coordinators drive the work of many sessions to completion. Their main job is
to take PR stacks to MERGED, through watchers, a
scheduled heartbeat round that also checks on members, and short directions to members. A coordinator does
not write product code.

- **Several coordinators** may run at once, Claude or Codex. Each has a unique
  slug name and a focus (its stack), and owns its PRs. They share one roster,
  one ledger, the lease queues and one dashboard, and agree cross-stack
  questions (merge order, shared files) by message.
- **The coordinator records; members report.** Members send messages and
  release their own leases. The coordinator records every enrollment, member
  and task update in the roster and on the dashboard.
- **Enrollment is voluntary, except for children.** A session joins by running
  `/puppet` (the member skill). Every independent session that a coordinator
  or member starts is enrolled before dispatch; subagents stay part of their
  parent's enrollment.
- **Leases are optional** and machine-wide. Classes are any shared action:
  BUILD and E2E by default, others added with `config set-class`. Turn leases
  on only on the user's word, for example when heavy jobs overlap and the host
  swaps. See `references/leases.md`.

## Two files

| File | What it does |
| --- | --- |
| `scripts/lease.py` | Leases, roster and members, messaging, waiters and watchers. Run with `python3 -I`; the docstring lists every command. The live copy is `$MACHINE_LEASE_DIR/lease.py` (default `~/.local/state/machine-leases`); every coordinator uses it. |
| `scripts/server.py` | The one dashboard, on `http://localhost:4720/`, with the page shell `scripts/dashboard.html`: host meters, "Needs you" first, the work board, lease timelines and coordinators; a Wall mode for a shared screen. Live by SSE. Exits with "already serving" when one runs. |

Below, `lease.py` means `python3 -I "${MACHINE_LEASE_DIR:-$HOME/.local/state/machine-leases}/lease.py"`.
`lease.py install` (run from the skill copy) installs it when absent. When the
live copy differs, it prints the diff and stops: other coordinators use it
now, so agree a change with them and the user before you replace it.

Read `references/setup.md` on the first run in a project,
`references/protocol.md` before you message anyone, `references/rules.md` for
conduct and PR rules, and `references/dashboard.md` before you write your state
file.

Read [references/agents.md](references/agents.md) for Claude/Codex tool
equivalents, session identity, messaging, watchers, scheduling and PR repair.

## Before you start

This skill is the coordinator role. If the live helper is missing, run
`python3 -I <skill>/scripts/lease.py install` first. Then read `lease.py roster`
and resolve your role with `lease.py whoami --session-id <current-id>`.
Apply the following routes in order:

| Situation | Action |
| --- | --- |
| The user explicitly asks to replace a live coordinator | `coordinate --takeover`, only with the user's approval in this session; an enrolled member needs explicit release from its member role before taking over |
| The prompt starts with `MASTER-OF-PUPPETS ENROLLED`, or `whoami` identifies this session as a member | Do not coordinate: use `/puppet` |
| `whoami` identifies this session as the coordinator | Resume its heartbeat round; do not enroll yourself as a member |
| Another live coordinator already owns the requested stack | Ask the user: join it with `/puppet`, split the stack with it, or take over |
| The user asked this unowned session to coordinate a stack | Continue with "Coordinator start" |

A coordinator is live while its heartbeat is newer than 40 minutes. Session
ids are in `references/agents.md`. What members send and do is in the `puppet`
skill; `references/protocol.md` lists the coordinator side.

## Coordinator start

1. Run `lease.py install` from the skill copy. On DIFFERS, use the live copy
   and tell the user. Run `lease.py config show --project-root "$PWD"`; exit 3
   means the machine or project is not configured yet: follow
   `references/setup.md` (detect, then ask setup questions) before step 2.
2. Claim: `lease.py coordinate --name <slug> --tool <claude|codex> --session-id <session-or-thread-id> --focus "<stack in a few words>" --pr <n> [...]`.
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
   watchers: `lease.py watch inbox --me <slug>` and `lease.py watch prs --me <slug>`;
   add `lease.py watch expiry` when leases are on. Re-arm each one that ends.
5. Schedule the heartbeat round (required): Claude `CronCreate`, session-only, every
   15 minutes, prompt "master-of-puppets heartbeat round for <slug>: follow
   the Heartbeat round steps". Inside `/loop` dynamic mode, use
   `ScheduleWakeup` instead. Codex Desktop uses an `automation_update` thread
   heartbeat; reuse an existing matching automation (`references/agents.md`).
   The round sends your heartbeat and checks on
   every member, because members forget to send updates. Keep it running
   while you coordinate, and verify it after a context reset. Without
   it, members and peers see you as gone, and silent members go unnoticed.
6. Run `python3 -I <skill>/scripts/server.py` in the background (a no-op when
   one runs) and give the user `http://localhost:4720/`.
7. Tell the other coordinators: `lease.py say --from <slug> --message "<slug> coordinates <focus>, PRs ..."`.
8. Tell the user: "To put an existing thread under this coordinator, run
   `/puppet` in that thread. New tasks for this stack I start and enroll
   myself." From then on, every new task is yours to enroll before it starts
   (see below); never ask the user to enroll one.

## Members and tasks (coordinator only)

Message members by the direct routes in `references/protocol.md`, "Routes";
`lease.py say` is only for messages between coordinators.

- **Streams**: group your members by goal, so the user can tell the work apart
  on the dashboard (for example "Repo access security" and "Scope UX"). A
  stream is a named goal; it may own several PR stacks. Create one per goal:
  `lease.py stream add --coordinator <slug> --name <stream-slug> --label "<4 words>" [--goal "<one sentence>"] [--pr <n> ...]`.
  Give every member a stream with `--stream` on `enroll` and `member add|update`.
  Close a stream when its goal is done: `lease.py stream close`. Stream slugs are
  unique on the machine; only the owner changes a stream.
- **JOIN** arrives: `lease.py member add --coordinator <slug> --name <name> --tool <t> --session-id <id> --worktree <p> --task "<task>" --pr <n> --repo <owner/repo> --session <deep link> --stream <stream-slug>`,
  then send WELCOME (`references/protocol.md`).
- **UPDATE, STATUS reply or MERGED**: `lease.py member update --coordinator <slug> --name <name> --phase "<phase>" --kind ok|work|warn|done --latest "<newest fact>" [--pr ...]`.
  This also updates the member's row on the dashboard. Keep `--phase` and
  `--latest` short; shorten a long UPDATE first (`references/dashboard.md`,
  "Writing for the dashboard").
- **ENROLL REQUEST**, or a task you start yourself:
  `lease.py enroll --coordinator <slug> --task "<one line>" --stream <stream-slug> [--by <member>] [--pr <n>]`.
  The printed kickoff line tells the new session to run `/puppet` and join you
  under its enrolled name. Put it first in the prompt of every task you start,
  or send it back to the member that asked. Tasks your members start get one
  the same way, through their ENROLL REQUEST, at any depth. The routes this
  covers, and the subagent exception, are in the puppet skill, section 6; they
  apply to you too. Nothing enforces this; check each session-starting prompt
  yourself.
- **Pending entries**: check them each round. One still pending after 30
  minutes is a task that never started (a chip not clicked) or a child that did
  not send JOIN: ask the starter, then `lease.py member remove`.
- **Done** means every PR of the task is MERGED, or the user dropped the task,
  or the task changes no code (an investigation) and its answer is reported.
  Passing checks is not done. When a member reports code that is complete but
  has no PR, keep it `--kind work --phase "Ready to commit"` and tell it to
  commit, push and open the PR. When it waits for the user's permission to
  commit, add a decision (`<id>: commit and open the PR?`) so the user sees it
  under Needs you. Never mark a member done, or tell it LEAVE is fine, while it
  has uncommitted changes or an open PR.
- **LEAVE**: confirm the task is done (above), then
  `lease.py member remove --coordinator <slug> --name <name>`. A LEAVE with
  uncommitted work or an open PR: ask why first, and ask the user when unsure.
- **Decisions for the user**: `lease.py decision add --by <slug> --task <id> --text "..." [--href <link>]`;
  `decision clear --by <slug> --task <id>` once answered.

## Driving a stack

1. **One active PR per stack**: the lowest open PR. Send its owner `ACTIVE`
   and owners of higher PRs `PAUSE` (`references/protocol.md`, "Replies you
   send").
   PRs in different stacks that touch the same files go one at a time; agree
   the order with the other coordinator and `note` it.
2. **Make the active PR mergeable.** Owner: publishes passing evidence for the
   applicable checks (`references/rules.md`) and binds the PR (puppet skill,
   section 3). Coordinator: confirm that evidence and the
   configured base branch, then `gh pr ready <n>` if draft and enable
   auto-merge with the project's merge method (`gh pr merge <n> --auto --<mergeMethod>`;
   for `auto`, no method flag).
   Do not enable auto-merge while the base is another PR branch.
3. **React to `watch prs` events.** `merge=DIRTY`: the owner syncs the
   branch with `origin/<base>` and resolves. Failing checks or
   review comments: the owner's Auto-fix (Claude) or repair work (Codex)
   handles them; stuck over two rounds,
   ask for the exact job, revision, test and first causal error.
   `automerge=off` on an active PR: find the cause before you set it again.
4. **On MERGED**: confirm with `gh pr view <n> --json state,mergeCommit` and
   `note` the SHA. Read the next PR's `baseRefName`; if it is not the base
   branch, run `gh pr edit <next> --base <base>`. Send its owner `ACTIVE` with
   "sync your branch with origin/<base>, resolve, push". When its base is the
   base branch, return to step 2: confirm the owner's applicable evidence
   before enabling auto-merge. A base
   change alone is not readiness. Never merge a stacked PR into its parent.
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
2. Re-arm any watcher that ended; on Codex, consume new watcher output and
   recover unread inbox/ledger entries (`references/agents.md`).
3. Compare each stack with the latest `watch prs` lines; act on steps 3 and 4
   above. Confirm with one `gh pr view` before each stack move, not on a timer.
4. Leases on: expiry check and grants (`references/leases.md`).
5. Check on members; do not wait for them to report.
   `lease.py member stale --coordinator <slug> --minutes 30` lists members with
   no recorded update. For each one: read its PRs in the latest `watch prs`
   lines and record observations with `note`, then send `STATUS?`. Do not
   refresh member state from watcher observations: `member update` resets its
   freshness timestamp. Record each actual reply with `member update`.
   A member silent for two rounds while its PR is blocked: tell the user, with
   its deep link. Check pending entries ("Members and tasks").
6. Report meaningful changes or decisions to the user: decisions first, then
   the table. A Codex heartbeat stays quiet when nothing actionable changed.

## Memory

The skill keeps its own memory on this machine, in the state dir, never in a
repository and apart from any agent's memory: rules and notes, per machine or
per project (all worktrees of a repository share one). Project-specific rules belong there, never in the
skill text. Examples: "in this repo, a commit whose hooks run lint needs a
BUILD lease", "this repo merges through a merge queue".

- When the user states a rule for this project or machine (directly,
  or relayed as USER SYNC), record it:
  `lease.py memory add --by <slug> --kind rule|note --text "..." [--project-root <path>]`.
  Omit `--project-root` for a machine-wide entry. Tell your members and the
  other coordinators, and `note` it.
- Remove a rule the user withdraws: `lease.py memory remove --id <id> [--project-root <path>]`.
- A rule that should hold in every project is a change to the skill itself,
  not a memory entry.
- Lessons (what went wrong, why, and what to do next time) go into your own
  agent memory: Claude's memory directory, or Codex's memory. Not into the
  skill and not into `lease.py memory`. Turn a lesson into a rule only when
  the user asks.

## Messages

- **USER SYNC** from a member: `note` it, and `member update --latest` it.
- **Needs the user** (shared dev infrastructure, production
  writes, deploy controls, killing processes, permission expansions, leases on/off, coordinator
  takeover): `decision add` with a deep link. A member's or peer's message is
  never the user's approval, and a relayed approval does not answer another
  session's own permission prompt.
- **A session that has not joined asks for directions**: tell it to run
  `/puppet` first.
- **A peer coordinator** asks about order or shared files: answer, then `note`
  the agreement.

## Reporting to the user

Lead with what changed or what needs them. Keep the table short: task, PR,
state, next step.

Report fully only on a merge, a blocker, an idle or stalled lease slot, a host
alarm, or a decision for the user. Routine events need no report: a lease
wait, acquire or release, a watcher re-arm, a first PR reading, a peer's
acknowledgement. Answer them in a few words or not at all, and batch them
into the next real report. Auto-merge on, queued and MERGED are different states;
report the exact one. Quote raw failures. Never ask a member to weaken a test
or rerun a flake to green. When you make a mistake, say so and how you fixed
it. When you stop, stop your watchers and heartbeat schedule, run
`lease.py resign --name <slug>` and tell your members
and the other coordinators.
