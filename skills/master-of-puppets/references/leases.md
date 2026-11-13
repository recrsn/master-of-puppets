# Leases (optional)

Leases make sessions take turns on shared actions: heavy jobs, or anything only
one session may use at a time. They are machine-wide:
every coordinator shares the same queues. They are off by default. Turn them on
only on the user's word: `coordinator.py leases on`. Then send the lease
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
`coordinator.py config set-class <NAME> --description "..." --default-gib <n> --default-cpus <n> --max-minutes <n> [--settle OTHER=<s>]`,
and cap it with `config set-machine --max-slots <NAME>=<n>`. A class with
`--default-gib 0 --default-cpus 0` uses neither budget, so only its slot cap
limits it. That fits a single resource: one Chrome window for E2E screenshots
(`BROWSER`, 0 GiB, 1 slot), a shared tunnel, a test database, a device.
`--settle OTHER=<s>` makes OTHER wait `<s>` seconds after each grant of this
class. `config remove-class <NAME>` is refused while the class has holders or
queue entries. Add classes only on the user's word, then tell the other
coordinators and your members.

**Pool classes** lease one named resource at a time: a VM, a device, a seat.
The holder gets exclusive use of one resource until it releases it; nothing
about the resource is built in. Make a class a pool by giving it shell commands
(each optional; `--pool-create ""` removes one):

`coordinator.py config set-class <NAME> --pool-create CMD --pool-start CMD --pool-stop CMD --pool-delete CMD --pool-recycle CMD --pool-health CMD --pool-max N`

Each command reads `MOP_CLASS`, `MOP_RESOURCE`, `MOP_RESOURCE_INFO` (JSON),
`MOP_LEASE_ID` and `MOP_WORKTREE` from its environment. When the request set
`--prefer`, it also reads `MOP_PREFER` (JSON) and `MOP_PREFER_<KEY>` (upper
case) for each. `create` prints one JSON
object with a `name` (the other fields are the info the holder sees, for
example an ssh alias). `--pool-max` caps how many resources may exist.
A pool class uses neither budget, runs no host check and needs no memory
size; `maxMinutes` 0 and `extend` work as for any class, and an expired lease
keeps its resource.

`acquire` assigns a free running resource, else starts a stopped one, else runs
`create` (it can take minutes: the entry keeps its queue place and
`await-grant` prints `ASSIGNING`). With none free and the pool at its max, it
exits 3 and the server's auto acquire retries. After `GRANTED`, the member sees
`RESOURCE <name> <info>`. `puppet.py release` returns the resource and never stops it: a stop is
costly and the next grant may come soon. The server's pool upkeep stops it
after `--pool-stop-after-minutes M` idle (default 0 = never) and the next grant starts it again.
A failed `start` exits 8 and marks the resource failed (reason `start`); a
failed `create` exits 8 and leaves none, and its refusal names Hutch's own
error. Manage the pool with
`coordinator.py resource list|add|mark|remove <NAME> [--name R] [--state free|stopped|failed] [--info JSON] [--delete]`:
`add` registers an existing resource, `mark` repairs a state, `remove --delete`
runs the delete command. Free or held is derived from the leases.

**Automatic VMs.** The user's rule, 6 Nov: "you manage vms, deleting and
creating should be automatic". So the pool deletes failed resources and
creates new ones without a coordinator step:

- **Health before every grant.** With `--pool-health CMD`, `acquire` runs the
  command on the resource it picked (a free one too, not only a started or
  created one) before it writes the lease. The command prints one JSON line,
  `{"freeGiB": N, "memAvailGiB": M, ...}` with exit 0; the grant needs at
  least `--pool-min-free-gib` (default 10) free on `/` and
  `--pool-min-mem-gib` (default 2) available memory. Under either, or a
  `{"failed": ...}` line, the resource is marked failed (reason `health`) and
  not granted; `acquire` exits 8 and the next try (the server's auto acquire
  retries at once) picks another one or creates one. The facts go on the
  holder's `RESOURCE` line. `scripts/examples/hutch-pool-health` is the
  command for a Hutch pool; it changes nothing on the VM. It first reads
  `hutch env status`. Only a known unhealthy state fails the check (reason
  `health`, so the upkeep deletes it): a deletion request, an env Hutch no
  longer has, or progressStatus `FAILED` on a stopped env. `FAILED` with
  `Available` goes on to the VM checks. When they fail, it is failed. When
  they pass, it prints `{"restart": ...}`: the pool runs the stop command
  once (log `hutch-failed-restarted`, the resource is `stopped` with
  `restartedAt`), and the next grant that picks it starts it and checks it
  again. `FAILED` again after that restart, or a failed stop, retires it (log
  `hutch-failed-deleted`). A pass clears `restartedAt`. No alert for the
  restart; after a retire, every coordinator gets `POOL-LOW` when the usable
  resources fall under the pool's `min` (`config set-class --pool-min N`).
  codespaceState `Shutdown` alone
  (Hutch stops an env after some idle hours, also while it is held) prints
  `{"stopped": ...}`: the resource is marked `stopped`, never deleted for it,
  and the next grant that picks it runs the pool's start command. `READY` or
  `BUILDING` with `Available` goes on to the disk, memory and SSH checks:
  Hutch shows `BUILDING` when the app services are down (a member stopped
  them, or the clean removed the build output), and checks do not need the
  app services. An error from Hutch, a malformed response or an unknown state
  counts as unreachable: kept, never deleted for it.
- **Host faults.** When the health command prints `{"hostError": ...}`
  (exit 4), the fault is on this Mac, not on the resource: for Hutch, an
  error text that asks for `gcloud auth login`. The resource is not marked
  (free again at a release, untouched at a grant), the grant is refused, and
  the pool sets an admission hold on the class (`by pool`, with the reason),
  once. The dashboard shows the hold as a serious alert, and every
  coordinator gets `HOST-FAULT <class>: <reason>`. After the fix (`gcloud
  auth login`), a coordinator runs `admission clear <class>`.
- **Health at every release.** `puppet.py release` (pass, fail or partial)
  runs the health command while the resource is `checking` (busy, so no grant
  takes it). With `--pool-clean CMD`, the clean command runs first, to free
  disk a run left behind: best effort, at most 600 s, and a failure goes on
  to the health check. It logs `resource cleaned ... before=B GiB after=A
  GiB`, so the log shows whether the floor fits. `scripts/examples/hutch-pool-clean`
  saves a dirty checkout under `refs/recycle/`, resets it to origin/main,
  runs `git clean -ffdx`, `pnpm store prune`, and removes `~/.cache/turbo`
  and `node_modules/.cache`. Healthy: free again, so a test failure keeps a
  good VM. Under a floor: marked failed (reason `health`) at once, not at the next grant.
  Unreachable: marked failed and kept, and the coordinator gets
  `HEALTH-UNREACHABLE`. With a recycle command, the recycle runs instead (it
  checks free disk too).
- **`--retire-vm "<reason>"` retires the resource** at release, for a dirty or
  unusable VM: marked failed (reason `retire`), never granted again.
- **Failed resources are deleted, by an explicit list.** Once a minute the
  server's pool upkeep deletes an unheld failed resource with the delete
  command only when its reason is `create`, `start`, `health`, `retire` or
  `manual` (from `resource mark --state failed`). Every other failed resource is kept:
  `unreachable` (the health or recycle command could not reach it, so its
  files stay for a check: `resource mark ... --state free` returns it),
  `delete` (its delete failed once; check it, then `resource remove ...
  --delete`), `dead-<op>` (an op whose process died; see below), and any failed
  resource with no reason or an unknown one, for example one that failed
  before reasons existed or one added with `resource add --state failed`.
  `resource list` shows these as `quarantined`; a coordinator marks them
  again (`--state failed` to delete, `--state free` to return).
- **New resources.** With no free or stopped resource left, `acquire` creates
  one. Hutch picks the zone; its CLI has no zone flag. A stopped VM keeps its
  zone, so a start that fails for capacity marks it failed, the upkeep deletes
  it, and the next grant creates a VM where Hutch has room. A create command
  that fails after it made a resource prints the resource's JSON and exits
  non-zero: the pool keeps it, failed (reason `create`), and the upkeep
  deletes it, so no VM is left behind. `scripts/examples/hutch-pool-create`
  does this; it reads the env id from Hutch's stdout JSON, else from its
  stderr progress lines (`id` or `environmentId`). When Hutch names no env,
  the refusal lists your envs on main with that slot type made since the
  create started. The helper claims none of them, because a parallel create
  or an env you made by hand looks the same: check each, then `resource add`
  it or delete it.
- **Guard.** With 2 resources failed as `unreachable`, `acquire` creates no
  more and exits 3 with `resources_blocked`: the server's ssh is likely
  broken, and every new VM would fail the same way. Fix ssh, then mark them
  free.

**Recycle.** With `--pool-recycle CMD`, a resource is reset at each grant
and each release, so every holder starts clean. `puppet.py await-grant`
runs it on the granted resource before it prints `GRANTED`; `puppet.py
release` runs it after the release, while the resource is `recycling`
(busy, so no grant takes it). The command ends with one JSON line:
`{"freeGiB": N}` and exit 0 when the resource is clean, or
`{"failed": "<reason>"}` and a non-zero exit when it reached the resource
and the reset or a check failed. A failed recycle destroys the resource
with the delete command and removes it from the pool (a failed delete marks
it failed); the lease's coordinator gets `RECYCLE-DESTROYED` in its inbox.
At a grant, the lease is dropped with a `release ... result=fail` line and
the entry is queued again at the front, up to 3 destroyed resources per
`await-grant`. Any other failure (no JSON line, ssh exit 255, the
15-minute timeout) counts as unreachable: the resource is kept, never
destroyed for a missing key or a network fault. At a grant, an unreachable
resource is not granted either: it is marked failed with reason `unreachable`
(files untouched, not deleted by the upkeep; `resource mark ... --state free`
returns it), the coordinator gets `RECYCLE-UNREACHABLE`,
and the entry is queued again at the front, so no holder gets a resource that
was not reset. Recycle is off until `config set-class ... --pool-recycle` sets
the command; installing the helpers does not turn it on. The events log records
`resource recycled CLS NAME free=N GiB`, `resource recycle-unreachable`,
`resource destroyed CLS NAME reason="..."` and `resource destroy-failed`.
When a grant has to create a resource and another one comes free while the
create runs, the grant takes the free one (checked every 10 s) and the create
finishes in the background into the pool, free. A recycle at grant may print
more facts in its JSON line (the Hutch command prints `sshAlias` and
`uptimeS`); they go on the holder's `RESOURCE` line.
`scripts/examples/hutch-pool-recycle` is the command for a Hutch pool:
over `hutch env ssh-config` and ssh it fetches `origin main`, forces `main`
to `origin/main`, runs `git clean -ffdx -e node_modules` in
`/workspaces/mono`, gives the checkout to the ssh login user, and checks
that `git status --porcelain` is empty and `/` has at least 10 GiB free.
`node_modules` stays, so the next holder's install is fast; build output,
`.env*` files and nested repositories go. Before the reset, a dirty checkout is
committed to `refs/recycle/<time>-<lease>` on the VM, so it stays recoverable
there until the VM is destroyed; the reset goes ahead regardless (the user's
rule, 5 Nov: "hutch is temporary, we recycle to save on startup time. always
git reset them and destory them if not possible").

Picking: a request may carry `puppet.py request ... --prefer KEY=VALUE`
(repeatable; for example `--prefer slotType=native`) or `--resource <name>`.
`--prefer` is matched against the resource info, as strings. `acquire` takes a
matching free resource, then a matching stopped one, then waits when another is
busy, then runs `create` (with the preference in its environment) when the pool
has room, and only then takes a non-matching one. `--resource` grants exactly
that resource, starting it when stopped. When it is unknown, held, busy or
failed, `acquire` exits 3 with `resource_unavailable`; it never takes another
resource and never runs `create`. `coordinator.py wait` takes the same two
options.

Idle cleanup runs inside the dashboard server, once a minute, for every pool
class; there is nothing to arm. `--pool-stop-after-minutes M` stops an unheld
running resource idle for M minutes; `--pool-idle-delete-hours H` (default 0 =
never) deletes an unheld resource that has idled for H hours, using the delete
command. Every lifecycle step (create, start, stop, delete) claims the
resource with an op token and a busy state; `resource mark` and `remove`
refuse a busy resource. Upkeep also acts on a busy resource whose
operation's process is gone (a crashed command or a server restart), at
once; a busy state with no operation record waits 90 min. A live operation
is never touched. Any op but a create quarantines the resource: failed with
reason `dead-<op>` (`dead-recycle`, `dead-health`, `dead-delete`, ...), kept,
never granted, and the coordinator gets `RESOURCE-QUARANTINED`. The op's ssh
session or remote command can outlive its parent, so a dead parent does not
prove that a reset or a clean stopped on the VM. Check that it ended, then
`resource mark ... --state free` (or `--state failed` to delete it). A dead
create's placeholder goes, and a request still queued for it
gets a new create at the next grant. The create may have made a resource
outside the pool, so with `--pool-find CMD` upkeep lists the resources made
since the create began (`MOP_SINCE`; one `{"name": ...}` line each) and
sends the lease's coordinator `CREATE-LOST` with the names not in the pool.
It claims none, because a parallel create or one made by hand looks the
same: check each, then `resource add` it or delete it.
`scripts/examples/hutch-pool-find` lists your Hutch envs on main. The events log records each reset and deletion.
For a lease that expired over an hour ago and still holds a resource, the
lease's coordinator gets `INBOX pool: POOL-EXPIRED ...` in `watch`: ask the
holder to release. Upkeep never takes a resource back.

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
coordinator.py config set-class BUILD --auto-acquire on
coordinator.py stream update --name <stream> --auto-acquire on
```

The dashboard server does the rest, for every registered coordinator, live
or not (the class or stream setting is the opt-in); there is nothing to arm. When your entry is the head of its queue, it runs `acquire`
with the entry's own figures. Every normal gate applies: queue order, slot
cap, settle, host check and both budgets. A gate that passes later (exit 3, 4,
5) is retried every 2 s. Each outcome arrives in your inbox, so in `watch`:
`INBOX auto: AUTO-GRANTED ...`, `INBOX auto: AUTO-REFUSED ...` or
`INBOX auto: AUTO-SKIPPED ...` (an entry marked for review).

The server grants from a snapshot, so `acquire` revalidates under its final lock
(after the host check): the entry must exist with the same id, holder,
minutes, GiB, cores, commands and worktree, must not be held or reviewed, and
its class or stream must still be on auto. If not, it refuses with exit 7 and
grants nothing. Your own `acquire` has no such check and may grant a reviewed
entry.

A deviation always waits for you. The server never splits a run and never
accepts a size:

- exit 2, the run is over a limit: ask the member to split it;
- exit 6, the GiB figure is below the observed peak: decide on the member's
  LEASE SIZE reason, then `acquire --accept-size` yourself;
- an entry without minutes or worktree.

### Stalls

A deviation waits for you only for a time, so one busy coordinator cannot
hold up the whole queue. The server walks each auto class's ready entries
from the front. An entry waits for its own coordinator when it is over the
limit (exit 2), undersized (exit 6), marked for review, without minutes or a
worktree, or in a class and stream that are both off auto. After the class's
`stallMinutes` (default 20), or at once when its coordinator is not live, the
entry is **stalled**:

- It keeps its place. Its coordinator gets one
  `INBOX auto: AUTO-STALLED CLASS ID: <how>: <reason> ...`.
- The auto grant, and every `acquire`, pass over it to the first entry behind
  it that is not stalled. That entry's coordinator gets `HEAD`.
- Its own coordinator can still `acquire` it, and the stall goes as soon as
  the reason clears (for example a re-request at the observed peak, or
  `ready` after a review). It is then the head again, ahead of every entry
  behind it, so it is not starved.
- `status`, `leases` and the dashboard show it as STALLED, and the dashboard
  lists it under Needs you.

Host, budget, slot, settle and admission refusals never stall an entry: they
pass by themselves, and passing a large entry over for them would starve it.
A stall never splits a run and never accepts a size. Set the time with
`coordinator.py config set-class CLASS --stall-minutes N`; 0 turns stalls off.

A coordinator that wants to grant a class by hand turns auto off for it; its
head entries then stall after `stallMinutes` too, when another coordinator's
stream has the class on auto.

### Reclaim

Only the member releases its lease, and a member whose waiter died (for
example in an app restart) never does. An expired lease then blocks its slot
and the whole queue behind it. So the server releases a lease that expired
more than the class's `reclaimMinutes` ago (default 10) when no process runs
in its worktree (the `left=N` count of watch's `EXPIRED` line; measure-peak
does not count):

- It uses the member's own release, as `--result fail`: the run minutes and
  peaks are recorded, and a pool resource is recycled.
- The coordinator and the member get one
  `INBOX auto: AUTO-RECLAIMED CLASS ID ...`. The next head is then granted.
- A lease with a live process in its worktree is never reclaimed. Only the
  `EXPIRED` alert goes out, as before.

Pool classes default to 0 (off): a run can use its resource from outside the
worktree, and pool upkeep already reports a lease that holds a resource long
after expiry (`POOL-EXPIRED`). Set the time with
`coordinator.py config set-class CLASS --reclaim-minutes N`; 0 turns it off.

A member's request ends in one of three outcomes: `GRANTED`, `HELD <reason>`
(wait for the coordinator) or `DENIED <reason>`.

- `coordinator.py hold CLASS --id ID --reason T`: leaves the ready queue.
- `coordinator.py hold CLASS --id ID --review [--reason T]`: keeps its place,
  but the server's auto acquire never grants it (`AUTO-SKIPPED`); only your
  `acquire` does. This holds even
  when the class or stream is on auto. It applies to the first grant only.
- `coordinator.py ready CLASS --id ID`: clears a hold or review.
- `coordinator.py deny CLASS --id ID --reason T`: removes the entry
  and the member sees `DENIED <reason>` (exit 4).

Auto acquire grants each entry for its own coordinator, and only the first
grant. An
extension is never auto-approved: the member asks, and only the coordinator
runs `extend`. Takeovers stay manual too.

## Votes

`coordinator.py vote` is a question every live coordinator decides, without
the user:

```bash
coordinator.py vote propose --text "<the question and your facts>"
coordinator.py vote agree --id <id> [--text "<why>"]
coordinator.py vote object --id <id> --text "<what you saw>"
coordinator.py vote list [--all]
```

Every live peer's `watch` prints `VOTE-REQUEST <id> by <you>: ...`, and again
for each open vote it has not voted on when `watch` starts. A vote passes
when every live coordinator agrees, or 30 minutes after it was made with no
objection: a live coordinator that has not voted by then agrees. One objection
closes it, and the proposer may propose again with new facts. Everyone gets
`VOTE PASSED <id>` or `VOTE <id> REJECTED`. The server passes due votes once a
minute. `vote list` shows open votes, who has not agreed and your own vote.
Do not ask the user about a vote, and do not add a dashboard decision for it.

### Class defaults by vote

Class defaults are the coordinators' job, never the user's. Coordinators
observe and vote on each class's default GiB, cores and max minutes. Observe
with `coordinator.py sizes --worktree <path>`, `capacity` and the release lines
in `events`. When the observations support a value (for example BUILD runs
peak at 4 cores, or never run past 15 min), put it on a vote:

```bash
coordinator.py vote propose --text "<your observations>" --class BUILD [--project-root <path>] [--default-gib <n>] [--default-cpus <n>] [--max-minutes <n>]
```

Without `--project-root` it sets the machine class; with it, that project's
class, which wins over the machine class. Check your own observations of that
class before you agree or object. When the vote passes, the values apply, the
change is recorded and every live coordinator gets CONFIG. Members get no
CONFIG message: tell a member only what changes for its own task, for example
a new limit on a request it has queued.

Each heartbeat round ("Heartbeat round" in SKILL.md, step 4):

1. `coordinator.py vote list`: vote on each open vote you have not voted on,
   from your own observations. Object only when your facts contradict it, and
   say what you saw.
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
  (`coordinator.py config set-machine --reserve-gib <n> --reserve-cpus <n> --size-margin <f> --max-slots BUILD=<n>`), and
  per project the peak mode, starting GiB and cores, and max minutes
  (`coordinator.py config set-project --root <path> --class BUILD --peak learn --default-gib <n> --default-cpus <n> --max-minutes <n>`).
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
   a priority, jump the queue or grant. `watch` shows each request as
   `INBOX <name>: REQUEST <CLASS> <id> <holder> ...`, and a changed
   one as `REQUEST <CLASS> <id> changed ...`. Check that the
   recorded commands fit the class. If they do not, `unwait` the entry and
   tell the member why. A request that prints an undersized warning to the
   member will refuse at `acquire` (exit 6); you may tell the member at once. A request needs no reply: `request` printed its
   position, and `await-grant` follows the queue. Reply LEASE QUEUED only when
   you change the entry (split, hold, priority). `watch` shows only new
   lines, so a request made while it did not run has no message: each heartbeat
   round, `status --brief` shows it.
   To queue for a member yourself, for example the second part of a split:
   `coordinator.py wait <CLASS> --holder "<task> <what>" --id <slug>-q-<name>-<n> --minutes <est> --commands "<exact commands>" --worktree <path> [--gib <n>] [--cpus <n>]`.
   To change an entry later, pass only `--id` and the fields that change.
   Start `--holder` with the task id (the dashboard matches on it, and the
   entry takes that task's priority).
2. When that entry is the first ready one (`watch` prints
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
   its `watch` prints HEAD: send nothing.
   **No receipts.** A coordinator never sends a release, drain or cleanup
   receipt to another coordinator, and never asks for one. The event line is
   the record; when it is not enough, run `drain-check` yourself.
5. A member running commands outside the recorded scope breaks "use it or
   return it": ask it to release at once.
6. An expired lease of yours: `watch` prints it once as
   `EXPIRED <CLASS> <id> at <HH:MM>Z left=<n> holder=...`; `left` counts the
   processes its run still has. Ask its member to release.
   Another coordinator's expired lease shows in `status`: ask that
   coordinator only when the lease blocks your head.

**Extending.** Extension is at the coordinator's discretion; only
`coordinator.py extend` changes an expiry. A member asks with
`puppet.py extend`, which refuses a run over the class limit and otherwise
logs the request and sends it to your inbox. Your `watch` prints
`EXTEND <CLASS> <id> <n> min ... Reason: ...`. Decide: check that
the reason fits the granted commands, and weigh who waits in that class
queue and the memory the lease holds. Then run
`coordinator.py extend <CLASS> --id <id> --minutes <n>` and reply
LEASE EXTENDED, or reply LEASE EXTEND REFUSED. When the waiting head
belongs to another coordinator, ask it with `say` first. Reply each time:
the member waits for your answer. `watch` reports a lease again when
it expires after an extension.

**Admission hold.** When no grant of a class may start, for example while a
failed run's cleanup is uncertain or the disk is low:
`coordinator.py admission hold <CLASS> --reason "<why>"`. `acquire`
refuses every grant of that class (exit 3, with the reason), and `status
--brief` and the dashboard show it. Clear it when the cause is gone:
`coordinator.py admission clear <CLASS> [--reason "<what was done>"]`.
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
  (`config set-class E2E --settle BUILD=<s>`, 0 removes it); then trust the
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
