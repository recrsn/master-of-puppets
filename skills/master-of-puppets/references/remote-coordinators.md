# Remote coordinators

Each machine runs its own helper server and keeps its own roster, ledger and
lease queues. Puppets and scouts report to the coordinator on their machine.
Only coordinators message across machines. Find the peer's address and
authorized transport in your [host guide](hosts/README.md).

Each coordinator records agreed ownership, accepted handoffs and unresolved
delivery gaps with `coordinator.py note --text "..."` in its local ledger.
Identify the peer by machine and coordinator name. A local roster entry or
inbox write does not establish remote custody.

## Ownership

```text
COORDINATOR SYNC — <from> to <to> — <stream, repository/PR or scout target> — <owner> — <boundary or exception>
```

Send the initial split and then only changes that affect the shared work,
such as a PR merging, a stream changing hands or a watch losing coverage.
Name the repository with each
PR number. Distinguish the coordinator responsible for implementation from
one whose scout watches the same target. If two peers claim the same work,
settle the boundary with the other coordinator before assigning it locally.
Each heartbeat compares new peer messages and local changes against the
last shared revision, handoff or observation recorded in the ledger.
Catch up missed messages after an outage. If the host cannot replay them,
request changes since the last confirmed point. When the comparison finds
a discrepancy or an unresolved ownership or coverage question,
send `COORDINATOR SYNC? — <scope> — <what needs confirmation>` once and
record it locally. The peer replies with the owner or watch status it can
verify. Follow up when circumstances change or a missed handoff needs action.
Heartbeats, routine status, lease events and acknowledgments of acknowledgments
stay off the peer channel.

## Updating a peer installation

When coordinating an authorized update, send the tested commit SHA. Before
retrying an interrupted delivery, check whether a newer tested revision has
superseded it. Record the delivery status the transport actually returned.

The receiver follows its own host's [lease configuration](leases.md) for
validation. With leases on, obtain a local BUILD grant before running tests.
With leases off, run authorized checks directly. After installation, check
the installed SHA, live helpers and server health, then reply once with
the observed revision and result. Until that reply, report the peer
installation as unconfirmed.

## Handoff

1. When the user directs a handoff, or an authorized work request leads to
   one, send `HANDOFF — <from> to <to> — <scope> — <handoff note>`.
   For a handoff of all work, reconcile the outgoing owners’ tasks with their
   relevant worktrees, including work without a PR or stream todo. Check for
   uncommitted or untracked files and commits absent from the remote. Before
   assigning an old plan item as unstarted, check merged work for the behavior
   it already delivers, including changes shipped under a different PR title.
   List any outstanding or unverified requirements explicitly. Keep
   unpublished work on the sending machine and identify what still needs an
   authorized transfer until the receiver can access it.
   Include repository, pushed branches and heads, open PRs, remaining work,
   restrictions and completion criteria. For a stream todo, include the
   output of `coordinator.py stream todo show --name <stream> --id <n>` so
   the receiver has the requirements, subtasks and recorded PR verdict.
   For a scout, include its targets,
   last verified cursor, open alerts and gaps. Send the contents or an
   accessible artifact. A socket, local file path or worktree on the sending
   machine cannot serve as the transfer.
2. The receiver verifies the scope and sends
   `CUSTODY ACCEPTED — <receiver> owns <scope> — <local successor or pending>`.
   If it cannot take custody, it tells the sender why. Until acceptance,
   the sender keeps responsibility for outstanding work and reports any
   coverage gap. An accepted message in a transport queue is not acceptance
   of the work.
3. The receiver enrolls its own local owner or scout. The sender retires its
   local assignment and records the accepted boundary. For a watch, record
   when the old watch stopped and the new watch actually began. Existing
   gaps stay open until verified. Before interrupting a local owner, check
   its held and queued leases. Have it withdraw obsolete requests and
   release grants once its commands drain. If the owner is already offline,
   record the lease as outstanding local cleanup and follow the local
   [expiry procedure](leases.md).
   The successor obtains any needed lease on its own machine.
4. Once custody has moved and both sides can account for outstanding work,
   the receiver sends
   `HANDOFF CLOSED — <scope> — <result and evidence> — <cleanup done or still owed>`.
   Both peers record the result. Match retries to the original scope and
   handoff note before enrolling another owner or closing another assignment.

Leases apply to one physical machine. When both machines can reach the same
external resource, the coordinators agree separately which machine will use
it. A local grant cannot reserve that resource across machines.

## Scout findings

```text
ALERT FORWARD — <stream or target> — <P0|P1|P2> — <fingerprint> — <observation time, evidence and action needed>
```

The scout reports locally. Its coordinator forwards an actionable finding
to the peer that owns the affected work and preserves the severity and
fingerprint across updates. The owning coordinator routes it to its local
member. Apply the existing P0 escalation immediately, including while peer
delivery is pending. See [Scout routing and response](scouts.md).

## Rules

```text
RULES SYNC — <from> to <to> — <scope and repository if applicable> — <exported rules payload>
```

On an edit that applies to a peer, review the exported scope and send its
JSON through the authorized route. If an export also contains rules private
to this machine, share only the entries intended for the peer. Keep private
rules in helper state, outside Git.

| Rules to share | Sender runs |
| --- | --- |
| Machine rules, including the shared PR rules file if present | `coordinator.py memory export --scope machine` |
| One project's rules | `coordinator.py memory export --scope project --project-root <local-checkout>` |
| Machine rules and that project's rules | `coordinator.py memory export --scope all --project-root <local-checkout>` |

Only memory entries of kind `rule` travel. Each machine uses its own path to
the same repository. The receiver runs `coordinator.py memory import`, passing
the payload on stdin or with `--file <received-file>`. For a payload with
project rules, add `--project-root <receiver-checkout>`.

The import merges each rule by ID and `updatedAt` within its scope. It
compares the shared `pr-rules.md` as one document by modification time.
Newer changes win and ties keep the local version, so a retry leaves the
same result. Missing entries do not delete local rules. Communicate an
intended removal explicitly to the affected coordinator. Local capacity,
admission settings and credentials stay on their own machine.
