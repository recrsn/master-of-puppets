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
  format runs, tests and codegen. 10 GiB, 20 min.
- **E2E**: starting local servers or stacks, and interacting with them. 8 GiB,
  45 min; settles BUILD for 60 s.

Add or change one with
`coordinator.py config set-class <NAME> --by <slug> --description "..." --default-gib <n> --max-minutes <n> [--settle OTHER=<s>]`,
and cap it with `config set-machine --by <slug> --max-slots <NAME>=<n>`. A class with
`--default-gib 0` uses no memory budget, so only its slot cap limits it. That
fits a single resource: one Chrome window for E2E screenshots
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

Maximum length: `maxMinutesEffective` per class from `coordinator.py config show`. Every release records the run minutes;
in learn mode the limit adapts to p90 of the last 10 runs + 25%, capped by
the configured maximum, and queue ETAs use the median run. `wait`, `acquire`
and `extend` refuse a longer lease with exit 2. Split a longer request: the
first part keeps the queue place, later parts join the back of their priority.

## Adaptive capacity

There is no fixed slot count. `coordinator.py acquire` admits a grant when the expected peak
memory of all holders plus the request fits the budget:

```
sum(held GiB) + request GiB <= total RAM - reserve
```

- Each project and class has a peak. Learn mode: the starting value (defaults
  BUILD 10, E2E 8 GiB) until three measurements exist, then the maximum of
  the last five. Fixed mode: the starting value. Pass `--worktree` to `wait`
  so the right project's peak applies.
- A request may carry its own estimate: `wait|acquire ... --gib <n>`.
- Measure every lease: right after `acquire`, start
  `coordinator.py measure-peak --id <id> --worktree <worktree>` in the background. It sums the RSS
  of processes whose working directory is in the worktree, writes the running
  peak to `peaks/<id>.gib`, and exits after release. `release` records it.
  RSS counts shared pages twice, so the figure errs high. Processes that run
  elsewhere (a browser, a shared daemon) are not counted; pass `--peak-gib`
  by hand when you know better.
- Settings come from the first-run setup (`references/setup.md`): the memory
  reserve and optional slot caps per machine
  (`coordinator.py config set-machine --by <slug> --reserve-gib <n> --max-slots BUILD=<n>`), and
  per project the peak mode, starting GiB and max minutes
  (`coordinator.py config set-project --by <slug> --root <path> --class BUILD --peak learn --default-gib <n> --max-minutes <n>`).
  In fixed mode, samples are still recorded but not used.
- `coordinator.py capacity` prints the budget, the class peaks and how many of each
  class fit now. The dashboard shows the same numbers.

Example: on a 24 GiB machine with a 6 GiB reserve, a 10 GiB build and an 8 GiB
stack fill the 18 GiB budget, so the result is one of each. A 64 GiB machine
admits more without a change.

The memory budget predicts; the host check observes. Both must pass, and
`acquire` checks both itself.

## Granting

1. Members queue their own requests with `puppet.py request`. It refuses
   when leases are off, a non-member, an id without the `<slug>-q-<name>-`
   prefix, an id that is already held and a run over the class limit, and
   gives the entry its task's priority. A member cannot set
   a priority, jump the queue or grant. `watch inbox` shows each request as
   `EVENT ... request <CLASS> <slug> <id> <holder> by=<name>`, and a changed
   one as `... request <CLASS> <slug> <id> changed ...`. Check that the
   recorded commands fit the class. If they do not, `unwait` the entry and
   tell the member why. A request needs no reply: `request` printed its
   position, and `await-grant` follows the queue. Reply LEASE QUEUED only when
   you change the entry (split, hold, priority). `watch inbox` shows only new
   lines, so a request made while it did not run has no event: each heartbeat
   round, `status --brief` shows it.
   To queue for a member yourself, for example the second part of a split:
   `coordinator.py wait <CLASS> --coordinator <slug> --holder "<task> <what>" --id <slug>-q-<name>-<n> --minutes <est> --commands "<exact commands>" --worktree <path> [--gib <n>]`.
   To change an entry later, pass only `--id` and the fields that change.
   Start `--holder` with the task id (the dashboard matches on it, and the
   entry takes that task's priority).
2. When that entry is the first ready one (`watch inbox` prints
   `HEAD <CLASS> <id>` for your entries), run `coordinator.py acquire ... --measure`.
   It runs the host check itself (about 25 s), then checks the queue, slot cap,
   settle time, max minutes and memory budget again under the lock.
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
   - 4: the request does not fit the memory budget. Keep it queued and wait
     for a release.
   - 5: the host is BUSY or free disk is below the floor. Start
     `coordinator.py calm-wait` in the background (`--settle <s>` while a
     stack starts), tell the member it waits for the host, and run `acquire`
     again on CALM.
4. On release: the member's `puppet.py release <CLASS> --id <id> --result pass|fail|partial --note "..." [--port <n> ...]`
   writes one event line, the shared record of the release:
   `release <CLASS> <id> ran <n> min result=<r> drained=<n> coordinator=<c> note="..."`.
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
run `coordinator.py up|unwait CLASS --id ID --notify`. Move up puts a ready entry
ahead of the ready entry in front of it; when that entry has a higher
priority, the moved entry takes it. Cancel removes an entry. Each affected
coordinator gets `INBOX dashboard: ...`. Treat it as the user's direction:
tell the affected members their new turn, or that the entry is gone. Do not
undo it, and queue a cancelled entry again only if the user agrees.
Coordinators never run `up` themselves.

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
