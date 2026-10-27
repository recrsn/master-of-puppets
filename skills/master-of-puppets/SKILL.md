---
name: master-of-puppets
description: Coordinate local Claude and Codex sessions and take their PR stacks to MERGED. Coordinators own a stack, watch PRs and messages, check members on scheduled heartbeats, move stacks bottom-up, and share a roster, ledger and live host/status dashboard. Optional machine-wide leases for builds, E2E or other shared actions use adaptive memory- and core-based capacity: members size their runs, and coordinators grant from rules and their own observations. Use when asked to be the coordinator, drive or land PR stacks, track blockers across sessions, or manage shared-machine leases, queues or colliding builds. Coordinator role only; sessions joining an existing coordinator use the separate puppet skill.
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
- **The coordinator records; members report.** Members send messages, queue
  their own lease requests and release their own leases. Only a coordinator
  grants. The coordinator records every enrollment, member and task update in
  the roster and on the dashboard.
- **Enrollment is voluntary, except for children.** A session joins by running
  `/puppet` (the member skill). Every independent session that a coordinator
  or member starts has the enrollment line first in its prompt; subagents stay
  part of their parent's enrollment.
- **Leases are optional** and machine-wide. Classes are any shared action:
  BUILD and E2E by default, others added with `config set-class`. Turn leases
  on only on the user's word, for example when heavy jobs overlap and the host
  swaps. See `references/leases.md`.

## Files

| File | What it does |
| --- | --- |
| `scripts/coordinator.py` | Coordinator commands: roster and members, streams, leases, messaging, shared-record reads, watchers, config, update votes and install. Run with `python3 -I`; the docstring lists every command. |
| `scripts/puppet.py` | Member commands: roster, whoami, memory list, the shared-record reads (`inbox`, `ledger`, `events`, `who`, `sizes`), and for the member's own lease `request`, `await-grant`, `extend` (asks for more time) and `release`. It cannot grant or extend. Members run only this file. |
| `scripts/moplib.py` | State code that both CLIs import. |
| `scripts/server.py` | The one dashboard, on `http://localhost:4720/`, with the page shell `scripts/dashboard.html`: host values and page links on every page. Dashboard: "Needs you" first, the work list and lease lanes. Events: coordinators and the ledger. Config and Rules: edit machine, class and project config and memory rules. Live by SSE. Exits with "already serving" when one runs. |

The live copies of `coordinator.py`, `puppet.py` and `moplib.py` are in
`$MACHINE_LEASE_DIR` (default `~/.local/state/machine-leases`); every session
uses them. Below, `coordinator.py` means
`python3 -I "${MACHINE_LEASE_DIR:-$HOME/.local/state/machine-leases}/coordinator.py"`.
`coordinator.py install` (run from the skill copy) installs the three files
when absent. When a live copy differs, it prints the diff and installs none:
other sessions use them now. An update goes through the shared vote; the
proposal and each vote also reach the other coordinators as messages:

1. One coordinator runs `update propose --by <you> --text "<what changes>"`
   from the skill copy. It records the exact files and adds a machine
   decision that asks the user Install or Do not install on the dashboard.
2. `update propose` messages every live coordinator (like `say`). Each one reads the diff
   (`install` without `--replace` prints it), and runs
   `update agree --by <you>` or `update object --by <you> --text "<why>"`.
3. The user answers the machine decision. When the user approves in your own
   session instead, record it: `update approve --by <you> --quote "<the user's words>"`.
   Either one is the user's approval for every coordinator.
4. Any coordinator runs `update status`; on "ready to install", it runs
   `install --replace --by <you>` once. The command refuses while a lease is
   granted, while a live coordinator has not agreed, or after another install,
   and it writes the file hashes to the ledger. Restart a dashboard you own.

`update` and `install` message every live coordinator themselves; do not send AGREE, installer elections or install reports by `say`.
A full install also removes obsolete helpers (an old `lease.py`); never run
one. `install` records the skill copy, and `roster`, `whoami`, `coordinate`,
`heartbeat` and `status` then print a warning when an update is due. On that
warning, start step 1, or check `update status` when a proposal exists.

Read `references/setup.md` on the first run in a project,
`references/protocol.md` before you message anyone, `references/rules.md` for
conduct and PR rules, `references/dashboard.md` before you write your state
file, `references/handoff.md` before you send or take a handoff, and
`references/coderabbit-cloud.md` before you suggest, start or track a
CodeRabbit cloud task.

Read [references/agents.md](references/agents.md) for Claude/Codex tool
equivalents, session identity, messaging, watchers, scheduling and PR repair.

## Before you start

This skill is the coordinator role. If the live helpers are missing, run
`python3 -I <skill>/scripts/coordinator.py install` first. Then read `coordinator.py roster`
and resolve your role with `coordinator.py whoami --session-id <current-id>`.
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

1. Run `coordinator.py install` from the skill copy. On DIFFERS, use the live copy
   and tell the user; replace it only through the update vote above. Run `coordinator.py config show --project-root "$PWD"`; exit 3
   means the machine or project is not configured yet: follow
   `references/setup.md` (detect, then ask setup questions) before step 2.
2. Claim: `coordinator.py coordinate --name <slug> --tool <claude|codex> --session-id <session-or-thread-id> --focus "<stack in a few words>" --pr <n> [...]`.
   Add `--general` when the user asked you to coordinate with no fixed stack
   or scope (a general-purpose coordinator).
   Exit 3 means the name or a PR belongs to a live coordinator: join it with `/puppet`, or
   agree a split with it by message.
3. Read the skill's memory: `coordinator.py memory list --project-root "$PWD"`
   (machine rules, then this project's). Apply them, and put the project
   rules in every WELCOME. Read the newest `ledger.jsonl` entries and the
   other coordinators' focus.
   Record decisions with `coordinator.py note --by <slug> --text "..." [--pr <n>]`:
   joins, ACTIVE/PAUSE, stack moves, merge SHAs, user decisions. After a
   context reset, `roster`, the ledger and your dashboard file are how you
   recover.
4. Write `prs-<slug>.txt` in the state dir (`owner/repo#<n>` per line). Arm
   watchers: `coordinator.py watch inbox --me <slug>` and `coordinator.py watch prs --me <slug>`;
   add `coordinator.py watch expiry` when leases are on, and
   `coordinator.py watch cloud --me <slug>` while you track CodeRabbit cloud
   tasks and no watch helper runs it. Re-arm each one that ends.
5. Schedule the heartbeat round (required): Claude `CronCreate`, session-only, every
   15 minutes, prompt "master-of-puppets heartbeat round for <slug>: follow
   the Heartbeat round steps". Inside `/loop` dynamic mode, use
   `ScheduleWakeup` instead. Codex Desktop uses an `automation_update` thread
   heartbeat; reuse an existing matching automation (`references/agents.md`).
   The round sends your heartbeat and checks on
   every member, because members forget to send updates. Keep it running
   while you coordinate, and verify it after a context reset. Without
   it, members and peers see you as gone, and silent members go unnoticed.
   Only an idle coordinator stops it ("When your work is done").
6. Run `python3 -I <skill>/scripts/server.py` in the background (a no-op when
   one runs) and give the user `http://localhost:4720/`.
7. Tell the other coordinators: `coordinator.py say --from <slug> --message "<slug> coordinates <focus>, PRs ..."`.
8. Tell the user: "To put an existing thread under this coordinator, run
   `/puppet` in that thread. New tasks for this stack I start and enroll
   myself." From then on, every new task is yours to enroll before it starts
   (see below); never ask the user to enroll one.

## Members and tasks (coordinator only)

Message members by the direct routes in `references/protocol.md`, "Routes";
`coordinator.py say` is only for messages between coordinators.

- **Streams**: group your members by goal, so the user can tell the work apart
  on the dashboard (for example "Repo access security" and "Scope UX"). A
  stream is a named goal; it may own several PR stacks. Create one per goal:
  `coordinator.py stream add --coordinator <slug> --name <stream-slug> --label "<4 words>" [--goal "<one sentence>"] [--pr <n> ...]`.
  Give every member a stream with `--stream` on `enroll` and `member add|update`.
  Close a stream when its goal is done: `coordinator.py stream close`. Stream slugs are
  unique on the machine; only the owner changes a stream.
- **JOIN** arrives: `coordinator.py member add --coordinator <slug> --name <name> --tool <t> --session-id <id> --worktree <p> --task "<task>" --pr <n> --repo <owner/repo> --session <deep link> --stream <stream-slug> [--parent <parent>]`.
  Pass `--parent` when JOIN lists one; it takes over that parent's pending
  child entry (same session id, else the same task text, else its only
  pending child). A JOIN with `parent none` whose session id matches a
  pending `child-of-*` entry is incomplete: ask the member to send JOIN again
  with its parent,
  then send WELCOME (`references/protocol.md`).
- **UPDATE, STATUS reply or MERGED**: `coordinator.py member update --coordinator <slug> --name <name> --phase "<phase>" --kind ok|work|warn|done --latest "<newest fact>" [--pr ...]`.
  This also updates the member's row on the dashboard. Keep `--phase` and
  `--latest` short; shorten a long UPDATE first (`references/dashboard.md`,
  "Writing for the dashboard").
- **A task you start yourself**:
  `coordinator.py enroll --coordinator <slug> --task "<one line>" --stream <stream-slug> [--pr <n>]`.
  The printed kickoff line tells the new session to run `/puppet` and join you
  under its enrolled name. Put it first in the prompt of every task you start.
  Members start their own child tasks without asking you: they write the
  enrollment line themselves (puppet skill, section 6), and the child sends
  JOIN with its parent.
- **CHILD TASK STARTED** arrives:
  `coordinator.py child --coordinator <slug> --parent <member> --task "<child task>" --tool <t> --session-id <id> [--pr <n>] [--stream <parent's stream>]`.
  It records the child as pending under its parent until the child's JOIN. The routes, the Claude and Codex rules and the subagent exception are
  in that section; they apply to you too. Nothing enforces this; check each
  session-starting prompt yourself.
- **Pending entries**: check them each round. One still pending after 30
  minutes is a task that never started (a chip not clicked) or a child that did
  not send JOIN after CHILD TASK STARTED: ask the starter, then `coordinator.py member remove`.
- **Done** means every PR of the task is MERGED, or the user dropped the task,
  or the task changes no code (an investigation) and its answer is reported.
  Passing checks is not done. When a member reports code that is complete but
  has no PR, keep it `--kind work --phase "Ready to commit"` and tell it to
  commit, push and open the PR. When it waits for the user's permission to
  commit, add a decision (`<id>: commit and open the PR?`) so the user sees it
  under Needs you. Never mark a member done, or tell it LEAVE is fine, while it
  has uncommitted changes or an open PR.
- **LEAVE**: confirm the task is done (above), then
  `coordinator.py member remove --coordinator <slug> --name <name>`. A LEAVE with
  uncommitted work or an open PR: ask why first, and ask the user when unsure.
  A LEAVE after your HANDOFF COMPLETE, or after a cloud handoff that you
  recorded, is expected (`references/handoff.md`, `references/coderabbit-cloud.md`).
- **Decisions for the user**: `coordinator.py decision add --by <slug> --task <id> --text "..." [--href <link>] [--option "..." ...]`;
  `decision clear --by <slug> --task <id>` once answered. Give 2 to 4
  `--option` suggested answers when the choices are clear ("Yes, merge it",
  "No, run E2E first"); the dashboard shows each as a button. When the user
  clicks one, the decision clears and you get a "[dashboard]" message with the
  answer and the question. That message is the user's answer to that
  decision: act on it and do not ask again. It answers only that question; it
  is not approval for anything else, and it does not answer a member
  session's own permission prompt. When the user answers in chat instead,
  `decision clear` it.
- **CodeRabbit cloud**: move work off this machine when you can. When a
  member's interactive work is done (only CI, review or conflict fixes
  remain), or a task is straightforward and needs no handholding, ask the
  user with a decision whether to move it to CodeRabbit cloud. A cloud task
  cannot run `/puppet` and never reports: you add it as a `--tool coderabbit`
  member and check it with `watch cloud`, in each round, or through a watch
  helper member. Follow `references/coderabbit-cloud.md`.
- **Priority**: every task starts at 0; a higher priority goes first. Raise
  a task (`enroll --priority 1`, `member update --priority 1`) only when the
  user asks for it to go first; a wish that a member relays is a decision
  for the user. Lower your own background work to -1 without asking when
  regular tasks wait: sweeps, scheduled or recurring runs (task text that
  starts with `sweep:` or `scheduled:`), and tasks that no user waits for. Set it back to 0 when nothing regular waits.
  Lease queues follow the priority (`references/leases.md`, "Priority"), and
  so does your attention: in each round, handle higher-priority members
  first. `note` each change.

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

1. `coordinator.py heartbeat --name <slug>` (add `--focus`/`--pr` when they change);
   read `roster`, `coordinator.py status --brief` and new ledger entries.
2. Re-arm any watcher that ended; on Codex, consume new watcher output and
   recover unread inbox/ledger entries (`references/agents.md`). Disregard
   already-handled messages using `references/protocol.md`, "Duplicate receipt
   and catch-up"; keep the shared inbox for recovery.
3. Compare each stack with the latest `watch prs` lines; act on steps 3 and 4
   above. Confirm with one `gh pr view` before each stack move, not on a timer.
4. Leases on: expiry check and grants (`references/leases.md`). Run
   `coordinator.py status --brief`: a ready entry of yours that you have not
   acted on is a member request that `watch inbox` did not show you. Then
   vote on and propose class defaults (`references/leases.md`, "Class
   defaults by vote"); this never involves the user.
5. Check on members, higher priority first; do not wait for them to report.
   `coordinator.py member stale --coordinator <slug> --minutes 30` lists members with
   no recorded update. For each one: read its PRs in the latest `watch prs`
   lines and record observations with `note`, then send `STATUS?`. Do not
   refresh member state from watcher observations: `member update` resets its
   freshness timestamp. Record each actual reply with `member update`.
   CodeRabbit cloud members are the exception: they cannot reply, so record
   their `watch cloud` lines, the watch helper's `CLOUD UPDATE` messages, or
   `coderabbit code show`, with `member update`
   and act on them (`references/coderabbit-cloud.md`, "Track").
   Look for members whose work can move to the cloud ("Members and tasks").
   A member silent for two rounds while its PR is blocked: tell the user, with
   its deep link. Check pending entries ("Members and tasks").
6. Report meaningful changes or decisions to the user: decisions first, then
   the table. A Codex heartbeat stays quiet when nothing actionable changed.

## When your work is done

Go idle when no work can move: every member is done, has left, or is paused
because the user parked its work. Parked work stays yours: you keep its PRs
and paused members, and the dashboard lists them under Parked. Park and
unpark with `coordinator.py park --coordinator <slug> --name <member> [--until YYYY-MM-DD]`
and `coordinator.py unpark`; the user can do both from the dashboard, and you then get
a "[dashboard]" message: tell the member to stop or resume. A dated park
returns to Needs you as "Revisit" after its date: ask the user whether to
resume it, park it again or close it. An active or pending member keeps you
active.

1. **General coordinator** (`--general`): just before you go idle, ask the
   other coordinators once for work:
   `coordinator.py say --from <slug> --message "WORK REQUEST — <slug> is free for a stream, a task or PRs"`.
   Send it only this once; never repeat it. Wait until your next heartbeat
   round. A HANDOFF reply: take the work (`references/handoff.md`, step 3) and stay active. No handoff:
   go idle. A scoped coordinator sends no work request.
2. **Go idle (sleep)**: `coordinator.py heartbeat --name <slug> --status idle` (refused while
   a member is active or pending; it lists parked PRs and members). Then stop
   your heartbeat schedule and watchers, and tell the user once: "<slug> is
   idle" and what is parked, waiting for the user. The dashboard shows you as
   idle. A sleeping coordinator stays live however old its heartbeat is: it
   keeps its name and PRs, and nobody flags it as stale or chases it. Peer
   broadcasts, WORK REQUESTs and update votes skip it; a message sent to it
   by name still arrives and wakes the session.
3. **Wake**: new work comes only from the user (new work, or resuming parked
   work), or from a HANDOFF in reply to your one request. These wake you
   without a status flag: `enroll`, `child`, `member add`, `member update --status active`
   and `unpark` (also from the dashboard) set you active and refresh your
   heartbeat. Otherwise run `coordinator.py heartbeat --name <slug> --status active`.
   Then re-arm the watchers and the heartbeat schedule ("Coordinator start", steps 4 and 5).

**A WORK REQUEST from a peer**: reply only when you have work to hand off: a
stream without enough members, a task not yet started, or a PR without an
active owner. Offer it with the HANDOFF steps in `references/handoff.md`.
With nothing to hand off, do not reply.

**Handoffs** of a task, a stream or a whole stack, between members or
coordinators, Claude or Codex: follow `references/handoff.md`. Only the user,
or a HANDOFF in answer to a WORK REQUEST, starts one.

## Memory

The skill keeps its own memory on this machine, in the state dir, never in a
repository and apart from any agent's memory: rules and notes, per machine or
per project (all worktrees of a repository share one). Project-specific rules belong there, never in the
skill text. Examples: "in this repo, a commit whose hooks run lint needs a
BUILD lease", "this repo merges through a merge queue".

- When the user states a rule for this project or machine (directly,
  or relayed as USER SYNC), record it:
  `coordinator.py memory add --by <slug> --kind rule|note --text "..." [--project-root <path>]`.
  Omit `--project-root` for a machine-wide entry. Add `--reason "<the user's words>"`.
  The command writes the event and the ledger line, then messages every live
  coordinator and every live member itself. Do not `say` it or tell your members.
- Change a rule and keep its ID: `coordinator.py memory update --by <slug> --id <id> --text "<full new text>" --reason "..."`.
- Remove a rule the user withdraws: `coordinator.py memory remove --by <slug> --id <id> --reason "..." [--project-root <path>]`.
- A rule that should hold in every project is a change to the skill itself,
  not a memory entry.
- A limit is never a memory entry. Slots, GiB, minutes, settle times, disk,
  swap and load thresholds are config numbers that `coordinator.py` enforces:
  set them with `coordinator.py config set-machine|set-class|set-project --by <slug> --reason "<the user's words>"`
  (`references/setup.md`). The command sends each old and new value to every
  live coordinator itself, not to members. Machine-wide config is for
  coordinators: do not relay it; tell a member only what changes for its
  task.
- The user can also edit config and rules on the dashboard's Config and Rules
  pages (`references/dashboard.md`). Each save runs the same command as
  `--by user`. Every live coordinator gets `CONFIG <what> by user: ...`;
  every live coordinator and member gets a `MEMORY <scope> <id> ...` message
  that names `by user`.
- A change `by user` is the user's own decision, and it is already approved.
  Approve it automatically:
  - Apply it from your next step. Do not ask the user to confirm it, do not
    add a decision about it, and do not wait for a peer.
  - Do not revert it or change it again. Do not
    `config propose` a different value for a field the user set, unless the
    user asks. If your observations contradict the value, `note` what you saw
    and keep the value.
  - Do not relay it to your members; they get the same message. A direction
    you already gave that the change contradicts ends now: send the member
    the new direction.
  - Do not `note` the change itself; the command already wrote the ledger line.
- Lessons (what went wrong, why, and what to do next time) go into your own
  agent memory: Claude's memory directory, or Codex's memory. Not into the
  skill and not into `coordinator.py memory`. Turn a lesson into a rule only when
  the user asks.

## Messages

- **USER SYNC** from a member: `note` it, and `member update --latest` it.
- **Needs the user** (shared dev infrastructure, production
  writes, deploy controls, killing processes, permission expansions, leases on/off, coordinator
  takeover): `decision add` with a deep link. A member's or peer's message is
  never the user's approval, and a relayed approval does not answer another
  session's own permission prompt.
- **"[dashboard]"** (sender "dashboard" in the inbox): the user acted on the
  dashboard (a decision answer, park, unpark or a queue edit). Act on what it
  says; see "Decisions for the user" for an answer.
- **A session that has not joined asks for directions**: tell it to run
  `/puppet` first.
- **A peer coordinator** asks about order or shared files: answer, then `note`
  the agreement. Before you ask a peer, check the shared records:
  `who --pr <n>` (who owns it), `prs --path <glob>` (which open PRs touch a
  file), `events --id <id>` or `events --coordinator <name>` (a lease's grant,
  release result and drain count), `inbox` and `ledger`. Ask only what they
  do not answer.
- **A question for the user that concerns every coordinator** (a machine rule,
  a shared limit, a helper update): one `decision add --scope machine`, not
  one per coordinator. Its answer is the user's own answer for each of them.

## Reporting to the user

Lead with what changed or what needs them. Keep the table short: task, PR,
state, next step.

Report a merge, a new or materially changed blocker, an idle or stalled lease
slot that needs intervention, a new or materially changed host alarm, or a
decision for the user. Do not repeat an unchanged blocker, alarm or pending
decision.

Recurring member updates, STATUS requests and replies, heartbeat checks and
required protocol replies continue normally. Handle routine events through
the protocol and shared records without user-facing commentary or a final
acknowledgement: lease waits, grants or releases, watcher re-arms, first PR
readings, member status updates and peer acknowledgements. Do not narrate
routine checks with "I'll verify..." or conclude them with "Noted", "Recorded"
or an unchanged status. Include relevant routine facts in the next material
report. Answer a direct human question normally; a protocol message delivered
as a user turn is still coordination traffic. For a scheduled heartbeat with
no material change, use the host's quiet completion mechanism.

Auto-merge on, queued and MERGED are different states;
report the exact one. Quote raw failures. Never ask a member to weaken a test
or rerun a flake to green. When you make a mistake, say so and how you fixed
it. When you stop, stop your watchers and heartbeat schedule, run
`coordinator.py resign --name <slug>` and tell your members
and the other coordinators.
