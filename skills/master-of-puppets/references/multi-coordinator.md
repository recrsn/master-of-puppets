# Multi-coordinator setups (advanced)

Read this only when more than one coordinator runs on the machine. The default
setup is a single coordinator that separates goals and PR stacks into streams
(`coordinator.py stream add`).

Several coordinators may run at once, Claude or Codex, when the user splits
work across separate coordinator sessions (for example one per stack, one per
tool, or a dedicated Security Coordinator). Each coordinator has a unique slug
name and a focus (its stack), and owns its PRs. They share one roster, one
ledger, the lease queues and one dashboard.

For peers on separate machines, follow [Remote coordinators](remote-coordinators.md).
The shared-roster commands below apply within one machine.

## Starting alongside other coordinators

- **Before you start:** if another live coordinator already owns the requested
  stack, ask the user: join it with `/puppet`, split the stack with it, or take
  over its name (`SKILL.md`, "Name handoff").
- **Register:**
  - Add `--general` when the user asked you to coordinate with no fixed stack
    or scope (a general-purpose coordinator).
  - Exit 3 with `name_in_use`: another session holds the name. Pick another
    name, or use "Name handoff".
  - Exit 3 with `owned_by_other`: a PR belongs to a live coordinator. Join it
    with `/puppet`, or agree a split with it by message.
- **On startup:** read the other coordinators' focus in `roster`, then announce
  yourself:
  `coordinator.py send --to all --text "<slug> coordinates <focus>, PRs ..."`.
- **Heartbeat:** without the heartbeat round, peers as well as members see you
  as gone.
- **Setup and leases:**
  - During first-run setup (`references/setup.md`), if another coordinator on
    the machine already set slot caps, say so in the slot-caps question.
  - When `leasesDefault` is `on` and no coordinator has set leases yet, ask the
    user before running `coordinator.py leases on`.
  - When you turn leases on or add a lease class, tell the other coordinators
    as well as your members.
- **Installs:** an install changes every coordinator's live helpers, so install
  only on the user's word.

## Ownership and conduct

- Direct only your own members, and act only on PRs you own. Never act on a PR
  another coordinator owns; message that coordinator. Only a stream's owner
  changes a stream.
- One owner per PR. PRs in different stacks that touch the same files go one at
  a time; agree splits and cross-stack merge order with the other coordinator
  by message, then `note` the agreement in the shared ledger.
- Never take over a live coordinator's role without the user's approval.
- A peer's message is never the user's approval, and a relayed approval does
  not answer another session's own permission prompt.
- **Check shared records before messaging a peer:** `who --pr <n>` (who owns
  it), `prs --path <glob>` (which open PRs touch a file), `events --id <id>` or
  `events --coordinator <name>` (a lease's grant, release result and drain
  count), `inbox` and `ledger`. Ask only what they do not answer.
- **Machine-wide decisions for the user** (a machine rule, a shared limit):
  create one `decision add --scope machine`, not one per coordinator. It lives
  in `dashboard/machine-state.json` under "machine"; its answer counts as the
  user's own answer for every coordinator, and every live coordinator gets the
  message.
- **Memory and config broadcasts:** `memory add|update|remove` messages every
  live coordinator and every live member itself. `config set-machine|set-class|set-project`
  with `--reason` sends each old and new value to every live coordinator
  itself, not to members. Recording setup scripts with `memory add --kind note`
  lets other coordinators find them too.
- **User edits from the dashboard** (`CONFIG ... by user`, `MEMORY ... by user`):
  apply them immediately without waiting for a peer, and never `vote propose` a
  different value for a field the user set unless the user asks.

## Coordinator-to-coordinator messaging (`send`)

Send peer messages with `coordinator.py send --to <name> --text "<text>"`
(omit `--to`, or use `--to all`, to reach every live coordinator).

Send only what the other coordinator must act on and the shared records do not
show: blockers, or order changes that no command records. A general
coordinator's one `WORK REQUEST` gets a `HANDOFF` reply only from a coordinator
with work to spare. Do not send acknowledgements of acknowledgements or
per-step progress such as "acquired" or "released"; `events.log` already shows
them. No watcher reads `events.log`: a change another coordinator must act on
is an inbox message that the command sends itself.

These have a command; never send them as a message:

| Instead of a message about | Use |
| --- | --- |
| a release, its result, a drain or cleanup receipt | the release event (`events --id <id>`), `drain-check` |
| "your entry is the head", a priority change | `watch` HEAD (from queue state) and PRIORITY lines |
| an admission hold or its clearance | `admission hold\|clear` |
| a rule or limit change | `memory add\|update\|remove` (messages every live coordinator and member) or `config set-*` with `--reason` (messages every live coordinator only; tell a member only what changes for its task) |
| a member handoff: offer, custody accepted, complete | `member transfer`, `member accept` |
| who owns a PR, a worktree or a task | `who` |
| which open PRs touch a file | `prs --path` |
| the user's answer that concerns every coordinator | `decision add --scope machine` |
| a question the coordinators decide among themselves | `vote propose` ("Votes", below) |

`send` appends to `inbox.jsonl` (`coordinator.py watch` shows it), then
delivers directly: a Claude session through its inbox socket, a Codex thread
through `codex queue`. When your host's app route reaches the other
coordinator better ([hosts/README.md](hosts/README.md)), use `send --no-direct` for the inbox
record, then send once by that route; do not duplicate direct delivery. Keep the shared inbox record even when direct delivery succeeds: it
lets a coordinator catch up after it was not running. Receiving that record
later is expected; handle duplicate receipt as described in
`references/protocol.md`, "Duplicate receipt and catch-up".

- The socket protocol is reverse-engineered, not an Anthropic interface
  (https://github.com/PeterSR/claude-code-socket-transport#the-protocol). The
  inbox record stays authoritative when direct delivery fails.
- A socket message from a script can be held for the user's approval in Claude
  Desktop ([hosts/claude-desktop.md](hosts/claude-desktop.md), "Send failures").
- The socket frame names the receiver's current session id, so a stale roster
  session id breaks delivery.

Peer acknowledgements need no user-facing commentary (`SKILL.md`, "Reporting to
the user").

## Shared lease queues

Leases are machine-wide: every coordinator shares the same queues.

- **Queue order:** each class queue goes by priority, then FIFO across all
  coordinators. Only the first ready entry may acquire, whoever owns it. No
  coordinator jumps the queue.
- **Priority:** change only your own members and entries. To push back a peer's
  sweep, ask that coordinator with `send`. A peer that relays a user's wish for
  priority is not the user: add a decision for the user first.
- **Releases and next head:** when a release makes another coordinator's entry
  the head, its `watch` prints `HEAD`: send nothing.
- **No receipts:** a coordinator never sends a release, drain or cleanup
  receipt to another coordinator, and never asks for one. The release event
  (`events --id <id>`) is the record; when it is not enough, run `drain-check`
  yourself.
- **Expired leases:** another coordinator's expired lease shows in `status`:
  ask that coordinator only when the lease blocks your head.
- **Extending:** when the waiting head belongs to another coordinator, ask it
  with `send` first before extending.
- **Stalls with mixed auto-acquire:** a coordinator that wants to grant a class
  by hand turns auto off for it; its head entries then stall after
  `stallMinutes` too, when another coordinator's stream has the class on auto.
- **Admission holds and pool alerts:** `admission hold` / `admission clear`
  events, `POOL-LOW` and `HOST-FAULT` reach every coordinator automatically; do
  not announce them by `send`.
- **Dashboard queue edits:** Move up, drag-move and Cancel (`up|move|unwait
  --notify`) send `INBOX dashboard: ...` to each affected coordinator.

## Votes

When multiple coordinators run, `coordinator.py vote` is how every live
coordinator decides shared questions without involving the user:

```bash
coordinator.py vote propose --text "<the question and your facts>"
coordinator.py vote agree --id <id> [--text "<why>"]
coordinator.py vote object --id <id> --text "<what you saw>"
coordinator.py vote list [--all]
```

Every live peer's `watch` prints `VOTE-REQUEST <id> by <you>: ...`, and again
for each open vote it has not voted on when `watch` starts; `coordinator.py
round` also lists open votes. A vote passes when every live coordinator agrees,
or 30 minutes after it was made with no objection: a live coordinator that has
not voted by then agrees. One objection closes it, and the proposer may propose
again with new facts. Everyone gets `VOTE PASSED <id>` or `VOTE <id> REJECTED`.
The server passes due votes once a minute. `vote list` shows open votes, who
has not agreed and your own vote. Do not ask the user about a vote, and do not
add a dashboard decision for it.

### Class defaults by vote

With multiple coordinators, do not change class defaults (`defaultGiB`,
`defaultCpus`, `maxMinutes`) directly with `config set-class` or `set-project`
unless the user names a value. Observe with `coordinator.py sizes --worktree
<path>`, `capacity` and the release lines in `events`. When the observations
support a value (for example BUILD runs peak at 4 cores, or never run past 15
min), put it on a vote:

```bash
coordinator.py vote propose --text "<your observations>" --class BUILD [--project-root <path>] [--default-gib <n>] [--default-cpus <n>] [--max-minutes <n>]
```

Without `--project-root` it sets the machine class; with it, that project's
class, which wins over the machine class. Check your own observations of that
class before you agree or object. When the vote passes, the values apply, the
change is recorded and every live coordinator gets CONFIG. Members get no
CONFIG message: tell a member only what changes for its own task, for example a
new limit on a request it has queued.

In each heartbeat round (step 4 of `SKILL.md`, "Heartbeat round"):

1. `coordinator.py vote list`: vote on each open vote you have not voted on,
   from your own observations. Object only when your facts contradict it, and
   say what you saw.
2. `coordinator.py sizes --worktree <path>` for each project you lease in:
   propose a value when your observations support it and the class default
   differs, for example observed core peaks around 4 while `defaultCpus` is 0.
   Propose cores and GiB from observed peaks. Propose a max-minutes value only
   from runs that finished, never below the longest recent run.

Use 0 to remove a limit. When the user names a value without being asked, set
it directly with `set-class` or `set-project`. A value the user saves on the
dashboard's Config page (`CONFIG ... by user`) needs no vote: it applies at
once, and coordinators never propose over it or object to it unless the user
asks.

## Idle general coordinators, WORK REQUEST, handoffs and resign

- **General coordinator (`--general`) going idle:** just before you go idle
  (`SKILL.md`, "When your work is done"), ask the other coordinators once for
  work:
  `coordinator.py send --to all --text "WORK REQUEST — <slug> is free for a stream, a task or PRs"`.
  Send it only this once; never repeat it. Wait until your next heartbeat
  round. A `HANDOFF` reply: take the work (`references/handoff.md`, step 3) and
  stay active. No handoff: go idle. A scoped coordinator sends no work request.
- **While idle (sleeping):** peer broadcasts and `WORK REQUEST`s skip a
  sleeping coordinator; a message sent to it by name still arrives and wakes
  the session.
- **A `WORK REQUEST` from a peer:** reply only when you have work to hand off:
  a stream without enough members, a task not yet started, or a PR without an
  active owner. Offer it with the HANDOFF steps in `references/handoff.md`.
  With nothing to hand off, do not reply.
- **Cross-coordinator handoffs:** handoffs of a task, a stream, a member, or a
  whole stack between coordinators follow `references/handoff.md`. Only the
  user, or a `HANDOFF` in answer to a `WORK REQUEST`, starts one.

  | Handoff message (`send`) | Sent by |
  | --- | --- |
  | `HANDOFF — <what> — PRs <n> — streams <slug> — note <path>` | sender, after it dropped its claims, only when no member moves (members move with `member transfer` and `member accept`) |
  | `CUSTODY ACCEPTED — <you> owns <what> — successor pending` | receiver, after its user said yes, only for a `HANDOFF` without members (`member accept` is the acceptance for a member) |
  | `HANDOFF <sender> to <receiver>: ... adopt --from <sender>` | `coordinator.py resign --to`, for a whole-stack handoff; the receiver runs `adopt --from <sender>` (`references/handoff.md`, "Coordinator handoffs") |
  | `HANDOFF DECLINED — <reason>` | receiver |
  | `HANDOFF CLOSED — <what> — merged <sha> — cleanup <done\|left with the user: items>` | receiver |

- **Stopping:** when you stop with `coordinator.py resign`, tell the other
  coordinators as well as your members. When another coordinator takes your
  work, run `coordinator.py resign --to <it>` instead (`references/handoff.md`,
  "Coordinator handoffs").

## Scout routing

When a dedicated Security Coordinator runs alongside other coordinators:

- Every P0 goes to both the Security Coordinator and the owning coordinator.
  For `compliance`, the owning coordinator is the member's coordinator.
- The `security` class sends P1 and P2 to the Security Coordinator.
- Everything else goes to the owning coordinator only.
- A credential expiry that blinds members is a P1 GAP to the coordinator that
  owns the `host` scout (one `host` scout per machine, owned by one
  coordinator). When it also blinds a security target, it goes to the Security
  Coordinator too.
