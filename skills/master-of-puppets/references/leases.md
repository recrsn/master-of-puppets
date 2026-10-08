# Leases (optional)

Leases make sessions take turns on shared actions: heavy jobs, or anything only
one session may use at a time. They are machine-wide:
every coordinator shares the same queues. They are off by default. Turn them on
only on the user's word: `lease.py leases on --by <slug>`. Then send the lease
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
`lease.py config set-class <NAME> --description "..." --default-gib <n> --max-minutes <n> [--settle OTHER=<s>]`,
and cap it with `config set-machine --max-slots <NAME>=<n>`. A class with
`--default-gib 0` uses no memory budget, so only its slot cap limits it. That
fits a single resource: one Chrome window for E2E screenshots
(`BROWSER`, 0 GiB, 1 slot), a shared tunnel, a test database, a device.
`--settle OTHER=<s>` makes OTHER wait `<s>` seconds after each grant of this
class. `config remove-class <NAME>` is refused while the class has holders or
queue entries. Add classes only on the user's word, then tell the other
coordinators and your members.

**No lease**: a plain dependency install, git hooks (never skip them), source
edits, reading code, browser-only work against remote sites, unless a class
covers it.

Maximum length: `maxMinutesEffective` per class from `lease.py config show`. Every release records the run minutes;
in learn mode the limit adapts to p90 of the last 10 runs + 25%, capped by
the configured maximum, and queue ETAs use the median run. Split a longer
request: the first part keeps the queue place, later parts join the back.

## Adaptive capacity

There is no fixed slot count. `lease.py` admits a grant when the expected peak
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
  `lease.py measure-peak --id <id> --worktree <worktree>` in the background. It sums the RSS
  of processes whose working directory is in the worktree, writes the running
  peak to `peaks/<id>.gib`, and exits after release. `release` records it.
  RSS counts shared pages twice, so the figure errs high. Processes that run
  elsewhere (a browser, a shared daemon) are not counted; pass `--peak-gib`
  by hand when you know better.
- Settings come from the first-run setup (`references/setup.md`): the memory
  reserve and optional slot caps per machine
  (`lease.py config set-machine --reserve-gib <n> --max-slots BUILD=<n>`), and
  per project the peak mode, starting GiB and max minutes
  (`lease.py config set-project --root <path> --class BUILD --peak learn --default-gib <n> --max-minutes <n>`).
  In fixed mode, samples are still recorded but not used.
- `lease.py capacity` prints the budget, the class peaks and how many of each
  class fit now. The dashboard shows the same numbers.

Example: on a 24 GiB machine with a 6 GiB reserve, a 10 GiB build and an 8 GiB
stack fill the 18 GiB budget, so the result is one of each. A 64 GiB machine
admits more without a change.

The memory budget predicts; the host check observes. Both must pass.

## Granting

1. Record the request under the id the member proposed (it is already waiting
   on it, for up to 10 minutes): `lease.py wait <CLASS> --coordinator <slug> --holder "<task> <what>" --id <member's id> --minutes <est> --commands "<exact commands>" --worktree <path> [--gib <n>]`.
   To change an entry later, pass only `--id` and the fields that change.
   Start `--holder` with the task id (the dashboard matches on it). Reply
   LEASE QUEUED with the position.
2. When that entry is the first ready one, run `lease.py host-check` **as
   its own step** and read the verdict. Never chain it with `acquire`: you
   will grant on a BUSY reading.
3. BUSY: do not grant. Start `lease.py calm-wait` in the background (`--settle <s>` while a stack starts), tell
   the member it waits for host pressure, and grant on CALM.
4. CALM: `lease.py acquire ... --measure`. `--measure` starts `measure-peak`
   for the lease; the granted commands come from the queue entry (or
   `--commands`) and show in `status --brief` and on the dashboard. Exit 3 with
   `settling` means another class's grant settles this one (for example BUILD
   for 60 s after an E2E grant): keep it queued and retry after that time. Exit 4 means the
   request does not fit the memory budget: keep it queued and wait for a
   release. Exit 0: send LEASE GRANTED with the lease id, the recorded
   commands, expiry and release command.
5. On release: confirm with `lease.py status --brief` and `note` the result.
   After an E2E release, run
   `lease.py drain-check --worktree <path> [--port <n> ...] [--ngrok]`; grant
   the next E2E only when it exits 0, else ask the holder to stop what is left.
   If the next head belongs to another coordinator, tell it the slot is free.
6. A member running commands outside the recorded scope breaks "use it or
   return it": ask it to release at once.

Strict FIFO per class: only the first ready entry may acquire, whoever owns
it. No coordinator jumps the queue.

## Rules members get wrong

- **Use it or return it.** A lease covers only the granted commands. No edits
  or repairs while holding it. On a failure: release at once with the raw
  failure, repair without a lease, queue again at the back.
- **Expired is not free.** An expired lease still holds its memory. Ask its
  holder. If the holder is gone, check for its processes and ask the user
  before a takeover. Never kill a process yourself.
- **Front of queue** (`wait --front`) only for a run you aborted yourself,
  for example a grant you made by mistake.
- **Held entries** (`hold`) keep their place but are skipped. Use it for a
  member that is paused or waits for the user.
- **Stack start.** Starting a full local stack is often the heaviest event on
  the machine. `acquire` refuses BUILD for E2E's settle time after an E2E grant
  (`config set-class E2E --settle BUILD=<s>`, 0 removes it); then trust the
  host check.

## Host check thresholds

Calm means swap-outs below `maxSwapouts` per `swapIntervalS` in two samples,
and a 1-minute load below cores × `loadPerCore` (defaults 200 per 12 s and
2.5 × cores; `MAX_SWAPOUTS`, `MAX_LOAD`, `INTERVAL` override them). A single memory reading is not enough. Thresholds come from the machine config. Disk floor: when the check prints
`disk_low=yes`, stop BUILD grants and propose removing unused
worktrees. Remove one only with the user's approval, with
`git worktree remove` (no force), and only when it is clean and unused.
