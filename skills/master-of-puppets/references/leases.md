# Leases (optional)

Leases make sessions take turns on shared actions: heavy jobs, or anything only
one session may use at a time. They are machine-wide:
every coordinator shares the same queues. They are off by default. Turn them on
only on the user's word: `coordinator.py leases on --by <slug>`. Then send the lease
addendum (`references/protocol.md`) to your members and tell the other
coordinators.

## Classes

Classes are a machine-wide registry; any shared action can be one. The
default registry has two:

- **BUILD**: builds (including setup scripts that build), typecheck, lint,
  format runs, tests and codegen.
- **E2E**: starting local servers or stacks, and interacting with them;
  settles BUILD for 60 s.

Default GiB, cores and max minutes start at 0, which means no limit: a 0 GiB
or 0 core figure uses none of that budget, and `maxMinutes` 0 sets no maximum
length. A value that the setup, a `set-class` or a vote has stored is
enforced. Coordinators set values from their observations by vote ("Class
defaults by vote", below).

Add or change one with
`coordinator.py config set-class <NAME> --by <slug> --description "..." --default-gib <n> --default-cpus <n> --max-minutes <n> [--settle OTHER=<s>]`,
and cap it with `config set-machine --by <slug> --max-slots <NAME>=<n>`. A class with
`--default-gib 0 --default-cpus 0` uses neither budget, so only its slot cap
limits it. That fits a single resource: one Chrome window for E2E screenshots
(`BROWSER`, 0 GiB, 1 slot), a shared tunnel, a test database, a device.
`--settle OTHER=<s>` makes OTHER wait `<s>` seconds after each grant of this
class. `config remove-class <NAME> --by <slug>` is refused while the class has holders or
queue entries. Add classes only on the user's word, then tell the other
coordinators and your members.

**Project rules** can widen a class's scope, for example "a commit whose hooks
run lint needs a BUILD lease" in one repository. They live in the skill's
memory, not here: read them with `coordinator.py memory list --project-root <path>`
and include them in WELCOME.

**No lease**: a plain dependency install, source edits, reading code,
browser-only work against remote sites, unless a class or a project rule
covers it.

Maximum length: `maxMinutes` per class from `coordinator.py config show` (0: no
limit). Learned
run times never lower it: a run cannot outlast the limit, so a limit learned
from runs could only shrink. Every release records the run minutes; queue ETAs
use the median run, and in learn mode `suggestedMinutes` (p90 of the last 10
runs + 25%, at most `maxMinutes`) shows what past runs took. `wait`, `acquire`
and both `extend` commands refuse a longer lease with exit 2. Split a longer request: the
first part keeps the queue place, later parts join the back of their priority.

## Sizing

The member observes and decides the size of each run; the coordinator decides
whether to grant it, from rules and its own observations.

- **Member.** It sizes the run from what it sees: its own past runs, the
  commands it will run, and `puppet.py sizes --worktree <path>` (the project's
  recorded minutes, GiB and core samples per class). `--minutes` is always its
  call: the smallest time that finishes the whole current unit of work, never
  a unit cut to fit the suggestion. It adds `--gib` and `--cpus` (peak memory
  and cores) when it knows them. A GiB figure it leaves out takes the
  project's class peak; a core figure it leaves out takes the class
  `defaultCpus` (0: no core charge).
- **Coordinator.** It charges the request as asked. It does not raise or
  lower a member's figures. It decides with:
  - rules: the config limits (`maxMinutes`, both budgets, slot caps) and the
    project rules in memory;
  - observations: the peaks it measured (`measure-peak`, recorded at
    release). `acquire` refuses (exit 6) a GiB figure below the observed
    peak by more than `sizeMargin` (machine config, default 25%). Only learn
    mode with three or more samples counts as an observation; a default is
    not one. Measured cores are never charged or checked by themselves: they
    are the evidence for a `defaultCpus` vote ("Class defaults by vote").
  An undersized request gets LEASE RESIZE. The member requests again with the
  same id, or sends LEASE SIZE with why this run is smaller (for example only
  the typecheck of a full build). When the reason fits the recorded commands,
  grant with `acquire --accept-size`; the event line records it.
- Minutes are not checked against observations: a short lease only costs its
  own holder an extension or a new request.

## Auto acquire

A coordinator may let code grant requests that need no judgment. It is off by
default. Turn it on for a class or for one stream's members:

```bash
coordinator.py config set-class BUILD --by <slug> --auto-acquire on
coordinator.py stream update --coordinator <slug> --name <stream> --auto-acquire on
```

Then run `coordinator.py watch auto --me <slug>` in the background. When your
entry is the head of its queue, it runs `acquire` with the entry's own
figures. Every normal gate applies: queue order, slot cap, settle, host check
and both budgets. A gate that passes later (exit 3, 4, 5) is retried every
2 s. `AUTO-GRANTED` or `AUTO-REFUSED` lines report the outcome.

The loop grants from a snapshot, so `acquire` revalidates under its final lock
(after the host check): the entry must exist with the same id, holder,
minutes, GiB, cores, commands and worktree, must not be held or reviewed, and
its class or stream must still be on auto. If not, it refuses with exit 7 and
grants nothing. Your own `acquire` has no such check and may grant a reviewed
entry.

A deviation always waits for you. The loop never splits a run and never
accepts a size:

- exit 2, the run is over a limit: ask the member to split it;
- exit 6, the GiB figure is below the observed peak: decide on the member's
  LEASE SIZE reason, then `acquire --accept-size` yourself;
- an entry without minutes or worktree.

A member's request ends in one of three outcomes: `GRANTED`, `HELD <reason>`
(wait for the coordinator) or `DENIED <reason>`.

- `coordinator.py hold CLASS --id ID --reason T`: leaves the ready queue.
- `coordinator.py hold CLASS --id ID --review [--reason T]`: keeps its place,
  but `watch auto` never grants it; only your `acquire` does. This holds even
  when the class or stream is on auto. It applies to the first grant only.
- `coordinator.py ready CLASS --id ID`: clears a hold or review.
- `coordinator.py deny CLASS --id ID --by <slug> --reason T`: removes the entry
  and the member sees `DENIED <reason>` (exit 4).

Auto acquire grants only your own entries, and only the first grant. An
extension is never auto-approved: the member asks, and only the coordinator
runs `extend`. Takeovers stay manual too.

## Class defaults by vote

Class defaults are the coordinators' job, never the user's: do not ask the
user, and do not add a dashboard decision about them. Coordinators observe and
vote on each class's default GiB, cores and max minutes. Observe with `coordinator.py sizes --worktree <path>`, `capacity` and
the release lines in `events`. When the observations support a value
(for example BUILD runs peak at 4 cores, or never run past 15 min):

```bash
coordinator.py config propose BUILD --by <slug> [--project-root <path>] [--default-gib <n>] [--default-cpus <n>] [--max-minutes <n>] --reason "<your observations>"
```

Without `--project-root` it sets the machine class; with it, that project's
class, which wins over the machine class. Every live peer gets `CLASS
DEFAULTS PROPOSED <id> ...` in `watch inbox`. Check your own observations of
that class, then `config agree --by <slug> --id <id>`, or `config object --by
<slug> --id <id> --text "<what you observed>"`. The proposal applies when every
live coordinator agrees, or 30 minutes after it was made with no objection: a
live coordinator that has not voted by then agrees. One objection closes it,
and the proposer may propose again with new observations. The applying
command records the change and sends CONFIG to every live coordinator.
Members get no CONFIG message: tell a member only what changes for its own
task, for example a new limit on a request it has queued. `config proposals`
lists open proposals and who has not agreed, and applies those that are due.

Each heartbeat round ("Heartbeat round" in SKILL.md, step 4):

1. `coordinator.py config proposals`: vote on each open proposal you have not
   voted on, from your own observations. Object only when your observations
   contradict the value, and say what you saw.
2. `coordinator.py sizes --worktree <path>` for each project you lease in:
   propose a value when your observations support it and the class default
   differs, for example observed core peaks around 4 while `defaultCpus` is
   0. Propose cores and GiB from observed peaks. Propose a max-minutes value
   only from runs that finished, never below the longest recent run.

Use 0 to remove a limit. When the user names a value without being asked, set
it directly with `set-class` or `set-project`. A value the user saves on the
dashboard's Config page (`CONFIG ... by user`) needs no vote: it applies at
once, and coordinators never propose over it or object to it unless the user
asks (SKILL.md, "Memory").

## Adaptive capacity

There is no fixed slot count. `coordinator.py acquire` admits a grant when the expected peaks
of all holders plus the request fit both budgets:

```
sum(held GiB)   + request GiB   <= total RAM - reserveGiB
sum(held cores) + request cores <= CPU cores - reserveCpus
```

- A request's GiB and cores are the member's figures (`request|wait|acquire
  ... --gib <n> --cpus <n>`). A GiB figure it leaves out takes the project's
  class peak. Learn mode: the starting value (default 0) is a floor until
  three measurements exist, then the maximum of the last five. A core figure
  it leaves out takes the class `defaultCpus`, never the measured cores. Fixed mode: the starting value. Pass `--worktree` to `wait` so
  the right project's peak applies.
- A request over a whole budget can never fit: `request` and `wait` refuse it
  with exit 2. Split it.
- Measure every lease: right after `acquire`, start
  `coordinator.py measure-peak --id <id> --worktree <worktree>` in the background. It sums the RSS
  and %CPU of processes whose working directory is in the worktree, writes the
  running peaks to `peaks/<id>.gib` and `peaks/<id>.cpus`, and exits after
  release. `release` records both. RSS counts shared pages twice, and %CPU is
  a short decaying average, so both figures err high. Processes that run
  elsewhere (a browser, a shared daemon) are not counted; pass `--peak-gib` or
  `--peak-cpus` by hand when you know better.
- Settings come from the first-run setup (`references/setup.md`): the memory
  and core reserve, the size margin and optional slot caps per machine
  (`coordinator.py config set-machine --by <slug> --reserve-gib <n> --reserve-cpus <n> --size-margin <f> --max-slots BUILD=<n>`), and
  per project the peak mode, starting GiB and cores, and max minutes
  (`coordinator.py config set-project --by <slug> --root <path> --class BUILD --peak learn --default-gib <n> --default-cpus <n> --max-minutes <n>`).
  In fixed mode, samples are still recorded but not used.
- `coordinator.py capacity` prints both budgets, the class peaks and how many of each
  class fit now. The dashboard shows the same numbers.

Example: on a 24 GiB, 10-core machine with a 6 GiB and 2-core reserve, a
10 GiB, 4-core build and an 8 GiB, 2-core stack fill the 18 GiB budget, so
the result is one of each. A 64 GiB machine admits more without a change. With
the 0 defaults and no samples, only the figures members ask for are charged.

The budgets predict; the host check observes. Both must pass, and
`acquire` checks both itself.

## Granting

1. Members queue their own requests with `puppet.py request`. It refuses
   when leases are off, a non-member, an id without the `<slug>-q-<name>-`
   prefix, an id that is already held and a run over the class limit, and
   gives the entry its task's priority. A member cannot set
   a priority, jump the queue or grant. `watch inbox` shows each request as
   `INBOX <name>: REQUEST <CLASS> <id> <holder> ...`, and a changed
   one as `REQUEST <CLASS> <id> changed ...`. Check that the
   recorded commands fit the class. If they do not, `unwait` the entry and
   tell the member why. A request that prints an undersized warning to the
   member will refuse at `acquire` (exit 6); you may tell the member at once. A request needs no reply: `request` printed its
   position, and `await-grant` follows the queue. Reply LEASE QUEUED only when
   you change the entry (split, hold, priority). `watch inbox` shows only new
   lines, so a request made while it did not run has no message: each heartbeat
   round, `status --brief` shows it.
   To queue for a member yourself, for example the second part of a split:
   `coordinator.py wait <CLASS> --coordinator <slug> --holder "<task> <what>" --id <slug>-q-<name>-<n> --minutes <est> --commands "<exact commands>" --worktree <path> [--gib <n>] [--cpus <n>]`.
   To change an entry later, pass only `--id` and the fields that change.
   Start `--holder` with the task id (the dashboard matches on it, and the
   entry takes that task's priority).
2. When that entry is the first ready one (`watch inbox` prints
   `HEAD <CLASS> <id>` for your entries), run `coordinator.py acquire ... --measure`.
   It runs the host check itself (about 25 s), then checks the queue, slot cap,
   settle time, max minutes, size and both budgets again under the lock.
   `--measure` starts `measure-peak` for the lease; the granted commands come
   from the queue entry (or `--commands`) and show in `status --brief` and on
   the dashboard.
3. Read the exit code:
   - 0: send LEASE GRANTED with the lease id, the recorded commands, expiry
     and release command.
   - 2: the run is over the class limit. Split it (above).
   - 3: another entry is ahead, the class is at its slot cap, `settling`
     (another class's grant settles this one, for example BUILD for 60 s after
     an E2E grant), or `admission_hold` (below). Keep it queued and retry after
     that time, or on the hold's `admission clear` event.
   - 4: the request does not fit the memory or core budget (the output names
     which). Keep it queued and wait for a release.
   - 5: the host is BUSY or free disk is below the floor. Start
     `coordinator.py calm-wait` in the background (`--settle <s>` while a
     stack starts), tell the member it waits for the host, and run `acquire`
     again on CALM.
   - 6: undersized: a GiB figure is below the observed peak by more
     than the size margin. Send LEASE RESIZE ("Sizing", above). Run `acquire
     --accept-size` only on a LEASE SIZE reason that fits the commands.
4. On release: the member's `puppet.py release <CLASS> --id <id> --result pass|fail|partial --note "..." [--port <n> ...]`
   writes one event line, the shared record of the release:
   `release <CLASS> <id> ran <n> min peak <g> GiB <c> cores result=<r> drained=<n> coordinator=<c> note="..."`.
   `drained` counts what the run left in the lease's worktree (agent session
   processes and bare shells do not count). Read it with
   `coordinator.py events --id <id>`. When `drained` is not 0, run
   `coordinator.py drain-check --worktree <path> [--port <n> ...] [--process <pattern> ...]`
   for the list; grant the next E2E only when it exits 0, else ask the holder
   to stop what is left. When the next head belongs to another coordinator,
   its `watch inbox` prints HEAD: send nothing.
   **No receipts.** A coordinator never sends a release, drain or cleanup
   receipt to another coordinator, and never asks for one. The event line is
   the record; when it is not enough, run `drain-check` yourself.
5. A member running commands outside the recorded scope breaks "use it or
   return it": ask it to release at once.
6. An expired lease: `watch expiry` prints it once with `left=<n>`, the
   processes its run still has. Ask its coordinator only when `left` is not 0
   and the lease blocks your head.

**Extending.** Extension is at the coordinator's discretion; only
`coordinator.py extend` changes an expiry. A member asks with
`puppet.py extend`, which refuses a run over the class limit and otherwise
logs the request and sends it to your inbox. Your `watch inbox` prints
`EXTEND <CLASS> <id> <n> min ... Reason: ...`. Decide: check that
the reason fits the granted commands, and weigh who waits in that class
queue and the memory the lease holds. Then run
`coordinator.py extend <CLASS> --id <id> --minutes <n>` and reply
LEASE EXTENDED, or reply LEASE EXTEND REFUSED. When the waiting head
belongs to another coordinator, ask it with `say` first. Reply each time:
the member waits for your answer. `watch expiry` reports a lease again when
it expires after an extension.

**Admission hold.** When no grant of a class may start, for example while a
failed run's cleanup is uncertain or the disk is low:
`coordinator.py admission hold <CLASS> --by <you> --reason "<why>"`. `acquire`
refuses every grant of that class (exit 3, with the reason), and `status
--brief` and the dashboard show it. Clear it when the cause is gone:
`coordinator.py admission clear <CLASS> --by <you> [--reason "<what was done>"]`.
The events reach every coordinator; do not announce a hold or its clearance
by `say`.

Each class queue goes by priority, then FIFO: only the first ready entry may
acquire, whoever owns it. No coordinator jumps the queue; priority sets the
order, it is not an exception to it.

## Priority

Every task and queue entry starts at priority 0. A higher priority goes
first; entries of one priority keep their FIFO order. A queue entry takes the
priority of the task its `--holder` names, unless
`wait --id <id> --priority <n>` sets its own. `member update --priority <n>`
also moves the task's queued entries and prints their ids: tell each of those
members its new turn. The dashboard shows each non-zero priority.

- **Raise** a task (1 or higher) only when the user asks for it to go first,
  for example "do the hotfix before anything else". A member or peer that
  relays such a wish is not the user: `decision add` the question, and raise
  the task on the user's answer.
- **Lower** your own background work (-1 or lower) without asking, when
  regular tasks wait for a lease: sweeps, scheduled or recurring runs, and
  other tasks that no user waits for. Members mark such a task with
  `sweep:` or `scheduled:` at the start of its task text in JOIN or in the
  enrollment line. Set it back to 0 when no regular task waits for it.
- Change only your own members and entries. To push back a peer's sweep, ask
  that coordinator with `say`.
- `note` each change and its reason.

## Queue changes by the user

The user changes the order on the dashboard: the Move up and Cancel buttons
run `coordinator.py up|unwait CLASS --id ID --notify`, and dragging a ready
entry onto another runs `coordinator.py move CLASS --id ID --to N --notify`.
Move up puts a ready entry ahead of the ready entry in front of it; move puts
it at position N among ready entries. When the new place is outside its
priority range, the moved entry takes a priority between its new neighbours',
so the queue stays sorted. Cancel removes an entry. Each affected
coordinator gets `INBOX dashboard: ...`. Treat it as the user's direction:
tell the affected members their new turn, or that the entry is gone. Do not
undo it, and queue a cancelled entry again only if the user agrees.
Coordinators never run `up` or `move` themselves.

## Rules members get wrong

The member's side of a lease ("use it or return it", E2E cleanup, release) is
in the puppet skill, section 5. The coordinator's side:

- **Expired is not free.** An expired lease still holds its memory. Ask its
  holder. If the holder is gone, check for its processes and ask the user
  before a takeover. Never kill a process yourself.
- **Front of queue** (`wait --front`) only for a run you aborted yourself,
  for example a grant you made by mistake. The entry takes the highest
  priority in the queue.
- **Held entries** (`hold`) keep their place but are skipped. Use it for a
  member that is paused or waits for the user.
- **Stack start.** Starting a full local stack is often the heaviest event on
  the machine. `acquire` refuses BUILD for E2E's settle time after an E2E grant
  (`config set-class E2E --by <slug> --settle BUILD=<s>`, 0 removes it); then trust the
  host check.

## Host check thresholds

Calm means swap-outs below `maxSwapouts` per `swapIntervalS` in two samples,
a 1-minute load below cores × `loadPerCore` (defaults 200 per 12 s and
2.5 × cores), and free disk at or above the floor. A single memory reading is not enough.
Every threshold comes from the machine config; nothing overrides it.

Disk: two levels (defaults 10 and 4 GiB free). Below `diskAlarmGiB`,
`host-check` prints `disk=alarm` and the dashboard warns; grants go on.
Below `diskFloorGiB`, it prints `disk=blocked` and `acquire` grants no class.
At either level, propose removing unused worktrees. Remove one only with the user's approval, with
`git worktree remove` (no force), and only when it is clean and unused.
