#!/usr/bin/env python3
"""Coordinator commands for master-of-puppets: roster, members, streams, ledger,
memory, peer messaging, leases, the host gate, watchers, config and install.
Members use puppet.py. Shared code is in moplib.py.

Configuration (asked once through the skill's first-run setup):
  machine  $DIR/config.json             reserveGiB, reserveCpus, sizeMargin, diskFloorGiB,
                                        diskAlarmGiB, maxSwapouts, swapIntervalS, loadPerCore,
                                        dashboardPort, maxSlots, classes
  project  $DIR/projects/<key>.json     root, baseBranch, mergeMethod, leasesDefault and per
                                        class maxMinutes, peakMode (learn|fixed), defaultGiB,
                                        defaultCpus, samples, cpuSamples
The project key comes from the repository's git common dir, so all worktrees of one
repository share a file; nothing is written into the repository.

Every limit is a number in this config, and coordinator.py enforces it: memory
and core budgets, the size margin, slot caps, settle times, max lease minutes,
swap-outs, load and the disk floor. Never put a limit in `memory`; set it with `config`.

Lease classes are a registry in config.json: any shared action that sessions must
take turns on (builds, local stacks, one browser window, a shared tunnel, a test
database, a device). Leases are optional and machine-wide. Default registry:
  BUILD: builds (incl. setup scripts that build), typecheck, lint/format, test runs, codegen.
  E2E:   starting local servers/stacks and interacting with them.
Each class has a description, defaultGiB and defaultCpus (0 = that budget does not
apply; with both 0 only maxSlots limits it), maxMinutes (0 = no limit) and settle {OTHER: seconds} (after a grant of this class,
OTHER waits that long; E2E settles BUILD for 60 s by default). Names are upper-case.
No lease: a plain dependency install, source edits, reading code, browser-only work
against remote sites (unless a class or a project rule in `memory` covers it).
Use it or return it: a lease covers the granted commands and their resource cleanup.
No edits or repairs while holding one. When a check fails, clean up owned resources
(stop owned E2E servers), release promptly with the failure, repair without a lease,
then join the queue again at the back.

Capacity is adaptive. There is no fixed slot count. A grant is admitted when the
expected peaks of all holders plus the request fit both budgets:
  sum(held GiB) + request GiB <= total RAM - reserveGiB
  sum(held cores) + request cores <= CPU cores - reserveCpus
The member sizes its run: minutes always, GiB and cores when it knows them. A GiB
figure it leaves out takes its project's class peak: in learn mode the max of the
last 5 measured peaks (`measure-peak` writes peaks/<id>.gib and .cpus; release
records them), with the default as a floor until 3 samples exist; in fixed mode the
default. A core figure it leaves out takes the class defaultCpus that coordinators
set (0 = no core charge); measured cores only inform their vote. The coordinator
decides on the request as asked: it charges the member's figures, and acquire
refuses (exit 6) a GiB figure below the observed peak (3+ samples, learn mode) by
more than sizeMargin, unless the coordinator accepts the member's reason with
--accept-size. Example: on a 24 GiB,
10-core machine with a 6 GiB and 2-core reserve, BUILD ~10 GiB/4 cores and E2E
~8 GiB/2 cores admit one of each. A 0 figure uses none of that budget.
Swap, load and disk are a separate gate (`host-check`) that acquire runs itself.
Disk: below diskAlarmGiB free the check raises the disk alarm (a warning); below
diskFloorGiB free it blocks, and no class is granted.

Admission is by priority, then FIFO, per class across coordinators: only the first
ready entry may acquire. Every entry and task starts at priority 0; higher goes first,
and entries of one priority keep their order. A queue entry takes its task's priority
(the member its holder names) unless `wait --priority` sets its own.
An expired lease (past expiresAt) still holds its memory: its holder releases it
(puppet.py release); a coordinator needs the user's approval for a takeover.

State lives in $MACHINE_LEASE_DIR (default ~/.local/state/machine-leases), not beside
this file, so every coordinator that runs any copy shares one state.

Usage: python3 -I coordinator.py <command> ...
       (the skill's other files are moplib.py, puppet.py and server.py)

Leases
  leases on|off --by C            machine-wide; only on the user's word
  status [--brief] | capacity
  wait CLASS --coordinator C --holder NAME --id ID [--minutes N] [--gib N] [--cpus N] [--commands TEXT] [--worktree P]
       [--prefer KEY=VALUE ...] [--resource NAME]   (pool classes)
       [--priority N] [--front]
       for an existing ID every flag is optional and only the given fields change.
       exit 2 when --minutes is over the class limit or --gib/--cpus over the whole budget: split the run.
       --priority: default the task's priority, else 0; a change moves the entry to its
       place among the others. --front: the head, at the highest priority in the queue.
       Members queue their own requests with puppet.py request; each puts a REQUEST
       message in the coordinator's inbox. Only acquire grants.
  acquire CLASS --coordinator C --holder NAME --id ID --worktree P --minutes N [--gib N] [--cpus N]
          [--commands TEXT] [--measure] [--accept-size]
       runs the host check itself (about 2 × swapIntervalS), then checks again under the lock.
       GiB and cores: --gib/--cpus, else the queue entry's, else the project's class peak.
       exit 0 granted, 2 --minutes over the class limit (split the run), 3 queued behind
       another entry, at a slot cap or in a settle window (another class's grant settles
       this one), 4 over the memory or core budget, 5 host BUSY or disk below the floor,
       6 undersized: a GiB figure below the observed peak by more than sizeMargin.
       --accept-size grants an undersized request: only when the member's reason fits.
       --commands records the granted scope; --measure starts measure-peak itself.
       The holder releases with puppet.py release.
  admission hold CLASS --by C --reason TEXT | admission clear CLASS --by C [--reason TEXT]
       no grant of CLASS while a hold is set (acquire exits 3 with its reason), for example
       while a failed run's cleanup is uncertain; status --brief and the dashboard show it
  unwait | ready CLASS --id ID    ready clears hold and review
  hold CLASS --id ID [--reason T] [--review]
       hold: the entry leaves the ready queue; the member sees HELD <reason>.
       --review: it keeps its place, but `watch auto` never grants it; only your acquire does.
  deny CLASS --id ID --by C --reason T   remove the entry; the member sees DENIED <reason>
  up CLASS --id ID                move a ready entry ahead of the ready entry in front of it
  move CLASS --id ID --to N       move a ready entry to position N among ready entries
       up and move set the entry's priority between its new neighbours' when it is
       outside that range, so the queue stays sorted by priority
       unwait, up and move take --notify (the dashboard's queue buttons and drag): each affected
       coordinator gets an inbox message from "dashboard", delivered directly as say does
  extend CLASS --id ID --minutes N   expires N minutes from now; exit 2 when the lease would
                                  run longer than the class limit. Extension is the coordinator's
                                  decision: members ask with puppet.py extend, and the owner's
                                  inbox gets EXTEND; reply LEASE EXTENDED or ask to release
  host-check                      admission gate; exit 0 CALM, 1 BUSY (pressure or disk below
                                  the floor); prints disk=ok|alarm|blocked
  calm-wait [--settle S] [--retry S]           one CALM line when the host is calm
  measure-peak --id ID --worktree P [--interval S]   run in the background after acquire;
                                  records peak GiB (summed RSS) and peak cores (summed %CPU)
  drain-check --worktree P [--port N ...] [--process PATTERN ...]   exit 0 when nothing is left; never kills
       agent session processes (claude, codex, their direct non-shell children, the
       caller's own ancestors and process group) and bare shells do not count. puppet.py release runs the
       same check and writes result= and drained= on its event line

Config (every set and remove takes --by C [--reason TEXT]; the event and ledger line
show who, why and each changed key with its old and new value)
  config show [--project-root P] | set-machine ... | set-project --root P ... | project-key P
       machine: --reserve-gib --reserve-cpus --size-margin --disk-floor-gib --disk-alarm-gib
                --max-swapouts --swap-interval-s --load-per-core --dashboard-port
                --max-slots CLASS=N (N=0 removes the cap)
  config set-class NAME [--description T] [--default-gib N] [--default-cpus N] [--max-minutes N]
                [--settle OTHER=S ...] [--auto-acquire on|off]
                [--pool-create CMD] [--pool-start CMD] [--pool-stop CMD] [--pool-delete CMD] [--pool-max N] [--pool-idle-delete-hours H] [--pool-stop-after-minutes M]
       a class with pool commands leases one named resource at a time (references/leases.md)
  resource list|add|mark|remove CLASS --by C [--name R] [--state free|stopped|failed] [--info JSON] [--delete]
       the resources of a pool class
       stream update ... --auto-acquire on|off   same for one stream's members
  watch pool --me C     run in the background: stop unheld running pool resources idle past
       --pool-stop-after-minutes (release never stops); reset pool resources stuck in a busy state for 90 min with no live operation; delete unheld ones idle past the class's --pool-idle-delete-hours; print
       POOL-EXPIRED for a lease that expired over an hour ago and still holds a resource
  watch auto --me C     run in the background: acquire C's head entry of each auto class or
       stream when it has minutes and a worktree. Prints AUTO-GRANTED or AUTO-REFUSED. Exit 2
       and 6 refusals are left to C (split the run, or acquire --accept-size).
  config remove-class NAME        refused while the class has holders or queue entries
  config propose CLASS --by C --reason TEXT [--project-root P] [--default-gib N] [--default-cpus N]
                [--max-minutes N]
       class defaults from C's observations (sizes, capacity, release events); 0 = no limit.
       Without --project-root it sets the machine class; with it, that project's class (which
       wins over the machine class). Every live peer gets CLASS DEFAULTS PROPOSED.
  config agree --by C --id ID | config object --by C --id ID --text TEXT | config proposals
       coordinators decide these without the user. A proposal applies when every live
       coordinator agrees, or 30 min after it was made with no objection (a live coordinator
       that has not voted agrees); the event and ledger record it, and every live coordinator
       gets CONFIG. One objection closes it. proposals lists open proposals and
       applies those that are due; run it each heartbeat round
       project: --name --base-branch --merge-method merge|squash|rebase|auto --leases-default
                [--class CLASS --max-minutes N --minutes learn|fixed --peak learn|fixed --default-gib N
                 --default-cpus N]
       --max-minutes is the hard lease limit. release records run minutes; with --minutes learn
       config show prints suggestedMinutes, p90 of the last 10 runs + 25% (at least 5, at most
       --max-minutes), a reference that never limits a lease or sets its length.

Roster and members (coordinators write; members send messages, and request and release their own leases)
  roster | whoami --session-id ID
  coordinate --name C --tool claude|codex --session-id ID --focus TEXT [--pr N ...] [--takeover] [--general]
       --general: a general-purpose coordinator with no fixed scope
  heartbeat --name C [--focus TEXT] [--pr N ...] [--status active|idle] | resign --name C
       --status idle: no work can move. Refused (exit 3) while a member is active or
       pending, or while C holds a lease or queue entry. Paused members and their PRs stay C's as parked work. An idle
       coordinator stays live and is never reported stale; peer broadcasts and update
       votes skip it. enroll, child, member add|update --status active and unpark wake it.
  stream add|update --coordinator C --name SLUG [--label TEXT] [--goal TEXT] [--pr N ...]
       update --owner C2 hands the stream to live coordinator C2
  stream close|reopen --coordinator C --name SLUG | stream list [--coordinator C]
       a stream is a named goal (one or more PR stacks) that groups members on the
       dashboard. The slug is unique on the machine; only its coordinator changes it.
       add needs --label (at most 40 characters); --goal at most 140.
  enroll --coordinator C --task TEXT [--by MEMBER] [--name NAME] [--pr N ...] [--stream SLUG] [--priority N]
       registers a task before it starts and prints the kickoff line for its prompt
  child --coordinator C --parent MEMBER --task TEXT --tool T --session-id ID [--pr N ...] [--stream SLUG]
       records a child task that MEMBER started (CHILD TASK STARTED) as pending under its
       parent, until the child's JOIN (member add --parent) takes the entry over
  member add|update --coordinator C --name NAME [--tool] [--session-id] [--worktree] [--task]
       [--pr N ...] [--repo owner/repo] [--status] [--phase] [--kind] [--latest] [--session URL]
       [--stream SLUG] [--priority N] [--parent MEMBER]   (--stream "" clears it)
       --parent: the member that started this one. On add, it takes over that parent's
       pending child entry with the same --session-id, else the same --task, else its only one
       --priority: the task's priority (default 0; higher first, below 0 for background
       work). A change also moves the task's queued lease entries and prints their ids
       updates the roster and the member's row in dashboard/<C>-state.json. Without
       --session the row links to the session from --tool and --session-id; without
       --repo, PR links use the worktree's GitHub origin (a warning when there is none)
  member remove --coordinator C --name NAME
  member transfer --coordinator C --name NAME --to C2 [--note PATH] | --cancel
  member accept --coordinator C2 --name NAME --from C
       transfer offers a member to live coordinator C2; C2's watch inbox prints TRANSFER.
       accept moves it in one locked write: the roster entry and its pending children,
       its queued and held lease entries (their coordinator field), its PRs and its row
  member stale --coordinator C [--minutes 30]   members (not done) with no update for N minutes
  park --coordinator C --name MEMBER [--until YYYY-MM-DD] [--notify]
  unpark --coordinator C --name MEMBER [--notify]
       park sets the member to paused; the task leaves Needs you and returns there as
       "Revisit" after --until. The dashboard's Park/Unpark buttons use --notify.
  decision add --by C --text TEXT [--task ID] [--href URL] [--option TEXT ...] [--scope machine]
       prints the decision id. Each --option (at most 4, 60 characters each) is a
       suggested answer: the dashboard shows it as a button on the decision.
       --scope machine: one question for every coordinator (dashboard/machine-state.json);
       its answer (decision answer --by machine) is the user's own answer for each of
       them, and --notify tells every live coordinator
  decision answer --by C --id ID --choice N [--notify]
       the user's answer, option N (from 1): clears the decision and notes it in the
       ledger. The dashboard's option buttons use --notify, so C gets the answer
  decision clear --by C (--task ID | --all) [--scope machine]
  note --by C --text TEXT [--pr N]   shared ledger

Memory (the skill's own memory; coordinators write it, everyone reads it)
  memory add --by NAME --text TEXT [--kind rule|note] [--project-root P] [--reason TEXT]
  memory update --by NAME --id ID --text TEXT [--kind rule|note] [--project-root P] [--reason TEXT]
       replaces the text and keeps the ID
  memory list [--project-root P] [--json]      machine entries, then the project's
  memory remove --by NAME --id ID [--project-root P] [--reason TEXT]
       each change logs an event (by=, reason=) and a ledger line with the old and new text
       Stored on this machine, in the state dir, never in a repository.
       Machine scope: memory/machine.json. Project scope (with --project-root):
       memory/<project-key>.json, shared by every worktree of the repository.
       Project-specific rules (for example which git hooks need a lease) live here,
       not in the skill text. Limits (GiB, slots, minutes, disk, swap, load) do not:
       they are config numbers.

Shared records (read-only; puppet.py has them too)
  inbox [--from C] [--to C] | ledger [--by C] [--pr N] | events [--id ID] [--class CLASS] [--coordinator C]
       each with [--since ISO|90s|30m|2h|1d] [--grep TEXT] [-n N (default 20, 0 all)] [--json].
       inbox --to C: messages C receives (to C or to all). events --coordinator C: C's
       grants, queue entries, lease IDs and actions. Use these, not tail, grep or jq.
  who --pr N | --worktree P | --repo owner/repo | --text TEXT
       the coordinators, members, streams, watch lists and leases that match; exit 3: no owner
  sizes --worktree P [--class CLASS]
       the project's recorded run minutes, GiB and core samples per class, the peaks
       acquire charges and the observed peaks it checks requests against
  prs --path GLOB [--path ...] [--repo owner/repo]
       open PRs of members and prs-<C>.txt watch lists whose changed files match (a glob
       or a directory prefix), with their owners; --repo also covers coordinator PRs

Peer-coordinator messaging
  say --from NAME --message TEXT [--to NAME] [--no-direct]
       appends to inbox.jsonl, then delivers directly: a Claude session through its inbox
       socket (protocol: github.com/PeterSR/claude-code-socket-transport, reverse-engineered,
       not an Anthropic interface), a Codex thread through `codex queue`. --to names a
       registered coordinator; without it, every live peer coordinator. Only registered
       coordinators use say. A receiver that bypasses
       permission prompts holds a socket message for the user's approval.

Watchers and install
  watch inbox --me C | watch expiry | watch prs --me C | watch cloud --me C [--interval S]
       Monitor sources. watch inbox reads inbox.jsonl only, never events.log. It prints
       the INBOX messages to C or to all, among them (each is a message in C's inbox):
         REQUEST CLASS ID ...   C's member queued or changed an entry: check and grant it
         PRIORITY CLASS ID N by=X   another coordinator or the dashboard changed its priority
         TRANSFER NAME ...      another coordinator offers C a member: member accept
         ACCEPT NAME ...        another coordinator took a member C offered
         EXTEND CLASS ID N min ...  C's member asks for more time (puppet.py extend): extend or refuse
         CONFIG, MEMORY, LEASES, ADMISSION, INSTALLED, UPDATE   a peer changed a machine rule
         CLASS DEFAULTS PROPOSED ID ...  a peer proposes class defaults: check your observations,
                                then config agree or config object
       and, from the queue state each 2 s:
         HEAD CLASS ID ...      an entry of C became the first ready entry: acquire it
       watch expiry prints each expired lease once, with left=N processes in its worktree.
       watch prs prints the state of each PR in prs-<C>.txt, then each change, from the shared
       poller in the dashboard server (one poll per PR for the machine, conditional by ETag), and
       PR-WATCHER down when that poller stops: start server.py.
       watch cloud reads cloud-<C>.txt (a CodeRabbit cloud task id or URL,
       then the member name, per line) and prints each task's state change from
       `coderabbit code show --agent`
  install [--replace --by C [--ignore-leases]]  copy moplib.py, coordinator.py and puppet.py into the state dir when absent.
       A live copy that differs stops the install (all or nothing). --replace installs only
       the proposed update of exactly these files, once the user approved it and every live
       coordinator agreed, while no lease is granted (--ignore-leases, only on the user's word, skips
       that check; held leases and their runs go on); it holds the state lock, so it is the
       only install, and it writes the file hashes to the ledger (no message needed). A full
       install removes obsolete helpers (lease.py). Each run except a refused --replace
       records this skill copy in source.json; roster, whoami, coordinate, heartbeat and
       status then warn on stderr when an update is due
  update propose --by C [--text TEXT]   from the skill copy: records the update (file hashes)
       with C's vote, adds a machine decision that asks the user Install / Do not install,
       and messages every live peer coordinator
  update agree --by C [--text TEXT] | update object --by C --text TEXT   record the vote
       and message every live peer coordinator
  update approve --by C --quote TEXT    the user's own words in C's session approve it
  update status [--ignore-leases]       votes, approval, blockers; exit 0 ready, 3 not

A coordinator is live while its heartbeat is newer than 40 minutes. coordinate and
heartbeat exit 3 when a PR is owned by another live coordinator; enroll and member
exit 3 when the coordinator is not live.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import re
import shutil
import subprocess
import time
import uuid
import os
import sys

# python3 -I keeps the script's own directory off sys.path; moplib is its sibling.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True  # no __pycache__ in the shared state dir
from moplib import (
    DIR, CONFIG, TOOLS, MEMBER_TOOLS, SLUG, FILES, OBSOLETE, SOURCE, version_warning, PEAKS,
    INBOX, PRS_STATE, PRS_EVENTS, PRS_POLL_S, CLASS_NAME, read_json, write_json, load_machine, registry,
    class_names, project_key, load_project, save_project, class_peak, typical_minutes,
    suggested_minutes, over_limit, undersized, extend_lease, now, lock, unlock, log, note,
    load_roster, save_roster, live, asleep, load, save, budget, order, queue_entry,
    say, deliver, notify, READS, memory_path, add_read_commands,
    read_cmd, run, worktree_pids, drain, pool_spec, pool_env, pool_run, pool_info, find_resource, RESOURCE_NAME, parse_prefer, prefer_matches,
    set_state, stop_resource, begin_op, end_op, op_current, pid_alive, BUSY_STATES, POOL_STUCK_MINUTES,
)


# ---------------------------------------------------------------- config


def changes(old, new):
    """{key: [old, new]} for each key whose value differs, one level into dicts."""
    out = {}
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        if k == "updatedAt" or a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            for sk, v in changes(a, b).items():
                out[f"{k}.{sk}"] = v
        else:
            out[k] = [a, b]
    return out


PENDING = []


def announce(by, message, members=False):
    """Queue a rule change for every live coordinator, and every live member when members is set;
    main sends it after the command releases the lock."""
    PENDING.append((by, message, members))


def record_config(by, reason, what, old, new):
    """One event and one ledger line per config change: who, why and the changed keys. The
    CONFIG message goes to live coordinators only: machine-wide config is theirs, and they
    give members task-specific direction."""
    diff = changes(old, new)
    log(f"config {what} by={by}{reason_field(reason)} changes={json.dumps(diff, separators=(',', ':'))}")
    note(by, f"config {what}: " + ("; ".join(f"{k} {json.dumps(a)} -> {json.dumps(b)}" for k, (a, b) in diff.items()) or "no change")
         + (f" (reason: {reason})" if reason else ""))
    announce(by, f"CONFIG {what} by {by}: " + ("; ".join(f"{k} {json.dumps(a)} -> {json.dumps(b)}" for k, (a, b) in diff.items()) or "no change")
             + (f" (reason: {reason})" if reason else ""))


PROPOSALS = os.path.join(DIR, "class-proposals.json")
VOTED = (("default_gib", "defaultGiB"), ("default_cpus", "defaultCpus"), ("max_minutes", "maxMinutes"))
VOTE_WINDOW_MINUTES = 30  # two heartbeat rounds: a live coordinator that has not voted by then agrees


def apply_class_defaults(p):
    """Write proposal p's values into its scope: the machine class registry, or one
    project's class. Returns (before, after) for record_config."""
    if p["project"]:
        proj = load_project(p["project"])
        before = json.loads(json.dumps(proj))
        proj["classes"][p["class"]].update(p["values"])
        proj["updatedAt"] = now().isoformat()
        save_project(proj)
        return before, proj
    raw = read_json(CONFIG) or {}
    before = json.loads(json.dumps({**raw, "classes": raw.get("classes") or registry()}))
    raw.setdefault("classes", registry())[p["class"]].update(p["values"])
    raw["updatedAt"] = now().isoformat()
    write_json(CONFIG, raw)
    return before, raw


def settle_proposal(p, roster, by):
    """Apply open proposal p when every live coordinator agrees, or when VOTE_WINDOW_MINUTES
    have passed with no objection (silence agrees). Returns the live coordinators still
    waited for."""
    waiting = [n for n, c in roster["coordinators"].items() if live(c) and not asleep(c) and p["votes"].get(n, {}).get("vote") != "agree"]
    due = now() - dt.datetime.fromisoformat(p["at"]) >= dt.timedelta(minutes=VOTE_WINDOW_MINUTES)
    if p["status"] != "open" or (waiting and not due):
        return waiting
    before, after = apply_class_defaults(p)
    p["status"], p["appliedAt"] = "applied", now().isoformat()
    p["silent"] = waiting
    what = f"class {p['class']}" + (f" project {p['project']}" if p["project"] else "")
    how = f"vote {p['id']}" + (f", silent after {VOTE_WINDOW_MINUTES} min: {', '.join(waiting)}" if waiting else "")
    record_config(by, f"{how}: {p['reason']}", what, before, after)
    announce(by, f"CONFIG {what} defaults {json.dumps(p['values'])} applied by {how}")
    return []


def class_vote_cmd(args):
    """propose, agree, object and proposals: class defaults (GiB, cores, max minutes) that
    coordinators set from their observations, without the user. A proposal applies when
    every live coordinator agrees, or after VOTE_WINDOW_MINUTES with no objection; one
    objection closes it. proposals also applies those that are due. The caller holds the lock."""
    data = read_json(PROPOSALS) or {"proposals": []}
    roster = load_roster()
    if args.ccmd == "proposals":
        for p in data["proposals"]:
            if p["status"] == "open":
                waiting = settle_proposal(p, roster, p["by"])
                print(f"{p['id']} {p['class']} {p['project'] or 'machine'} {json.dumps(p['values'])} by {p['by']}"
                      f" · observations: {p['reason']} · " + (f"waiting: {', '.join(waiting)}" if p["status"] == "open" else "applied"))
        write_json(PROPOSALS, data)
        return 0
    if not live(roster["coordinators"].get(args.by)):
        print(f"{args.by} is not a live coordinator")
        return 3
    if args.ccmd == "propose":
        if args.name not in registry():
            print(f"unknown lease class {args.name}; known: {', '.join(class_names())}")
            return 2
        values = {field: getattr(args, flag) for flag, field in VOTED if getattr(args, flag) is not None}
        if not values:
            print("propose at least one of --default-gib, --default-cpus, --max-minutes (0 = no limit)")
            return 2
        if any(v < 0 for v in values.values()):
            print("values are 0 (no limit) or more")
            return 2
        key = project_key(args.project_root)[0] if args.project_root else None
        p = {"id": uuid.uuid4().hex[:8], "class": args.name, "project": key, "values": values, "by": args.by,
             "reason": args.reason, "at": now().isoformat(), "status": "open",
             "votes": {args.by: {"vote": "agree", "at": now().isoformat()}}}
        data["proposals"].append(p)
        log(f"class-propose {p['id']} {args.name} {key or 'machine'} {json.dumps(values, separators=(',', ':'))} by={args.by}")
        announce(args.by, f"CLASS DEFAULTS PROPOSED {p['id']} by {args.by}: {args.name} ({key or 'machine'}) {json.dumps(values)}. "
                 f"Observations: {args.reason}. Check your own (sizes, capacity, events), then config agree --id {p['id']} "
                 f"or config object --id {p['id']} --text. Do not ask the user. With no objection it applies in "
                 f"{VOTE_WINDOW_MINUTES} min.")
    else:
        p = next((x for x in data["proposals"] if x["id"] == args.id), None)
        if not p or p["status"] != "open":
            print(f"no open class proposal {args.id}")
            return 3
        p["votes"][args.by] = {"vote": args.ccmd, "text": args.text or "", "at": now().isoformat()}
        log(f"class-{args.ccmd} {p['id']} by={args.by}" + (f" text={json.dumps(args.text)}" if args.text else ""))
        if args.ccmd == "object":
            p["status"] = "rejected"
            announce(args.by, f"CLASS DEFAULTS {p['id']}: {args.by} objects — {args.text}. Closed; propose again with new observations.")
    waiting = settle_proposal(p, roster, args.by)
    write_json(PROPOSALS, data)
    print(f"{p['id']} {p['status']}" + (f"; waiting for {', '.join(waiting)}" if p["status"] == "open" else ""))
    return 0


def config_cmd(args):
    machine = load_machine()
    if args.ccmd in ("propose", "agree", "object", "proposals"):
        return class_vote_cmd(args)
    if args.ccmd == "project-key":
        key, base = project_key(args.path)
        print(json.dumps({"key": key, "root": base}))
        return 0
    if args.ccmd == "set-machine":
        raw = read_json(CONFIG) or {}
        before = json.loads(json.dumps(raw))
        for flag, field in (("reserve_gib", "reserveGiB"), ("reserve_cpus", "reserveCpus"), ("size_margin", "sizeMargin"),
                            ("disk_floor_gib", "diskFloorGiB"), ("disk_alarm_gib", "diskAlarmGiB"),
                            ("max_swapouts", "maxSwapouts"), ("swap_interval_s", "swapIntervalS"),
                            ("load_per_core", "loadPerCore"), ("dashboard_port", "dashboardPort")):
            if getattr(args, flag) is not None:
                raw[field] = getattr(args, flag)
        merged = {**machine, **raw}
        if merged["diskAlarmGiB"] < merged["diskFloorGiB"]:
            print(f"--disk-alarm-gib ({merged['diskAlarmGiB']:g}) must be at least --disk-floor-gib ({merged['diskFloorGiB']:g})")
            return 2
        if not 0 <= merged["sizeMargin"] < 1:
            print(f"--size-margin is a fraction from 0 to below 1, got {merged['sizeMargin']:g}")
            return 2
        for item in args.max_slots or []:
            cls, _, n = item.partition("=")
            slots = raw.setdefault("maxSlots", {})
            if cls not in registry() or not n.isdigit():
                print(f"--max-slots wants CLASS=N, got {item}")
                return 2
            if int(n):
                slots[cls] = int(n)
            else:
                slots.pop(cls, None)
        raw["configured"] = True
        raw["updatedAt"] = now().isoformat()
        write_json(CONFIG, raw)
        record_config(args.by, args.reason, "machine", before, raw)
        print(json.dumps(load_machine(), indent=1))
        return 0
    if args.ccmd in ("set-class", "remove-class"):
        if not CLASS_NAME.match(args.name):
            print("class names are upper-case, for example BROWSER or TEST-DB")
            return 2
        raw = read_json(CONFIG) or {}
        before = json.loads(json.dumps({**raw, "classes": raw.get("classes") or registry()}))
        reg = raw.setdefault("classes", registry())
        if args.ccmd == "remove-class":
            state = load()
            if state.get(args.name) or state["queue"].get(args.name):
                print(f"{args.name} has holders or queue entries; release or unwait them first")
                return 3
            reg.pop(args.name, None)
            for other in reg.values():
                other.get("settle", {}).pop(args.name, None)
            raw.get("maxSlots", {}).pop(args.name, None)
        else:
            c = reg.setdefault(args.name, {"description": "", "defaultGiB": 0, "defaultCpus": 0, "maxMinutes": 0, "settle": {}})
            for flag, field in (("description", "description"), ("default_gib", "defaultGiB"), ("default_cpus", "defaultCpus"),
                                ("max_minutes", "maxMinutes")):
                if getattr(args, flag) is not None:
                    c[field] = getattr(args, flag)
            if args.auto_acquire is not None:
                c["autoAcquire"] = args.auto_acquire == "on"
            for flag, field in (("pool_create", "create"), ("pool_start", "start"), ("pool_stop", "stop"),
                                ("pool_delete", "delete"), ("pool_max", "max"),
                                ("pool_idle_delete_hours", "idleDeleteHours"), ("pool_stop_after_minutes", "stopAfterMinutes")):
                value = getattr(args, flag)
                if value is not None:
                    pool = c.setdefault("pool", {})
                    if value in ("", 0):
                        pool.pop(field, None)
                    else:
                        pool[field] = value
            for item in args.settle or []:
                other, _, secs = item.partition("=")
                if not secs.isdigit():
                    print(f"--settle wants OTHER=SECONDS, got {item}")
                    return 2
                if int(secs):
                    c.setdefault("settle", {})[other] = int(secs)
                else:
                    c.setdefault("settle", {}).pop(other, None)
        raw["updatedAt"] = now().isoformat()
        write_json(CONFIG, raw)
        record_config(args.by, args.reason, f"class {args.ccmd} {args.name}", before, raw)
        print(json.dumps(reg, indent=1))
        return 0
    if args.ccmd == "set-project":
        key, base = project_key(args.root)
        proj = load_project(key, base)
        before = json.loads(json.dumps(proj))
        proj["root"] = base
        for flag, field in (("name", "name"), ("base_branch", "baseBranch"), ("merge_method", "mergeMethod"), ("leases_default", "leasesDefault")):
            if getattr(args, flag) is not None:
                proj[field] = getattr(args, flag)
        if args.pcls:
            c = proj["classes"][args.pcls]
            for flag, field in (("max_minutes", "maxMinutes"), ("minutes", "minutesMode"), ("peak", "peakMode"),
                                ("default_gib", "defaultGiB"), ("default_cpus", "defaultCpus")):
                if getattr(args, flag) is not None:
                    c[field] = getattr(args, flag)
        proj["configured"] = True
        proj["updatedAt"] = now().isoformat()
        save_project(proj)
        record_config(args.by, args.reason, f"project {key}", before, proj)
        print(json.dumps(proj, indent=1))
        return 0
    out = {"machine": machine}
    missing = [] if machine["configured"] else ["machine"]
    if args.project_root:
        key, base = project_key(args.project_root)
        proj = load_project(key, base)
        for c in class_names():
            proj["classes"][c]["peakGiB"] = class_peak(proj, c)
            proj["classes"][c]["peakCpus"] = class_peak(proj, c, "cpus")
            proj["classes"][c]["suggestedMinutes"] = suggested_minutes(proj, c)
            proj["classes"][c]["typicalMinutes"] = typical_minutes(proj, c)
        out["project"] = proj
        if not proj["configured"]:
            missing.append("project")
    out["unconfigured"] = missing
    print(json.dumps(out, indent=1))
    return 3 if missing else 0


# ---------------------------------------------------------------- peer messaging


def say_cmd(args):
    """Append to inbox.jsonl (the record every coordinator watches), then deliver directly:
    Peer Claude coordinators through their inbox socket, Codex through `codex queue`."""
    roster = load_roster()
    coords = roster["coordinators"]
    if args.sender not in coords or (args.to and args.to not in coords):
        print("say is coordinator-to-coordinator only; use native direct messaging for members")
        return 2
    say(args.sender, args.message, args.to)
    print("inbox: appended")
    if args.no_direct:
        return 0
    targets = []
    if args.to:
        c = roster["coordinators"].get(args.to)
        if c:
            targets.append((args.to, c.get("tool"), c.get("sessionId")))
        if not targets:
            print(f"direct: no roster entry with a session id for {args.to} (inbox only)")
    else:
        targets = [(n, c.get("tool"), c.get("sessionId")) for n, c in roster["coordinators"].items() if n != args.sender and live(c) and not asleep(c)]
    text = f"[{args.sender} via coordinator.py say] {args.message}"
    for name, tool, sid in targets:
        print(deliver(name, tool, sid, text))
    return 0


# ---------------------------------------------------------------- roster, members and streams


PARK_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def park_cmd(args):
    """park: member status "paused", with an optional deadline (parkedUntil, a local
    date). Parked tasks stay out of Needs you; once the deadline passes the dashboard
    lists it there again as "Revisit". unpark: status "active", deadline cleared.
    With --notify (the dashboard's Park buttons), the coordinator gets a message."""
    if args.cmd == "park" and args.until and not PARK_DATE.match(args.until):
        print("--until wants a date, YYYY-MM-DD")
        return 2
    lock()
    try:
        roster = load_roster()
        members = roster["members"].get(args.coordinator, [])
        m = next((x for x in members if x["name"] == args.name), None)
        if m is None:
            print(f"{args.name} is not a member of {args.coordinator}")
            return 3
        if args.cmd == "park":
            m["status"] = "paused"
            m["parkedAt"] = now().isoformat()
            if args.until:
                m["parkedUntil"] = args.until
            else:
                m.pop("parkedUntil", None)
            done = f"parked {args.name}" + (f" until {args.until}" if args.until else "")
            message = (f"The user parked {args.name} ({m.get('task', '')})"
                       + (f" until {args.until}" if args.until else " with no deadline")
                       + " on the dashboard. Tell its member to stop work on it until it is unparked.")
        else:
            m["status"] = "active"
            for key in ("parkedAt", "parkedUntil"):
                m.pop(key, None)
            done = f"unparked {args.name}"
            coord = roster["coordinators"].get(args.coordinator)
            if asleep(coord):
                coord["status"] = "active"
                coord.pop("sleptAt", None)
                coord["heartbeat"] = now().isoformat()
                log(f"active {args.coordinator}")
                note(args.coordinator, f"{args.coordinator} is active")
            message = f"The user unparked {args.name} ({m.get('task', '')}) on the dashboard. Tell its member to resume."
        m["updatedAt"] = now().isoformat()
        save_roster(roster)
        log(f"{args.cmd} {args.coordinator} {args.name}" + (f" until={args.until}" if args.cmd == "park" and args.until else "")
            + (" by=dashboard" if args.notify else ""))
    finally:
        unlock()
    print(done)
    if args.notify:
        print(notify(args.coordinator, message))
    return 0


def pr_conflicts(roster, name, prs):
    """PRs in prs already owned by another live coordinator."""
    return {
        n: other
        for other, c in roster["coordinators"].items()
        if other != name and live(c)
        for n in c.get("prs", [])
        if n in prs
    }


KICKOFF_MARK = "MASTER-OF-PUPPETS ENROLLED"


def kickoff_line(coord, name, parent):
    by = f", started by {parent}" if parent and parent != coord else ""
    with_parent = f" with parent {parent}" if parent and parent != coord else ""
    return (
        f"{KICKOFF_MARK} — {coord} has enrolled you as member {name}{by}. "
        f"You must enroll: your first action is to run /puppet and send {coord} your JOIN message as {name}{with_parent}, before any other work; "
        f"then follow {coord}'s directions. Start every child task you create with "
        f"puppet enrollment: put a line like this one first in its prompt (the puppet skill, section 6)."
    )


def roster_cmd(args):
    roster = load_roster()
    coords = roster["coordinators"]
    if args.cmd == "leases":
        roster["leases"] = args.mode
        save_roster(roster)
        log(f"leases {args.mode} by={args.by}")
        note(args.by, f"leases {args.mode}")
        announce(args.by, f"LEASES {args.mode} by {args.by}")
        return 0
    if args.cmd in ("coordinate", "heartbeat", "resign"):
        cur = coords.get(args.name)
        if args.cmd == "coordinate":
            if not SLUG.match(args.name) or args.name == MACHINE:
                print(f"--name must be a lowercase slug other than {MACHINE}, for example claude-scope-ux")
                return 2
            if live(cur) and cur["sessionId"] != args.session_id and not args.takeover:
                print(json.dumps({"live_coordinator": {args.name: cur}}))
                return 3
            clash = pr_conflicts(roster, args.name, args.pr or [])
            if clash:
                print(json.dumps({"owned_by_other": clash}))
                return 3
            coords[args.name] = {
                "tool": args.tool,
                "sessionId": args.session_id,
                "focus": args.focus,
                "prs": args.pr or [],
                "since": now().isoformat(),
                "heartbeat": now().isoformat(),
                "status": "active",
                "general": args.general,
            }
            roster["members"].setdefault(args.name, [])
            save_roster(roster)
            log(f"coordinate {args.name} tool={args.tool} focus={args.focus!r}")
            note(args.name, f"coordinates: {args.focus}")
            print(json.dumps({"coordinator": coords[args.name], "leases": roster["leases"]}, indent=1))
            return 0
        if not cur:
            print(f"no coordinator named {args.name}")
            return 3
        if args.cmd == "heartbeat":
            if args.pr is not None:
                clash = pr_conflicts(roster, args.name, args.pr)
                if clash:
                    print(json.dumps({"owned_by_other": clash}))
                    return 3
                cur["prs"] = args.pr
            if args.focus:
                cur["focus"] = args.focus
            if args.status == "idle":
                mlist = roster["members"].get(args.name, [])
                moving = [m["name"] for m in mlist if m.get("status") not in ("done", "paused")]
                if moving:
                    print(json.dumps({"not_idle": {"members": moving}}))
                    return 3
                lstate = load()
                leased = [f"{c} {h['id']}" for c in class_names() for h in lstate[c] if h.get("coordinator") == args.name]
                queued = [f"{c} {q['id']}" for c in class_names() for q in lstate["queue"][c] if q.get("coordinator") == args.name]
                if leased or queued:
                    print(json.dumps({"not_idle": {"leases": leased, "queue": queued}}))
                    return 3
                parked = [m["name"] for m in mlist if m.get("status") == "paused"]
                if parked or cur.get("prs"):
                    print(json.dumps({"parked": {"prs": cur.get("prs", []), "members": parked}}))
            if args.status and args.status != cur.get("status", "active"):
                cur["status"] = args.status
                if args.status == "idle":
                    cur["sleptAt"] = now().isoformat()
                else:
                    cur.pop("sleptAt", None)
                log(f"{args.status} {args.name}")
                note(args.name, f"{args.name} is {args.status}")
                if args.status == "idle":
                    print(json.dumps({"asleep": "stop your heartbeat schedule and watchers; wake with heartbeat --status active"}))
            cur["heartbeat"] = now().isoformat()
            save_roster(roster)
            return 0
        coords.pop(args.name)
        save_roster(roster)
        log(f"resign {args.name}")
        note(args.name, "resigned")
        return 0
    if args.cmd == "stream":
        return stream_cmd(args, roster)
    stream = getattr(args, "stream", None)
    if stream:
        if stream not in roster["streams"]:
            print(f"no stream named {stream}; create it with coordinator.py stream add")
            return 3
        if roster["streams"][stream].get("status") == "closed":
            print(f"stream {stream} is closed; reopen it first")
            return 3
    cur = coords.get(args.coordinator)
    members = roster["members"].setdefault(args.coordinator, [])
    if not live(cur):
        alive = {n: c["focus"] for n, c in coords.items() if live(c)}
        print(json.dumps({"no_live_coordinator": args.coordinator, "live": alive}))
        return 3
    wakes = args.cmd in ("enroll", "child") or (args.cmd == "member" and (args.mcmd == "add" or (args.mcmd == "update" and args.status in ("active", "pending"))))
    if wakes and cur.get("status") == "idle":
        cur["status"] = "active"
        cur.pop("sleptAt", None)
        cur["heartbeat"] = now().isoformat()
        log(f"active {args.coordinator}")
        note(args.coordinator, f"{args.coordinator} is active")
    if args.cmd == "enroll":
        name = args.name or f"{re.sub(r'[^a-z0-9]+', '-', args.task.lower()).strip('-')[:24].strip('-')}-{os.urandom(2).hex()}"
        members[:] = [m for m in members if m["name"] != name]
        members.append({
            "name": name,
            "status": "pending",
            "parent": args.by or args.coordinator,
            "task": args.task,
            "prs": args.pr or [],
            "stream": stream or "",
            "priority": args.priority or 0,
            "enrolledAt": now().isoformat(),
        })
        save_roster(roster)
        upsert_task(args.coordinator, name, {"name": args.task, "phase": "Enrolled, not started", "kind": "work", "stream": stream or ""})
        note(args.coordinator, f"{name} enrolled (started by {args.by or args.coordinator}): {args.task}"
             + (f", priority {args.priority}" if args.priority else ""))
        print(kickoff_line(args.coordinator, name, args.by))
        return 0
    if args.cmd == "child":
        if not any(x["name"] == args.parent and x.get("status") != "pending" for x in members):
            print(f"{args.parent} is not a joined member of {args.coordinator}")
            return 3
        name = f"child-of-{args.parent}-{os.urandom(2).hex()}"
        for x in [x for x in members if x.get("status") == "pending" and x.get("sessionId") == args.session_id]:
            members.remove(x)
            remove_task(args.coordinator, x["name"])
        members.append({
            "name": name,
            "status": "pending",
            "parent": args.parent,
            "task": args.task,
            "tool": args.tool,
            "sessionId": args.session_id,
            "prs": args.pr or [],
            "stream": stream or "",
            "priority": 0,
            "enrolledAt": now().isoformat(),
        })
        save_roster(roster)
        upsert_task(args.coordinator, name, {"name": args.task, "phase": "Started, not joined", "kind": "work", "stream": stream or "",
                                             "session": session_link(args.tool, args.session_id)})
        note(args.coordinator, f"{args.parent} started child task {name}: {args.task}")
        print(name)
        return 0
    if args.cmd == "member" and args.mcmd == "stale":
        cutoff = now() - dt.timedelta(minutes=args.minutes)
        rows = []
        for x in members:
            if x.get("status") == "done":
                continue
            last = x.get("updatedAt") or x.get("joinedAt") or x.get("enrolledAt")
            when = dt.datetime.fromisoformat(last) if last else None
            if when is None or when < cutoff:
                age = int((now() - when).total_seconds() // 60) if when else None
                rows.append(f"{x['name']} {x.get('status', 'active')} last update {age if age is not None else '?'} min ago — {x.get('task', '')[:60]}")
        print("\n".join(rows) if rows else f"no member silent for {args.minutes} min")
        return 0
    if args.cmd == "member" and args.mcmd in ("transfer", "accept"):
        return transfer_cmd(args, roster)
    m = next((x for x in members if x["name"] == args.name), None)
    if args.cmd == "member" and args.mcmd == "remove":
        members[:] = [x for x in members if x["name"] != args.name]
        save_roster(roster)
        remove_task(args.coordinator, args.name)
        note(args.coordinator, f"{args.name} left")
        return 0
    if args.parent is not None and args.parent != args.coordinator and not any(
            x["name"] == args.parent and x["name"] != args.name for x in members):
        print(f"{args.parent} is not a member of {args.coordinator}")
        return 3
    if args.mcmd == "add":
        if m is None and args.parent:
            kids = [x for x in members if x.get("status") == "pending" and x.get("parent") == args.parent]
            same = [x for x in kids if args.session_id and x.get("sessionId") == args.session_id]
            same = same or [x for x in kids if args.task and x.get("task") == args.task]
            m = same[0] if same else kids[0] if len(kids) == 1 else None
            if m is not None:
                remove_task(args.coordinator, m["name"])
                m["name"] = args.name
                m["joinedAt"] = now().isoformat()
        if m is None:
            m = {"name": args.name, "joinedAt": now().isoformat()}
            members.append(m)
        m["status"] = "active"
        m.setdefault("joinedAt", now().isoformat())
    elif m is None:
        print(f"{args.name} is not a member of {args.coordinator}")
        return 3
    for flag, field in (("tool", "tool"), ("session_id", "sessionId"), ("worktree", "worktree"), ("task", "task"), ("status", "status"),
                        ("stream", "stream"), ("repo", "repo"), ("parent", "parent")):
        if getattr(args, flag, None) is not None:
            m[field] = getattr(args, flag)
    moved = None
    if args.priority is not None and args.priority != m.get("priority", 0):
        m["priority"] = args.priority
        moved = reprioritize(args.coordinator, args.name, args.priority)
        note(args.coordinator, f"{args.name} priority {args.priority}")
    if args.pr is not None:
        m["prs"] = args.pr
        if not m.get("repo") and m.get("worktree"):
            m["repo"] = github_repo(m["worktree"])
        if args.pr and not m.get("repo"):
            print(f"warning: no GitHub repo for {args.name}; PR links need --repo owner/repo", file=sys.stderr)
    m["updatedAt"] = now().isoformat()
    save_roster(roster)
    row = {}
    for flag, field in (("task", "name"), ("phase", "phase"), ("kind", "kind"), ("latest", "latest"), ("worktree", "worktree"), ("session", "session"),
                        ("stream", "stream")):
        if getattr(args, flag, None) is not None:
            row[field] = getattr(args, flag)
    if args.session is None and (args.mcmd == "add" or args.session_id is not None or args.tool is not None):
        row["session"] = session_link(m.get("tool"), m.get("sessionId"))
    if (args.pr is not None or args.repo) and m.get("repo"):
        row["links"] = [{"label": f"PR #{n}", "href": f"https://github.com/{m['repo']}/pull/{n}"} for n in m.get("prs", [])]
    if args.mcmd == "add":
        row.setdefault("phase", "Joined")
    upsert_task(args.coordinator, args.name, row)
    if args.mcmd == "add":
        by = f", child of {m['parent']}" if m.get("parent") and m["parent"] != args.coordinator else ""
        note(args.coordinator, f"{args.name} joined{by}: {m.get('task', '')} (PRs {' '.join('#' + str(n) for n in m.get('prs', [])) or 'none'})")
    if moved:
        print(json.dumps({"moved": moved}))
    return 0


def transfer_cmd(args, roster):
    """transfer: offer member NAME to live coordinator --to (or --cancel the offer).
    accept: the receiver takes it in one locked write: the roster entry and its pending
    children, its queued and held lease entries, its PRs and its dashboard row. The
    caller holds the lock and has checked that --coordinator is live."""
    coords = roster["coordinators"]
    if args.mcmd == "transfer":
        m = next((x for x in roster["members"].get(args.coordinator, []) if x["name"] == args.name), None)
        if m is None:
            print(f"{args.name} is not a member of {args.coordinator}")
            return 3
        if args.cancel:
            offer = m.pop("transfer", None)
            save_roster(roster)
            log(f"transfer {args.name} from={args.coordinator} cancelled by={args.coordinator}")
            print(f"cancelled the offer of {args.name}" + (f" to {offer['to']}" if offer else " (there was none)"))
            return 0
        if not args.to or args.to == args.coordinator or not live(coords.get(args.to)):
            print(json.dumps({"no_live_coordinator": args.to}))
            return 3
        m["transfer"] = {"to": args.to, "note": args.note or "", "at": now().isoformat()}
        save_roster(roster)
        log(f"transfer {args.name} from={args.coordinator} to={args.to} by={args.coordinator}"
            + (f" note={json.dumps(args.note)}" if args.note else ""))
        note(args.coordinator, f"offered {args.name} to {args.to}" + (f"; note {args.note}" if args.note else ""))
        say(args.coordinator, f"TRANSFER {args.name} from {args.coordinator}" + (f", note {args.note}" if args.note else "")
            + f": take it with member accept --coordinator {args.to} --name {args.name} --from {args.coordinator}", args.to)
        print(f"offered {args.name} to {args.to}; it takes the member with member accept")
        return 0
    src, dst = args.source, args.coordinator
    moving = [x for x in roster["members"].get(src, []) if x["name"] == args.name]
    if not moving or (moving[0].get("transfer") or {}).get("to") != dst:
        print(f"{src} has not offered {args.name} to {dst}")
        return 3
    m = moving[0]
    moving += [x for x in roster["members"][src] if x.get("status") == "pending" and x.get("parent") == args.name]
    names = [x["name"] for x in moving]
    for x in moving:
        roster["members"][src].remove(x)
        x.pop("transfer", None)
        if x.get("parent") == src:
            x["parent"] = dst
        x["updatedAt"] = now().isoformat()
        roster["members"].setdefault(dst, []).append(x)
    prs = [n for x in moving for n in x.get("prs", [])]
    if src in coords:
        coords[src]["prs"] = [n for n in coords[src].get("prs", []) if n not in prs]
    coords[dst]["prs"] = list(dict.fromkeys(coords[dst].get("prs", []) + prs))
    save_roster(roster)
    state, machine = load(), load_machine()
    leases = []
    for c in class_names(machine):
        for q in state[c] + state["queue"][c]:
            if q["coordinator"] == src and q["holder"].partition(" ")[0] in names:
                q["coordinator"] = dst
                leases.append(q["id"])
    if leases:
        save(state, machine)
    rows = {t["id"]: t for t in (read_json(state_path(src)) or {}).get("tasks", [])}
    for n in names:
        remove_task(src, n)
        upsert_task(dst, n, {k: v for k, v in rows.get(n, {"name": next(x.get("task") for x in moving if x["name"] == n)}).items() if k != "id"})
    log(f"accept {args.name} from={src} to={dst} by={dst}" + (f" leases={','.join(leases)}" if leases else ""))
    note(dst, f"took {', '.join(names)} from {src}" + (f"; PRs {' '.join('#' + str(n) for n in prs)}" if prs else "")
         + (f"; leases {', '.join(leases)}" if leases else ""))
    say(dst, f"ACCEPT {', '.join(names)}: {dst} took custody" + (f"; PRs {' '.join('#' + str(n) for n in prs)}" if prs else "")
        + (f"; leases {', '.join(leases)}" if leases else "") + ". Stop directing it.", src)
    print(json.dumps({"moved": names, "prs": prs, "leases": leases}))
    return 0


def reprioritize(coord, name, priority):
    """Give the task's queued lease entries its new priority and re-order each queue.
    Returns {CLASS: [ids]} of the moved entries, so the coordinator can tell their new turn."""
    state, machine = load(), load_machine()
    moved = {}
    for c in class_names(machine):
        for q in state["queue"][c]:
            if q["coordinator"] == coord and q["holder"].partition(" ")[0] == name and q.get("priority", 0) != priority:
                q["priority"] = priority
                moved.setdefault(c, []).append(q["id"])
                log(f"priority {c} {q['id']} {priority} by={coord}")
        order(state["queue"][c])
    if moved:
        save(state, machine)
    return moved


def stream_cmd(args, roster):
    """Streams: named goals that group members on the dashboard. Only the owning coordinator changes one."""
    streams = roster["streams"]
    if args.scmd == "list":
        rows = {n: s for n, s in streams.items() if not args.coordinator or s.get("coordinator") == args.coordinator}
        print(json.dumps(rows, indent=1))
        return 0
    if not SLUG.match(args.name):
        print("--name must be a lowercase slug, for example repo-access")
        return 2
    for flag, limit in (("label", 40), ("goal", 140)):
        text = getattr(args, flag, None)
        if text is not None and len(text) > limit:
            print(f"--{flag} must be at most {limit} characters; it is shown on the dashboard")
            return 2
    cur = streams.get(args.name)
    if not live(roster["coordinators"].get(args.coordinator)):
        print(json.dumps({"no_live_coordinator": args.coordinator}))
        return 3
    if args.scmd == "add":
        if cur:
            print(json.dumps({"stream_exists": {args.name: cur}}))
            return 3
        if not args.label:
            print("stream add needs --label")
            return 2
        cur = streams[args.name] = {"coordinator": args.coordinator, "label": args.label, "goal": args.goal or "",
                                    "prs": args.pr or [], "status": "open", "createdAt": now().isoformat()}
    elif not cur:
        print(f"no stream named {args.name}")
        return 3
    elif cur.get("coordinator") != args.coordinator:
        print(json.dumps({"owned_by": cur.get("coordinator"), "stream": args.name}))
        return 3
    elif args.scmd == "update":
        if args.owner and not live(roster["coordinators"].get(args.owner)):
            print(json.dumps({"no_live_coordinator": args.owner}))
            return 3
        for flag in ("label", "goal"):
            if getattr(args, flag) is not None:
                cur[flag] = getattr(args, flag)
        if args.pr is not None:
            cur["prs"] = args.pr
        if args.auto_acquire is not None:
            cur["autoAcquire"] = args.auto_acquire == "on"
        if args.owner and args.owner != args.coordinator:
            cur["coordinator"] = args.owner
            note(args.coordinator, f"stream {args.name} handed to {args.owner}")
    else:
        cur["status"] = "closed" if args.scmd == "close" else "open"
    cur["updatedAt"] = now().isoformat()
    save_roster(roster)
    log(f"stream {args.scmd} {args.name} by={args.coordinator}")
    if args.scmd in ("add", "close", "reopen"):
        verb = {"add": "opened", "close": "closed", "reopen": "reopened"}[args.scmd]
        note(args.coordinator, f"stream {args.name} {verb}: {cur['label']}")
    print(json.dumps({args.name: cur}, indent=1))
    return 0


def state_path(coord):
    return os.path.join(DIR, "dashboard", f"{coord}-state.json")


def session_link(tool, session_id):
    """Deep link for the dashboard, from the tool and its session or thread id."""
    if not session_id:
        return None
    if tool == "coderabbit":
        return f"https://app.coderabbit.ai/code/tasks/{session_id}"
    return f"codex://threads/{session_id}" if tool == "codex" else f"claude://claude.ai/epitaxy/{session_id}"


def github_repo(worktree):
    """owner/repo of the worktree's GitHub origin remote, or None."""
    out = subprocess.run(["git", "-C", os.path.expanduser(worktree), "remote", "get-url", "origin"],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    hit = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", out.stdout.strip()) if out.returncode == 0 else None
    return hit.group(1) if hit else None


def upsert_task(coord, task_id, fields):
    """Create or update the dashboard row for a member in dashboard/<coord>-state.json."""
    path = state_path(coord)
    data = read_json(path) or {}
    tasks = data.setdefault("tasks", [])
    row = next((t for t in tasks if t.get("id") == task_id), None)
    if row is None:
        row = {"id": task_id}
        tasks.append(row)
    row.update({k: v for k, v in fields.items() if v is not None})
    data["updated"] = now().strftime("%H:%MZ")
    write_json(path, data)


def remove_task(coord, task_id):
    path = state_path(coord)
    data = read_json(path) or {}
    data["tasks"] = [t for t in data.get("tasks", []) if t.get("id") != task_id]
    data["updated"] = now().strftime("%H:%MZ")
    write_json(path, data)


MAX_OPTIONS = 4
MAX_OPTION_CHARS = 60


MACHINE = "machine"  # the dashboard source of machine-scope decisions; no coordinator has this name


def add_decision(by, text, options, scope=None, task=None, href=None, extra=None):
    """Append a decision to dashboard/<by>-state.json, or with scope machine to
    dashboard/machine-state.json (one question for every coordinator). The caller holds the lock."""
    path = state_path(MACHINE if scope == MACHINE else by)
    data = read_json(path) or {}
    item = {"id": uuid.uuid4().hex[:8], "text": text}
    if scope == MACHINE:
        item["by"] = by
    if task:
        item["task"] = task
    if href:
        item["href"] = href
    if options:
        item["options"] = options
    item.update(extra or {})
    data.setdefault("decisions", []).append(item)
    data["updated"] = now().strftime("%H:%MZ")
    write_json(path, data)
    return item


def decision_cmd(args):
    """add, answer and clear. answer is the user's choice from the dashboard; it runs in
    another process than the owner's, so it takes the lock. A machine-scope decision
    (--scope machine; answered with --by machine) is one question for every coordinator:
    the answer is the user's own answer for each of them, and each live one is told."""
    if args.dcmd == "add" and args.option:
        if len(args.option) > MAX_OPTIONS or any(len(o) > MAX_OPTION_CHARS or not o.strip() for o in args.option):
            print(f"at most {MAX_OPTIONS} options, each 1 to {MAX_OPTION_CHARS} characters")
            return 2
    if args.dcmd == "clear" and not (args.task or args.all):
        print("decision clear needs --task ID or --all")
        return 2
    scope = getattr(args, "scope", None)
    machine_scope = scope == MACHINE or args.by == MACHINE
    path = state_path(MACHINE if machine_scope else args.by)
    lock()
    try:
        if args.dcmd == "add":
            item = add_decision(args.by, args.text, args.option, scope, args.task, args.href)
            data = read_json(path)
            log(f"decision add {item['id']} scope={scope or 'coordinator'} by={args.by}")
            print(f"decision {item['id']} added · {len(data['decisions'])} decisions for {MACHINE if machine_scope else args.by}")
            return 0
        data = read_json(path) or {}
        items = data.setdefault("decisions", [])
        if args.dcmd == "answer":
            item = next((d for d in items if isinstance(d, dict) and d.get("id") == args.id), None)
            options = (item or {}).get("options") or []
            if item is None or not 1 <= args.choice <= len(options):
                print(f"decision {args.id} of {args.by} has changed or is answered; reload the dashboard")
                return 3
            answer = options[args.choice - 1]
            data["decisions"] = [d for d in items if d is not item]
            task = item.get("task", "")
            done = f"Answered{' for ' + task if task else ''}: {answer}"
            whom = " for every coordinator" if machine_scope else ""
            message = (f"The user answered the decision{' for ' + task if task else ''}{whom} on the dashboard: \"{answer}\" "
                       f"(question: \"{item.get('text', '')}\"). This is the user's answer; act on it.")
            if item.get("update"):
                record_update_answer(item["update"], args.choice == 1, answer)
        else:
            def keep(d):
                """Machine scope clears only your own items. A legacy string decision has no
                task or author: only a coordinator-scope --all clears it."""
                if not isinstance(d, dict):
                    return machine_scope or not args.all
                if machine_scope and d.get("by") != args.by:
                    return True
                return not args.all and d.get("task") != args.task
            data["decisions"] = [d for d in items if keep(d)]
            done = "cleared"
        data["updated"] = now().strftime("%H:%MZ")
        write_json(path, data)
        if args.dcmd == "answer":
            log(f"decision answer {args.by} {args.id} choice={args.choice}" + (" by=dashboard" if args.notify else ""))
            note("dashboard" if args.notify else args.by, f"User decision{' for ' + task if task else ''}{whom}: {answer} ({item.get('text', '')})")
    finally:
        unlock()
    print(f"{done} · {len(data['decisions'])} decisions for {MACHINE if machine_scope else args.by}")
    if args.dcmd == "answer" and args.notify:
        targets = [n for n, c in load_roster()["coordinators"].items() if live(c)] if machine_scope else [args.by]
        for name in targets:
            print(notify(name, message))
    return 0


# ---------------------------------------------------------------- helper update vote


UPDATE = os.path.join(DIR, "update.json")


def file_hashes(src):
    return {n: hashlib.sha256(open(os.path.join(src, n), "rb").read()).hexdigest() for n in FILES}


def digest_of(hashes):
    return hashlib.sha256("".join(hashes[n] for n in FILES).encode()).hexdigest()[:12]


def update_blockers(proposal, roster, state, ignore_leases=False):
    """Why proposal cannot be installed now: an empty list when it can. ignore_leases (the user's word)
    drops the granted-lease blocker."""
    if not proposal:
        return ["no update proposal; run update propose from the skill copy"]
    why = []
    if proposal.get("installed"):
        why.append(f"already installed by {proposal['installed']['by']} at {proposal['installed']['at']}")
    if proposal.get("rejected"):
        why.append(f"the user rejected it: {proposal['rejected']}")
    if not proposal.get("approval"):
        why.append("no user approval: the dashboard decision, or update approve with the user's words")
    votes = proposal.get("votes", {})
    for name, c in roster["coordinators"].items():
        v = votes.get(name, {}).get("vote")
        if v == "object":
            why.append(f"{name} objects: {votes[name].get('text', '')}")
        elif live(c) and not asleep(c) and v != "agree":
            why.append(f"no vote from live coordinator {name}")
    held = [h["id"] for c in class_names() for h in state[c]]
    if held and not ignore_leases:
        why.append(f"leases are granted: {', '.join(held)}; install between grants")
    return why


def record_update_answer(digest, yes, answer):
    """The user's answer to an update proposal's machine decision. The caller holds the lock."""
    proposal = read_json(UPDATE)
    if not proposal or proposal["digest"] != digest:
        return
    if yes:
        proposal["approval"] = {"by": "dashboard", "quote": answer, "at": now().isoformat()}
    else:
        proposal["rejected"] = f"{answer} (dashboard, {now().isoformat()})"
    write_json(UPDATE, proposal)
    log(f"update {'approve' if yes else 'reject'} {digest} by=dashboard")


def broadcast(sender, message, members=False):
    """Inbox record, then direct delivery to every live peer coordinator (say without --to).
    With members, also to every live member of a live coordinator, so no coordinator relays it."""
    say(sender, message)
    roster = load_roster()
    text = f"[{sender} via coordinator.py] {message}"
    for n, c in roster["coordinators"].items():
        if n != sender and live(c) and not asleep(c):
            print(deliver(n, c.get("tool"), c.get("sessionId"), text))
    if not members:
        return
    for coord, mlist in roster["members"].items():
        if not live(roster["coordinators"].get(coord)) or asleep(roster["coordinators"].get(coord)):
            continue
        for m in mlist:
            if m.get("status") != "done":
                print(deliver(m["name"], m.get("tool"), m.get("sessionId"), text))


def update_cmd(args):
    """propose, agree, object, approve and status: one shared record of a helper update
    that install reads. propose, agree and object also message every live peer."""
    announce = []
    code = update_locked(args, announce)
    for message in announce:
        broadcast(args.by, message)
    return code


def update_locked(args, announce):
    lock()
    try:
        roster, state = load_roster(), load()
        proposal = read_json(UPDATE)
        if args.ucmd == "status":
            why = update_blockers(proposal, roster, state, args.ignore_leases)
            if proposal:
                print(json.dumps({k: proposal.get(k) for k in ("digest", "git", "source", "by", "at", "text", "votes", "approval", "rejected", "installed")}, indent=1))
            print("ready to install" if not why else "not ready:\n  " + "\n  ".join(why))
            return 0 if not why else 3
        if not live(roster["coordinators"].get(args.by)):
            print(f"{args.by} is not a live coordinator")
            return 3
        if args.ucmd == "propose":
            here = os.path.dirname(os.path.realpath(__file__))
            if os.path.realpath(DIR) == here:
                print("run update propose from the skill copy, not the live copy")
                return 2
            hashes = file_hashes(here)
            digest = digest_of(hashes)
            if proposal and proposal["digest"] == digest and not proposal.get("installed"):
                print(f"update {digest} is already proposed by {proposal['by']}")
                return 0
            git = run(["git", "-C", here, "describe", "--always", "--dirty"]).strip() or None
            proposal = {"digest": digest, "files": hashes, "source": here, "git": git, "by": args.by, "at": now().isoformat(),
                        "text": args.text or "", "votes": {args.by: {"vote": "agree", "at": now().isoformat()}}}
            item = add_decision(args.by, f"Replace the live helpers with {git or digest} from {here}? Proposed by {args.by}"
                                + (f": {args.text}" if args.text else ""), ["Install", "Do not install"], MACHINE,
                                extra={"update": digest})
            proposal["decision"] = item["id"]
            write_json(UPDATE, proposal)
            log(f"update propose {digest} by={args.by}")
            note(args.by, f"proposed helper update {digest} ({git or 'no git'}) from {here}; machine decision {item['id']}")
            print(f"proposed update {digest}; machine decision {item['id']} asks the user")
            announce.append(f"UPDATE PROPOSED {digest} ({git or 'no git'}) by {args.by}"
                            + (f": {args.text}" if args.text else "")
                            + f". Read the diff with install, then run update agree or update object --text.")
            return 0
        if not proposal or proposal.get("installed"):
            print("no open update proposal")
            return 3
        if args.ucmd == "approve":
            proposal["approval"] = {"by": args.by, "quote": args.quote, "at": now().isoformat()}
            path = state_path(MACHINE)
            data = read_json(path) or {}
            data["decisions"] = [d for d in data.get("decisions", []) if d.get("id") != proposal.get("decision")]
            write_json(path, data)
        else:
            proposal.setdefault("votes", {})[args.by] = {"vote": args.ucmd, "text": args.text or "", "at": now().isoformat()}
        write_json(UPDATE, proposal)
        log(f"update {args.ucmd} {proposal['digest']} by={args.by}")
        note(args.by, f"update {proposal['digest']}: {args.ucmd}" + (f" — user: {args.quote}" if args.ucmd == "approve" else
                                                                     f" — {args.text}" if args.text else ""))
        if args.ucmd in ("agree", "object"):
            announce.append(f"UPDATE {proposal['digest']}: {args.by} {'agrees' if args.ucmd == 'agree' else 'objects'}"
                            + (f" — {args.text}" if args.text else ""))
        why = update_blockers(proposal, roster, state)
        print("ready to install" if not why else "not ready:\n  " + "\n  ".join(why))
        return 0
    finally:
        unlock()


# ---------------------------------------------------------------- memory


def reason_field(reason):
    return f" reason={json.dumps(reason)}" if reason else ""


def memory_cmd(args):
    """add, update (same ID) and remove. Each change logs one event and one ledger line
    with who and why, and messages every live peer coordinator."""
    path, name = memory_path(args.project_root)
    lock()
    try:
        data = read_json(path) or {"entries": []}
        if args.mcmd == "add":
            entry = {"id": f"m-{os.urandom(3).hex()}", "kind": args.kind, "text": args.text, "by": args.by, "at": now().isoformat()}
            data["entries"].append(entry)
            write_json(path, data)
            log(f"memory add {name} {entry['id']} by={args.by}{reason_field(args.reason)}")
            note(args.by, f"memory {name} {entry['id']} added: {args.text}" + (f" (reason: {args.reason})" if args.reason else ""))
            announce(args.by, f"MEMORY {name} {entry['id']} added by {args.by}: {args.text}" + (f" (reason: {args.reason})" if args.reason else ""), members=True)
            print(entry["id"])
            return 0
        entry = next((x for x in data["entries"] if x["id"] == args.id), None)
        if entry is None:
            print(f"no memory entry {args.id} in {name}")
            return 3
        if args.mcmd == "update":
            old = entry["text"]
            entry["text"] = args.text
            if args.kind:
                entry["kind"] = args.kind
            entry.update({"updatedBy": args.by, "updatedAt": now().isoformat()})
            change = f"changed from {json.dumps(old)} to {json.dumps(args.text)}"
        else:
            data["entries"].remove(entry)
            change = f"removed: {json.dumps(entry['text'])}"
        write_json(path, data)
        log(f"memory {args.mcmd} {name} {args.id} by={args.by}{reason_field(args.reason)}")
        note(args.by, f"memory {name} {args.id} {change}" + (f" (reason: {args.reason})" if args.reason else ""))
        announce(args.by, f"MEMORY {name} {args.id} {change} by {args.by}" + (f" (reason: {args.reason})" if args.reason else ""), members=True)
        return 0
    finally:
        unlock()


# ---------------------------------------------------------------- leases


def brief(state):
    """One line per holder and per class queue, then the budget."""
    t = now()
    lines = []
    for c in class_names():
        for h in state[c]:
            left = int((dt.datetime.fromisoformat(h["expiresAt"]) - t).total_seconds() // 60)
            status = f"EXPIRED {-left} min ago" if left < 0 else f"{left} min left"
            lines.append(f"{c} held  {h['id']} ({h['coordinator']}, {h['gib']} GiB, {h['cpus']} cores) {status} — {h['holder'][:60]}")
            if h.get("commands"):
                lines.append(f"           covers: {h['commands'][:120]}")
        q = state["queue"][c]
        ready = [x for x in q if not x.get("hold")]
        prio = f", priority {ready[0]['priority']}" if ready and ready[0].get("priority") else ""
        head = f"head {ready[0]['id']} ({ready[0]['coordinator']}{prio})" if ready else "no ready entry"
        lines.append(f"{c} queue {len(ready)} ready, {len(q) - len(ready)} on hold — {head}")
    for c, hold in state.get("admission", {}).items():
        lines.append(f"{c} ADMISSION HOLD by {hold['by']} since {hold['at'][11:16]}Z — {hold['reason']}")
    b = state["budget"]
    lines.append(f"budget {b['freeGiB']} of {b['limitGiB']} GiB free · {b['freeCpus']} of {b['limitCpus']} cores free"
                 f" · capacity {b['capacity']} · peaks {b['peakGiB']} GiB {b['peakCpus']} cores")
    return "\n".join(lines)


def queue_edit_cmd(args):
    """unwait, up and move. With --notify, tell each affected coordinator after the lock is released."""
    lock()
    try:
        state, machine = load(), load_machine()
        queue = state["queue"][args.cls]
        i = next((n for n, q in enumerate(queue) if q["id"] == args.id), None)
        if i is None:
            print(f"{args.id} is not queued for {args.cls}")
            return 0 if args.cmd == "unwait" else 3
        entry = queue[i]
        if args.cmd == "unwait":
            del queue[i]
            done = f"removed {args.id} from the {args.cls} queue"
            message = (f"The user cancelled {args.cls} queue entry {args.id} ({entry['holder']}) on the dashboard. "
                       "Tell its member; queue it again only if the user agrees.")
            to = [entry["coordinator"]]
            log(f"unwait {args.cls} {args.id}" + (" by=dashboard" if args.notify else ""))
        else:
            if entry.get("hold"):
                print(f"{args.id} is on hold; mark it ready first")
                return 3
            ready = [n for n, q in enumerate(queue) if not q.get("hold")]
            pos = ready.index(i) + 1
            target = max(1, min(pos - 1 if args.cmd == "up" else args.to, len(ready)))
            if target == pos:
                print(f"{args.id} is already at {args.cls} position {pos} among ready entries")
                return 0
            other = queue[ready[target - 1]]
            queue.pop(i)
            j = queue.index(other) + (target > pos)
            queue.insert(j, entry)
            # Keep the queue sorted by priority, so a later sort keeps the new place:
            # the entry takes a priority between its neighbours'.
            old = entry.get("priority", 0)
            new = old
            if j + 1 < len(queue):
                new = max(new, queue[j + 1].get("priority", 0))
            if j:
                new = min(new, queue[j - 1].get("priority", 0))
            if new != old:
                entry["priority"] = new
            prio = f" at priority {new}" if new != old else ""
            side = "ahead of" if target < pos else "behind"
            done = f"moved {args.id} to {args.cls} position {target}{prio}, {side} {other['id']}"
            message = (f"The user moved {args.cls} queue entry {args.id} ({entry['holder']}) from position {pos} to {target}{prio}, "
                       f"{side} {other['id']} ({other['holder']}), on the dashboard. Tell the affected members their new turn.")
            to = list(dict.fromkeys([entry["coordinator"], other["coordinator"]]))
            log(f"{args.cmd} {args.cls} {args.id} to {target} {side} {other['id']}" + (" by=dashboard" if args.notify else ""))
        save(state, machine)
    finally:
        unlock()
    print(done)
    for name in to if args.notify else []:
        print(notify(name, message))
    return 0


def admission_cmd(args, state, machine):
    """hold: no grant of CLASS until clear, for example while a failed run's cleanup is
    uncertain or the disk is low. acquire refuses with exit 3 and the hold's reason.
    The caller holds the lock."""
    holds = state.setdefault("admission", {})
    if args.acmd == "hold":
        holds[args.cls] = {"by": args.by, "reason": args.reason, "at": now().isoformat()}
        verb = "hold"
    elif args.cls not in holds:
        print(f"no admission hold on {args.cls}")
        return 0
    else:
        old = holds.pop(args.cls)
        verb = "clear"
        if old["by"] != args.by:
            print(f"cleared the hold of {old['by']}: {old['reason']}")
    save(state, machine)
    log(f"admission {verb} {args.cls} by={args.by}" + (f" reason={json.dumps(args.reason)}" if args.reason else ""))
    note(args.by, f"admission {verb} {args.cls}" + (f": {args.reason}" if args.reason else ""))
    announce(args.by, f"ADMISSION {verb} {args.cls} by {args.by}" + (f": {args.reason}" if args.reason else ""))
    return 0


def acquire_checks(args, state, machine):
    """Every acquire gate except the host and the memory budget. Returns (exit, text) to refuse, else None."""
    queue, holders = state["queue"][args.cls], state[args.cls]
    if any(h["id"] == args.id for h in holders):
        return 0, "already held"
    hold = state.get("admission", {}).get(args.cls)
    if hold:
        return 3, json.dumps({"admission_hold": {args.cls: hold}})
    entry = next((q for q in queue if q["id"] == args.id), {})
    why = over_limit(args.cls, entry.get("project") or project_key(args.worktree)[0], args.minutes)
    if why:
        return 2, why
    ready = [q for q in queue if not q.get("hold")]
    if ready and ready[0]["id"] != args.id:
        return 3, json.dumps({"queued_ahead": ready[0]})
    cap = machine["maxSlots"].get(args.cls)
    if cap and len(holders) >= cap:
        return 3, json.dumps({"max_slots": cap, "held": holders})
    for other, spec in registry(machine).items():
        secs = (spec.get("settle") or {}).get(args.cls, 0)
        for h in state[other] if secs else []:
            left = secs - (now() - dt.datetime.fromisoformat(h["grantedAt"])).total_seconds()
            if left > 0:
                return 3, json.dumps({"settling": int(left), "after": h["id"], "class": other})
    return None


def acquire_cmd(args):
    """Check the queue, cap, settle and length; run the host check without the lock; then
    check again under the lock (another grant may have landed) and the memory budget.
    A pool class skips the host and budget gates and assigns a resource instead."""
    if pool_spec(args.cls):
        return pool_acquire_cmd(args)
    lock()
    try:
        refused = acquire_checks(args, load(), load_machine())
    finally:
        unlock()
    if refused:
        print(refused[1])
        return refused[0]
    calm, line = host_check()
    if not calm:
        print(json.dumps({"host": line}))
        log(f"refuse {args.cls} {args.coordinator} {args.id} host BUSY")
        return 5
    lock()
    try:
        state, machine = load(), load_machine()
        refused = acquire_checks(args, state, machine)
        if refused:
            print(refused[1])
            return refused[0]
        queue, holders = state["queue"][args.cls], state[args.cls]
        entry = next((q for q in queue if q["id"] == args.id), {})
        expect = getattr(args, "auto_expect", None)
        if expect and (entry_tuple(entry) != expect or entry.get("hold") or entry.get("review")
                       or not auto_entry(entry, machine, load_roster(), args.cls)):
            print(json.dumps({"auto_stale": args.id}))
            log(f"refuse {args.cls} {args.coordinator} {args.id} auto grant: entry changed, held, reviewed or auto is off")
            return 7
        key = entry.get("project") or project_key(args.worktree)[0]
        asked_gib, asked_cpus = args.gib or entry.get("gib"), args.cpus or entry.get("cpus")
        why = None if args.accept_size else undersized(args.cls, key, asked_gib, machine["sizeMargin"])
        if why:
            print(json.dumps({"undersized": why}))
            log(f"refuse {args.cls} {args.coordinator} {args.id} {why}")
            return 6
        proj = load_project(key)
        gib = asked_gib or class_peak(proj, args.cls)
        cpus = asked_cpus or class_peak(proj, args.cls, "cpus")
        b = budget(state, machine)
        for kind, need, free, limit, unit in (("memory", gib, b["freeGiB"], b["limitGiB"], "GiB"),
                                              ("cpu", cpus, b["freeCpus"], b["limitCpus"], "cores")):
            if need > free:
                why = f"needs {need:g} {unit}, {free:g} {unit} free of {limit:g} {unit} budget"
                print(json.dumps({kind: why, "held": [h["id"] for c in class_names(machine) for h in state[c]]}))
                log(f"refuse {args.cls} {args.coordinator} {args.id} {why}")
                return 4
        state["queue"][args.cls] = [q for q in queue if q["id"] != args.id]
        t = now()
        holders.append({
            "coordinator": args.coordinator,
            "holder": args.holder,
            "id": args.id,
            "worktree": args.worktree,
            "project": key,
            "gib": gib,
            "cpus": cpus,
            "commands": args.commands or entry.get("commands"),
            "grantedAt": t.isoformat(),
            "expiresAt": (t + dt.timedelta(minutes=args.minutes)).isoformat(),
        })
        if args.measure:
            os.makedirs(PEAKS, exist_ok=True)
            proc = subprocess.Popen(
                [sys.executable, "-I", os.path.abspath(__file__), "measure-peak", "--id", args.id, "--worktree", args.worktree],
                stdin=subprocess.DEVNULL, stdout=open(os.path.join(PEAKS, f"{args.id}.log"), "a"), stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            holders[-1]["measurePid"] = proc.pid
        save(state, machine)
        log(f"acquire {args.cls} {args.coordinator} {args.id} {args.holder} until {holders[-1]['expiresAt']} "
            f"({gib:g} GiB, {round(b['freeGiB'] - gib, 1)} GiB left; {cpus:g} cores, {round(b['freeCpus'] - cpus, 1)} cores left"
            + (", size accepted" if args.accept_size else "") + ")")
        return 0
    finally:
        unlock()


def pool_pick(state, cls, spec, entry=None):
    """The resource to assign: a free running one, else a stopped one; never one that is held or
    busy with an operation. Returns (resource, None), or (None, why): settling (one is busy;
    retry), exhausted (the pool is at max), none_free (no create command), create, or
    unavailable (the entry names one exact resource that cannot be assigned now).
    An entry that names a resource (wantResource) gets exactly that one, or unavailable: no other
    resource, no create. An entry with prefer takes a matching resource first (free, then
    stopped), then waits for a busy one, then creates one (it gets the preference), and only
    then takes a non-matching one."""
    entry = entry or {}
    pool = state["resources"][cls]
    held = {h.get("resource") for h in state[cls]}

    def free(r):
        return not r.get("op") and r["name"] not in held

    def first(states, match=None):
        for want in states:
            for r in pool:
                if r["state"] == want and free(r) and (match is None or match(r)):
                    return r
        return None

    if entry.get("wantResource"):
        r = find_resource(state, cls, entry["wantResource"])
        if r and r["state"] in ("free", "stopped") and free(r):
            return r, None
        return None, "unavailable"
    prefer = entry.get("prefer") or {}
    if prefer:
        r = first(("free", "stopped"), lambda r: prefer_matches(r.get("info"), prefer))
        if r:
            return r, None
        if any(r.get("op") or r["state"] in BUSY_STATES for r in pool):
            return None, "settling"
        if spec.get("create") and not (spec.get("max") and len(pool) >= spec["max"]):
            return None, "create"
    r = first(("free", "stopped"))
    if r:
        return r, None
    if any(r.get("op") or r["state"] in BUSY_STATES for r in pool):
        return None, "settling"
    if spec.get("max") and len(pool) >= spec["max"]:
        return None, "exhausted"
    return None, "create" if spec.get("create") else "none_free"


def pool_acquire_cmd(args):
    """Grant a pool class: assign a free resource, start a stopped one, or create one when
    none exists. The start or create command runs without the lock (it can take minutes);
    the entry keeps its queue place and the resource holds an op token meanwhile, so no other
    command touches it. After the command the token is checked again under the lock: a resource
    that was reset or removed meanwhile is not written. The holder record names the resource;
    the member's await-grant prints it."""
    cls, spec, machine = args.cls, pool_spec(args.cls), load_machine()
    lock()
    try:
        state = load()
        refused = acquire_checks(args, state, machine)
        if refused:
            print(refused[1])
            return refused[0]
        queued = next((q for q in state["queue"][cls] if q["id"] == args.id), None)
        entry = queued or {}
        expect = getattr(args, "auto_expect", None)
        if expect and (entry_tuple(entry) != expect or entry.get("hold") or entry.get("review")
                       or not auto_entry(entry, machine, load_roster(), cls)):
            print(json.dumps({"auto_stale": args.id}))
            return 7
        res, why = pool_pick(state, cls, spec, queued)
        if why in ("settling", "exhausted", "none_free", "unavailable"):
            listing = [{"name": r["name"], "state": r["state"]} for r in state["resources"][cls]]
            if why == "unavailable":
                print(json.dumps({"resource_unavailable": entry["wantResource"], "resources": listing}))
            else:
                print(json.dumps({"resources_" + why: listing}))
            return 3
        if res is None:
            res = {"name": f"pending-{args.id}", "info": {}}
            state["resources"][cls].append(res)
            action, token = "create", begin_op(res, "create", "creating", args.id)
        else:
            res["prior"] = res["state"]
            action = "start" if res["state"] == "stopped" else "assign"
            token = begin_op(res, action, "assigning", args.id)
        entry["assigning"] = {"create": "creating a resource", "start": f"starting {res['name']}", "assign": f"assigning {res['name']}"}[action]
        placeholder, info = res["name"], res.get("info")
        prefer = entry.get("prefer") or {}
        save(state, machine)
        log(f"resource {action} {cls} {placeholder} for={args.id}")
    finally:
        unlock()
    ok, out, err = True, "", ""
    if action == "create":
        ok, out, err = pool_run(spec["create"], pool_env(cls, "", None, args.id, args.worktree, prefer))
    elif action == "start" and spec.get("start"):
        ok, out, err = pool_run(spec["start"], pool_env(cls, placeholder, info, args.id, args.worktree, prefer))
    name, new_info = pool_info(out) if action == "create" and ok else (placeholder, info)
    if action == "create" and ok and name is None:
        ok, err = False, "create printed no JSON object with a valid name"
    lock()
    try:
        state, machine = load(), load_machine()
        pool = state["resources"][cls]
        res = op_current(state, cls, placeholder, token)
        entry = next((q for q in state["queue"][cls] if q["id"] == args.id), None)
        if entry:
            entry.pop("assigning", None)
        problem = None if ok else f"{action} failed: {err}"
        if res is None:
            problem = f"{placeholder} was reset or removed while {action} ran"
            if action == "create" and ok and not find_resource(state, cls, name):
                pool.append({"name": name, "info": new_info})  # the VM exists: keep it, free
                set_state(pool[-1], "free")
        elif ok and action == "create" and any(r["name"] == name and r is not res for r in pool):
            problem = f"create returned {name}, which the pool already has"
        if not problem and queued and entry is None:
            problem = f"{args.id} left the queue during the assignment"
        if not problem:
            refused = acquire_checks(args, state, machine)
            problem = refused and refused[1]
        if problem:
            if res is not None:
                if action == "create" and not ok:
                    pool.remove(res)
                elif not ok:
                    end_op(res, "failed")
                else:
                    if action == "create":
                        res.update(name=name, info=new_info)
                    res.pop("prior", None)
                    end_op(res, "free")
            save(state, machine)
            log(f"refuse {cls} {args.coordinator} {args.id} resource {problem}")
            print(json.dumps({"resource_error": problem}))
            return 8
        res.pop("prior", None)
        res.update(name=name, info=new_info)
        end_op(res, "free")
        key = (entry or queued or {}).get("project") or project_key(args.worktree)[0]
        t = now()
        state["queue"][cls] = [q for q in state["queue"][cls] if q["id"] != args.id]
        state[cls].append({
            "coordinator": args.coordinator, "holder": args.holder, "id": args.id, "worktree": args.worktree,
            "project": key, "gib": 0, "cpus": 0, "commands": args.commands or (queued or {}).get("commands"),
            "resource": name, "resourceInfo": new_info,
            "grantedAt": t.isoformat(), "expiresAt": (t + dt.timedelta(minutes=args.minutes)).isoformat(),
        })
        save(state, machine)
        log(f"acquire {cls} {args.coordinator} {args.id} {args.holder} until {state[cls][-1]['expiresAt']} resource={name}")
        return 0
    finally:
        unlock()


def resource_cmd(args):
    """list, add, mark and remove: the pool of a class. The caller does not hold the lock.
    add registers an existing resource; mark and remove change one that nobody holds and that
    has no operation running; remove --delete claims it (op delete, state deleting), runs the
    class's delete command without the lock, then removes it, or marks it failed when delete failed."""
    spec = pool_spec(args.cls)
    if not spec:
        print(f"{args.cls} has no pool; set one with config set-class {args.cls} --pool-create ...")
        return 2
    lock()
    try:
        state, machine = load(), load_machine()
        pool = state["resources"][args.cls]
        held = {h.get("resource"): h["id"] for h in state[args.cls]}
        if args.rcmd == "list":
            for r in pool:
                print(f"{r['name']} {r['state']}" + (f" held by {held[r['name']]}" if r["name"] in held else "") + f" {json.dumps(r.get('info', {}))}")
            return 0
        res = find_resource(state, args.cls, args.name)
        if args.rcmd == "add":
            if not RESOURCE_NAME.match(args.name):
                print(f"{args.name} is not a valid resource name")
                return 2
            if res:
                print(f"{args.name} is already in the {args.cls} pool")
                return 3
            res = {"name": args.name, "info": json.loads(args.info or "{}")}
            set_state(res, args.state)
            pool.append(res)
        elif res is None:
            print(f"{args.name} is not in the {args.cls} pool")
            return 3
        elif args.name in held:
            print(f"{args.name} is held by {held[args.name]}; wait for its release")
            return 3
        elif res.get("op") or res["state"] in BUSY_STATES:
            print(f"{args.name} is {res['state']} ({(res.get('op') or {}).get('kind', 'unknown')} running); wait for it to finish")
            return 3
        elif args.rcmd == "mark":
            set_state(res, args.state)
        elif args.delete and spec.get("delete"):
            token, info = begin_op(res, "delete", "deleting"), res.get("info")
            save(state, machine)
            unlock()
            try:
                ok, _, err = pool_run(spec["delete"], pool_env(args.cls, args.name, info))
            finally:
                lock()
            state, machine = load(), load_machine()
            res = op_current(state, args.cls, args.name, token)
            if res is None:
                print(f"{args.name} was reset while delete ran; check the VM, then add or remove it")
                return 8
            if not ok:
                end_op(res, "failed")
                save(state, machine)
                print(f"delete failed: {err}")
                log(f"resource delete-failed {args.cls} {args.name} by={args.by}")
                return 8
            state["resources"][args.cls].remove(res)
        else:
            pool.remove(res)
        save(state, machine)
        log(f"resource {args.rcmd} {args.cls} {args.name} by={args.by}")
        return 0
    finally:
        unlock()


# ---------------------------------------------------------------- host


def swapouts():
    m = re.search(r"Swapouts:\s+(\d+)", run(["vm_stat"]))
    return int(m.group(1)) if m else 0


def host_check():
    """Admission gate: two swap-out samples, load and the disk floor, with the machine
    config's numbers only. Returns (calm, line)."""
    cfg = load_machine()
    interval = int(cfg["swapIntervalS"])
    max_swap = int(cfg["maxSwapouts"])
    max_load = (os.cpu_count() or 1) * float(cfg["loadPerCore"])
    calm, parts = True, []
    for i in (1, 2):
        a = swapouts()
        time.sleep(interval)
        d = swapouts() - a
        parts.append(f"sample{i} swapouts/{interval}s={d}")
        calm = calm and d < max_swap
    load1 = os.getloadavg()[0]
    calm = calm and load1 < max_load
    free = shutil.disk_usage("/").free / 2**30
    disk = "blocked" if free < cfg["diskFloorGiB"] else "alarm" if free < cfg["diskAlarmGiB"] else "ok"
    calm = calm and disk != "blocked"
    m = re.search(r"(\d+)%", run(["memory_pressure", "-Q"]))
    parts += [
        f"load1={load1:.2f}", f"max_load={max_load:g}", f"disk_free_GiB={free:.1f}",
        f"disk_floor_GiB={cfg['diskFloorGiB']:g}", f"disk_alarm_GiB={cfg['diskAlarmGiB']:g}",
        f"disk={disk}", f"memory_free={m.group(1) + '%' if m else '?'}",
        f"verdict={'CALM' if calm else 'BUSY'}",
    ]
    return calm, " ".join(parts)


def host_check_cmd(args):
    calm, line = host_check()
    print(line)
    return 0 if calm else 1


def calm_wait_cmd(args):
    """Block until two calm samples, print one CALM line. Run in the background."""
    if args.settle:
        time.sleep(args.settle)
    while True:
        calm, line = host_check()
        if calm:
            print(f"CALM {time.strftime('%H:%M:%SZ', time.gmtime())} {line}", flush=True)
            return 0
        time.sleep(args.retry)


def measure_peak_cmd(args):
    """While ID holds a lease, sum RSS and %CPU of processes working in the worktree; keep
    the max of each in peaks/<id>.gib and peaks/<id>.cpus for release. RSS counts shared
    pages twice, and %CPU is a short decaying average, so both err high."""
    os.makedirs(PEAKS, exist_ok=True)
    peak = {"gib": 0.0, "cpus": 0.0}
    time.sleep(2)
    while any(h["id"] == args.id for c in class_names() for h in load()[c]):
        pids = worktree_pids(args.worktree)
        if pids:
            rss, cpu = 0, 0.0
            for line in run(["ps", "-o", "rss=,%cpu=", "-p", ",".join(pids)]).splitlines():
                f = line.split()
                if len(f) == 2 and f[0].isdigit():
                    rss += int(f[0])
                    cpu += float(f[1].replace(",", "."))
            for kind, value in (("gib", round(rss / 2**20, 1)), ("cpus", round(cpu / 100, 1))):
                if value > peak[kind]:
                    peak[kind] = value
                    with open(os.path.join(PEAKS, f"{args.id}.{kind}"), "w") as out:
                        out.write(str(value))
        time.sleep(args.interval)
    print(f"peak {args.id} {peak['gib']} GiB {peak['cpus']} cores")
    return 0


def drain_check_cmd(args):
    """Report what a released lease left behind: processes working in the worktree (with
    their listeners, except agent session processes), listeners on the given ports, and
    processes matching each --process pattern (for example a tunnel or a browser started
    for the run). Exit 0 when nothing is left, 1 otherwise. It only reports; it never kills."""
    left = drain(args.worktree, args.port or [], args.process or [])
    for line in left:
        print(f"  {line}")
    print(f"{'drained' if not left else 'not drained'}: {len(left)} left for {args.worktree}")
    return 0 if not left else 1


def prs_cmd(args):
    """Open PRs on the machine whose changed files match --path: the PRs of members (with
    their repo), of prs-<C>.txt watch lists, and of coordinators (with --repo). One gh
    call per PR, eight at a time. Exit 3 when none matches."""
    import fnmatch
    from concurrent.futures import ThreadPoolExecutor
    roster = load_roster()
    owners = {}
    for coord, members in roster["members"].items():
        for m in members:
            for n in m.get("prs", []) if m.get("repo") else []:
                owners.setdefault((m["repo"], n), []).append(f"{coord}/{m['name']}")
    for path in sorted(p for p in os.listdir(DIR) if p.startswith("prs-") and p.endswith(".txt")):
        for raw in open(os.path.join(DIR, path)).read().splitlines():
            repo, _, n = (raw.split() or [""])[0].rpartition("#")
            if repo and n.isdigit():
                owners.setdefault((repo, int(n)), []).append(path[4:-4])
    known = {n for _, n in owners}
    for coord, c in roster["coordinators"].items():
        for n in c.get("prs", []) if args.repo else []:
            if n not in known:
                owners.setdefault((args.repo, n), []).append(coord)
    refs = [r for r in owners if not args.repo or r[0] == args.repo]

    def hit(path):
        return any(fnmatch.fnmatch(path, g) or path.startswith(g.rstrip("/") + "/") for g in args.path)

    def view(ref):
        r = subprocess.run(["gh", "pr", "view", str(ref[1]), "--repo", ref[0], "--json", "state,title,files"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            return ref, None, " ".join(r.stderr.split())[:120]
        d = json.loads(r.stdout)
        return ref, d, [f["path"] for f in d.get("files", []) if hit(f["path"])]
    found = 0
    with ThreadPoolExecutor(8) as pool:
        for (repo, n), d, files in pool.map(view, refs):
            if d is None:
                print(f"{repo}#{n} error {files}", file=sys.stderr)
            elif d["state"] == "OPEN" and files:
                found += 1
                print(f"{repo}#{n} ({', '.join(dict.fromkeys(owners[(repo, n)]))}) {d['title'][:70]}")
                for f in files[:10]:
                    print(f"  {f}")
                if len(files) > 10:
                    print(f"  ... {len(files) - 10} more")
    if not found:
        print(f"no open PR among {len(refs)} touches {' '.join(args.path)}")
    return 0 if found else 3


# ---------------------------------------------------------------- watchers and install


def follow(paths):
    """Yield (path, line) for lines appended to the files after start, and (None, None)
    after each sweep so the caller can poll state."""
    files = {}
    for p in paths:
        open(p, "a").close()
        f = open(p)
        f.seek(0, os.SEEK_END)
        files[p] = f
    while True:
        for p, f in files.items():
            for line in f.readlines():
                if line.strip():
                    yield p, line.strip()
        yield None, None
        time.sleep(2)


def own_heads(me):
    """{CLASS: entry} for each class whose first ready queue entry is me's (by the
    entry's coordinator field, so a transferred member's old ID prefix does not matter)."""
    state, heads = load(), {}
    for c in class_names():
        ready = [q for q in state["queue"][c] if not q.get("hold")]
        if ready and ready[0]["coordinator"] == me:
            heads[c] = ready[0]
    return heads


def entry_tuple(entry):
    """The fields an automatic grant is made from; it is granted only if they are unchanged."""
    return tuple(entry.get(k) for k in ("id", "coordinator", "holder", "minutes", "gib", "cpus", "commands", "worktree"))


def auto_entry(entry, machine, roster, cls):
    """True when entry's class or its member's stream has autoAcquire on."""
    if registry(machine)[cls].get("autoAcquire"):
        return True
    name = entry["holder"].partition(" ")[0]
    m = next((x for x in roster["members"].get(entry["coordinator"], []) if x["name"] == name), None)
    return bool(m and (roster["streams"].get(m.get("stream")) or {}).get("autoAcquire"))


def watch_auto(me):
    """Grant my head entries by running acquire, for classes or streams with autoAcquire on.
    Prints AUTO-GRANTED or AUTO-REFUSED when an entry's outcome changes. Exit 2 (over the
    limit) and 6 (undersized) wait for the coordinator: this loop never splits a run or
    accepts a size. Exit 7 means the entry changed during the host check; the final check
    under the lock revalidates the entry, its hold and review state and the auto opt-in.
    Other refusals retry on the next pass."""
    seen = {}
    while True:
        machine, roster = load_machine(), load_roster()
        heads = own_heads(me)
        for c, q in heads.items():
            if not auto_entry(q, machine, roster, c):
                continue
            key = (q["id"], q.get("minutes"), q.get("gib"), q.get("cpus"))
            if q.get("review"):
                if seen.get(c) != (key, "review"):
                    print(f"AUTO-SKIPPED {c} {q['id']}: marked for review; grant it with acquire", flush=True)
                    seen[c] = (key, "review")
                continue
            if seen.get(c, (None,))[0] == key and seen[c][1] in (2, 6):
                continue
            if not q.get("minutes") or not q.get("worktree"):
                if seen.get(c) != (key, "incomplete"):
                    print(f"AUTO-REFUSED {c} {q['id']}: entry needs minutes and worktree; set them with wait, then acquire", flush=True)
                    seen[c] = (key, "incomplete")
                continue
            ns = argparse.Namespace(cls=c, coordinator=me, holder=q["holder"], id=q["id"], worktree=q["worktree"],
                                    minutes=q["minutes"], gib=q.get("gib"), cpus=q.get("cpus"), accept_size=False,
                                    commands=q.get("commands"), measure=True, auto_expect=entry_tuple(q))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = acquire_cmd(ns)
            if code == 0:
                print(f"AUTO-GRANTED {c} {q['id']}", flush=True)
                seen.pop(c, None)
            elif seen.get(c) != (key, code):
                print(f"AUTO-REFUSED {c} {q['id']} exit {code}: {buf.getvalue().strip()[:300]}", flush=True)
                seen[c] = (key, code)
        time.sleep(2)


def watch_pool(me, once=False):
    """Once a minute, for each pool class: stop an unheld running resource idle for stopAfterMinutes
    (release never stops: a stop is costly, and the next grant may come soon); reset a resource
    stuck in a busy state past POOL_STUCK_MINUTES whose operation's process is gone (a crashed
    create, start, stop or delete; a live operation is never reset); delete an unheld resource idle
    for the class's idleDeleteHours (needs a delete command); print POOL-EXPIRED once per lease that
    expired over an hour ago while still holding a resource (never taken back). Each step claims the
    resource with an op token first, so two watchers or a manual command never run the same step."""
    warned = set()
    while True:
        t, machine = now(), load_machine()
        for cls, spec in registry(machine).items():
            pool = spec.get("pool")
            if not pool:
                continue
            idle, to_stop = [], []
            lock()
            try:
                state = load()
                held = {h.get("resource") for h in state[cls]}
                for r in list(state["resources"][cls]):
                    age = (t - dt.datetime.fromisoformat(r.get("since") or t.isoformat())).total_seconds() / 60
                    op = r.get("op") or {}
                    if (op or r["state"] in BUSY_STATES) and age > POOL_STUCK_MINUTES and not (op.get("pid") and pid_alive(op["pid"])):
                        if r["state"] == "creating":
                            state["resources"][cls].remove(r)
                        else:
                            end_op(r, {"assigning": r.get("prior") or "free", "deleting": "failed"}.get(r["state"], "free"))
                            r.pop("prior", None)
                        save(state, machine)
                        log(f"resource reset {cls} {r['name']} stuck {age:.0f} min by={me}")
                        print(f"POOL-RESET {cls} {r['name']}: stuck {age:.0f} min", flush=True)
                    elif op or r["state"] in BUSY_STATES or r["name"] in held:
                        continue
                    elif r["state"] in ("free", "stopped") and pool.get("idleDeleteHours") and pool.get("delete") \
                            and age > pool["idleDeleteHours"] * 60:
                        idle.append(r["name"])
                    elif r["state"] == "free" and pool.get("stop") and pool.get("stopAfterMinutes") \
                            and age > pool["stopAfterMinutes"]:
                        to_stop.append(r["name"])
                for h in state[cls]:
                    over = (t - dt.datetime.fromisoformat(h["expiresAt"])).total_seconds() / 60
                    if h.get("resource") and over > 60 and (cls, h["id"]) not in warned:
                        warned.add((cls, h["id"]))
                        print(f"POOL-EXPIRED {cls} {h['id']} ({h['coordinator']}): lease expired {over:.0f} min ago, "
                              f"still holds {h['resource']}; ask the holder to release", flush=True)
            finally:
                unlock()
            for name in to_stop:
                if stop_resource(cls, name):
                    print(f"POOL-STOPPED {cls} {name}", flush=True)
            for name in idle:
                ns = argparse.Namespace(rcmd="remove", cls=cls, name=name, by=me, delete=True, state="free", info=None)
                code = resource_cmd(ns)
                print(f"POOL-DELETED {cls} {name}" if code == 0 else f"POOL-DELETE-FAILED {cls} {name} exit {code}", flush=True)
        if once:
            return
        time.sleep(60)


def watch_inbox(me):
    """Messages to me or to all (inbox.jsonl only; it never reads events.log), and:
    HEAD when an entry of mine becomes the first ready entry of its class (acquire it),
    polled from the queue state."""
    heads = {}

    def report_heads():
        nonlocal heads
        now_heads = own_heads(me)
        for c, q in now_heads.items():
            if (heads.get(c) or {}).get("id") != q["id"]:
                prio = f" priority {q['priority']}" if q.get("priority") else ""
                print(f"HEAD {c} {q['id']}{prio} — {q['holder'][:60]}: acquire it when the host and budget allow", flush=True)
        heads = now_heads
    report_heads()
    for path, line in follow([INBOX]):
        if path is None:
            report_heads()
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            print(f"INBOX {line}", flush=True)
            continue
        if rec.get("from") != me and rec.get("to") in (None, me):
            print(f"INBOX {rec.get('from')}: {rec.get('message')}", flush=True)


def watch_expiry():
    """Each lease past its expiry, once per expiry, with left=N: the processes its run still has in
    its worktree (as drain-check counts them). An expired lease still holds its slot."""
    seen = set()
    while True:
        t = now()
        state = load()
        for c in class_names():
            for h in state[c]:
                key = (c, h["id"], h["expiresAt"])  # an extended lease can expire again
                if key not in seen and dt.datetime.fromisoformat(h["expiresAt"]) < t:
                    seen.add(key)
                    left = len(drain(h["worktree"])) if h.get("worktree") else "?"
                    print(f'{c} {h["id"]} ({h["coordinator"]}) expired at {h["expiresAt"][11:16]}Z left={left} holder={h["holder"][:60]}', flush=True)
        time.sleep(60)


def watch_prs(me):
    """State changes of the PRs listed in prs-<me>.txt ("owner/repo#123" per line), read from the
    shared poller's prs-state.json and prs-events.log (the dashboard server polls, with ETags).
    Prints each PR's current state first, then each change. PR-WATCHER down when the poller stops."""
    path = os.path.join(DIR, f"prs-{me}.txt")
    open(path, "a").close()

    def mine():
        return {(raw.split() or [""])[0] for raw in open(path).read().splitlines()}
    state = read_json(PRS_STATE) or {}
    for ref, rec in (state.get("prs") or {}).items():
        if ref in mine() and rec.get("line"):
            print(f"PR {ref} {rec['line']}", flush=True)
    down = False
    for p, line in follow([PRS_EVENTS]):
        if p is None:
            at = (read_json(PRS_STATE) or {}).get("at", 0)
            stale = time.time() - at > 3 * ((read_json(PRS_STATE) or {}).get("pollS") or PRS_POLL_S) + 60
            if stale != down:
                down = stale
                print("PR-WATCHER down: no PR poll for a while; start `python3 -I <skill>/scripts/server.py`" if down
                      else "PR-WATCHER up", flush=True)
        elif line.split(" ", 2)[1:2] and line.split(" ", 2)[1] in mine():
            print(line, flush=True)


def cloud_state(task):
    """One line of state for a CodeRabbit cloud task, from the last record of `coderabbit code show --agent`."""
    try:
        r = subprocess.run(["coderabbit", "code", "show", task, "--agent"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120,
                           env={**os.environ, "CODERABBIT_CLI_DISABLE_AUTO_UPDATE": "true"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"error {exc}"[:200]
    last = None
    for raw in r.stdout.splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("status") != "beta_notice":
            last = rec
    if not last:
        return "error " + " ".join((r.stderr or "no record").split())[:200]
    if last.get("type") != "complete":
        return f"{last.get('type')} {last.get('status') or last.get('action')}: {' '.join(str(last.get('message', '')).split())[:160]}"
    t = last.get("task") or {}

    def val(v):
        return json.dumps(v, separators=(",", ":"))[:80] if isinstance(v, (dict, list)) else str(v)
    keys = ("status", "turnStatus", "patchStatus", "planStatus", "deliveryStatus", "pendingReason", "cancellationPending")
    parts = [f"{k}={val(t[k])}" for k in keys if t.get(k) not in (None, "", False)]
    if (t.get("prHealth") or {}).get("state"):
        parts.append(f"pr={t['prHealth']['state']}")  # watch prs reports the rest; other PR health fields flap
    goal = (t.get("goalState") or {}).get("goal") or {}
    if goal.get("status"):
        parts.append(f"goal={goal['status']}")
    return " ".join(parts) or "shown"


def watch_cloud(me, interval):
    """State changes of the CodeRabbit cloud tasks in cloud-<me>.txt ("<task id or URL> <member>" per line).
    Cloud tasks cannot run the puppet skill or send messages, so this is their only report."""
    path = os.path.join(DIR, f"cloud-{me}.txt")
    open(path, "a").close()
    last = {}
    while True:
        for raw in open(path).read().splitlines():
            f = raw.split()
            if not f or f[0].startswith("#"):
                continue
            line = cloud_state(f[0].rstrip("/").rsplit("/", 1)[-1])
            if last.get(f[0]) != line:
                print(f"CLOUD {f[0]} {f[1] if len(f) > 1 else '-'} {line}", flush=True)
                last[f[0]] = line
        time.sleep(interval)


def watch_cmd(args):
    try:
        if args.what == "inbox":
            watch_inbox(args.me)
        elif args.what == "expiry":
            watch_expiry()
        elif args.what == "cloud":
            watch_cloud(args.me, args.interval)
        elif args.what == "auto":
            watch_auto(args.me)
        elif args.what == "pool":
            watch_pool(args.me)
        else:
            watch_prs(args.me)
    except KeyboardInterrupt:
        return 0
    return 0


def install_cmd(args):
    """Copy the helpers into the state dir when absent. All or nothing: when a live copy
    differs, print every diff and install none, so live files never mix versions; with
    --replace, replace every differing copy, only for the update proposal of exactly these
    files that the user approved and every live coordinator agreed, while no lease is
    granted. The state lock makes it the only install. After a full install, remove obsolete
    helpers. Each run records this skill copy as the source, so later runs can warn when
    an update is due; a refused --replace records nothing."""
    here = os.path.dirname(os.path.realpath(__file__))
    if os.path.realpath(DIR) == here:
        print("this is the live copy")
        return 0
    if not args.replace:
        return install_files(args, here)
    if not args.by:
        print("install --replace needs --by <coordinator>")
        return 2
    lock()
    try:
        proposal = read_json(UPDATE)
        why = update_blockers(proposal, load_roster(), load(), args.ignore_leases)
        if proposal and proposal["files"] != file_hashes(here):
            why.append(f"this copy is not the proposed update {proposal['digest']}; propose it with update propose")
        if why:
            print("not installed:\n  " + "\n  ".join(why))
            return 3
        code = install_files(args, here)
        proposal["installed"] = {"by": args.by, "at": now().isoformat()}
        write_json(UPDATE, proposal)
        log(f"install {proposal['digest']} by={args.by}")
        note(args.by, f"installed helper update {proposal['digest']} ({proposal.get('git') or 'no git'}) from {here}: "
             + " ".join(f"{n}={h[:12]}" for n, h in proposal["files"].items()))
        announce(args.by, f"INSTALLED helper update {proposal['digest']} by {args.by}. Restart a dashboard you own.")
        return code
    finally:
        unlock()


def install_files(args, here):
    import difflib
    write_json(SOURCE, {"path": here, "at": now().isoformat()})
    plan, differs = [], False
    for name in FILES:
        src, dst = os.path.join(here, name), os.path.join(DIR, name)
        new = open(src).read()
        if not os.path.exists(dst):
            plan.append((dst, new))
            continue
        old = open(dst).read()
        if old == new:
            print(f"up to date {dst}")
            continue
        if args.replace:
            plan.append((dst, new))
            continue
        differs = True
        print(f"DIFFERS {dst} (not overwritten; run update propose, and install --replace --by C once the user approves and every live coordinator agrees)")
        sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), dst, src, n=1))
    if differs:
        if plan:
            print("nothing installed (" + ", ".join(os.path.basename(d) for d, _ in plan) + " too): every live copy must match first")
        return 2
    for dst, new in plan:
        tmp = f"{dst}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            f.write(new)
        os.chmod(tmp, 0o755 if dst.endswith(("coordinator.py", "puppet.py")) else 0o644)
        verb = "replaced" if os.path.exists(dst) else "installed"
        os.replace(tmp, dst)  # atomic: a session that starts now reads the old or the new file, never half of one
        print(f"{verb} {dst}")
    for name in OBSOLETE:
        path = os.path.join(DIR, name)
        if os.path.exists(path):
            os.remove(path)
            print(f"removed obsolete {path}")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--brief", action="store_true")
    dc = sub.add_parser("decision")
    dsub = dc.add_subparsers(dest="dcmd", required=True)
    da = dsub.add_parser("add")
    da.add_argument("--by", required=True)
    da.add_argument("--text", required=True)
    da.add_argument("--task")
    da.add_argument("--href")
    da.add_argument("--option", action="append", help="a suggested answer; repeat for each (at most 4)")
    da.add_argument("--scope", choices=(MACHINE,), help="machine: one question for every coordinator, answered once")
    dn = dsub.add_parser("answer")
    dn.add_argument("--by", required=True)
    dn.add_argument("--id", required=True)
    dn.add_argument("--choice", type=int, required=True, help="the option number, from 1")
    dn.add_argument("--notify", action="store_true", help="tell the coordinator (sender: dashboard)")
    dl = dsub.add_parser("clear")
    dl.add_argument("--by", required=True)
    dl.add_argument("--task")
    dl.add_argument("--all", action="store_true")
    dl.add_argument("--scope", choices=(MACHINE,), help="clear your machine-scope decisions")
    sub.add_parser("capacity")
    a = sub.add_parser("acquire")
    a.add_argument("cls", metavar="CLASS")
    a.add_argument("--coordinator", required=True)
    a.add_argument("--holder", required=True)
    a.add_argument("--id", required=True)
    a.add_argument("--worktree", required=True)
    a.add_argument("--minutes", type=int, required=True)
    a.add_argument("--gib", type=float, help="expected peak GiB; default: queue entry estimate, then class peak")
    a.add_argument("--cpus", type=float, help="expected peak cores; default: queue entry estimate, then class peak")
    a.add_argument("--accept-size", action="store_true", help="grant a request below the observed peak: the member's reason fits")
    a.add_argument("--commands", help="the exact granted commands; default: the queue entry's")
    a.add_argument("--measure", action="store_true", help="start measure-peak in the background for this lease")
    rs = sub.add_parser("resource", help="the resources of a pool class: list, add, mark, remove")
    rs.add_argument("rcmd", choices=("list", "add", "mark", "remove"))
    rs.add_argument("cls", metavar="CLASS")
    rs.add_argument("--by", required=True)
    rs.add_argument("--name", help="the resource; not needed for list")
    rs.add_argument("--state", choices=("free", "stopped", "failed"), default="free", help="add: the state it starts in; mark: the new state")
    rs.add_argument("--info", help="add: a JSON object shown to the holder, for example the host to connect to")
    rs.add_argument("--delete", action="store_true", help="remove: run the class's delete command first")
    w = sub.add_parser("wait")
    w.add_argument("cls", metavar="CLASS")
    w.add_argument("--coordinator", help="required for a new entry")
    w.add_argument("--holder", help="required for a new entry; an existing entry keeps its holder text unless given")
    w.add_argument("--id", required=True)
    w.add_argument("--minutes", type=int)
    w.add_argument("--gib", type=float)
    w.add_argument("--cpus", type=float)
    w.add_argument("--commands", help="the exact commands the lease would cover")
    w.add_argument("--worktree", help="sets the project whose class peak applies")
    w.add_argument("--priority", type=int, help="higher goes first; default: the task's priority, else 0")
    w.add_argument("--front", action="store_true", help="re-queue at the head (only for a run aborted by the coordinator)")
    w.add_argument("--prefer", action="append", metavar="KEY=VALUE", help="pool class: take a resource whose info matches first; the create command gets MOP_PREFER_<KEY>")
    w.add_argument("--resource", help="pool class: grant exactly this resource, or exit 3; never another one, never a new one")
    for name in ("unwait", "up", "move"):
        u = sub.add_parser(name)
        u.add_argument("cls", metavar="CLASS")
        u.add_argument("--id", required=True)
        if name == "move":
            u.add_argument("--to", type=int, required=True, help="position among ready entries, from 1")
        u.add_argument("--notify", action="store_true", help="tell each affected coordinator (sender: dashboard)")
    pk = sub.add_parser("park")
    pk.add_argument("--coordinator", required=True)
    pk.add_argument("--name", required=True)
    pk.add_argument("--until", help="deadline YYYY-MM-DD; after it the task returns to Needs you as Revisit")
    pk.add_argument("--notify", action="store_true", help="tell the coordinator (sender: dashboard)")
    upk = sub.add_parser("unpark")
    upk.add_argument("--coordinator", required=True)
    upk.add_argument("--name", required=True)
    upk.add_argument("--notify", action="store_true", help="tell the coordinator (sender: dashboard)")
    x = sub.add_parser("extend")
    x.add_argument("cls", metavar="CLASS")
    x.add_argument("--id", required=True)
    x.add_argument("--minutes", type=int, required=True)
    for name in ("hold", "ready"):
        h = sub.add_parser(name)
        h.add_argument("cls", metavar="CLASS")
        h.add_argument("--id", required=True)
        if name == "hold":
            h.add_argument("--reason", help="shown to the member as HELD <reason>")
            h.add_argument("--review", action="store_true",
                           help="keep the queue place but never auto-acquire this entry; only you grant it")
    dn = sub.add_parser("deny")
    dn.add_argument("cls", metavar="CLASS")
    dn.add_argument("--id", required=True)
    dn.add_argument("--by", required=True)
    dn.add_argument("--reason", required=True, help="shown to the member as DENIED <reason>")
    adm = sub.add_parser("admission")
    asub = adm.add_subparsers(dest="acmd", required=True)
    ah = asub.add_parser("hold")
    ah.add_argument("cls", metavar="CLASS")
    ah.add_argument("--by", required=True)
    ah.add_argument("--reason", required=True)
    acl = asub.add_parser("clear")
    acl.add_argument("cls", metavar="CLASS")
    acl.add_argument("--by", required=True)
    acl.add_argument("--reason", help="for example what was cleaned up")
    pp = sub.add_parser("prs")
    pp.add_argument("--path", action="append", required=True, help="a glob or a directory prefix; repeat for more")
    pp.add_argument("--repo", help="only this owner/repo; also the repo for coordinator PRs that no member lists")
    cf = sub.add_parser("config")
    csub = cf.add_subparsers(dest="ccmd", required=True)
    cs = csub.add_parser("show")
    cs.add_argument("--project-root")
    cm = csub.add_parser("set-machine")
    cm.add_argument("--by", required=True)
    cm.add_argument("--reason", help="why, for example the user's words")
    cm.add_argument("--reserve-gib", type=float)
    cm.add_argument("--reserve-cpus", type=float, help="cores kept free of leases")
    cm.add_argument("--size-margin", type=float, help="fraction a request may be below the observed peak (0.25 = 25%%)")
    cm.add_argument("--disk-floor-gib", type=float, help="below this many GiB free, no lease is granted")
    cm.add_argument("--disk-alarm-gib", type=float, help="below this many GiB free, the host check raises the disk alarm")
    cm.add_argument("--max-swapouts", type=int)
    cm.add_argument("--swap-interval-s", type=int)
    cm.add_argument("--load-per-core", type=float)
    cm.add_argument("--dashboard-port", type=int)
    cm.add_argument("--max-slots", action="append", help="CLASS=N hard cap; N=0 removes it")
    cpj = csub.add_parser("set-project")
    cpj.add_argument("--by", required=True)
    cpj.add_argument("--reason", help="why, for example the user's words")
    cpj.add_argument("--root", required=True)
    cpj.add_argument("--name")
    cpj.add_argument("--base-branch")
    cpj.add_argument("--merge-method", choices=("merge", "squash", "rebase", "auto"),
                     help="auto: run gh pr merge --auto with no method flag (merge queue or repository default)")
    cpj.add_argument("--leases-default", choices=("on", "off"))
    cpj.add_argument("--class", dest="pcls", metavar="CLASS")
    cpj.add_argument("--max-minutes", type=int)
    cpj.add_argument("--minutes", choices=("learn", "fixed"), help="learn: suggest a request length from recorded run times; the limit stays --max-minutes")
    cpj.add_argument("--peak", choices=("learn", "fixed"))
    cpj.add_argument("--default-gib", type=float)
    cpj.add_argument("--default-cpus", type=float)
    sc = csub.add_parser("set-class")
    sc.add_argument("--by", required=True)
    sc.add_argument("--reason", help="why, for example the user's words")
    sc.add_argument("name", metavar="CLASS")
    sc.add_argument("--description")
    sc.add_argument("--default-gib", type=float, help="expected peak; 0 = not memory-bound")
    sc.add_argument("--default-cpus", type=float, help="expected peak cores; 0 = not CPU-bound")
    sc.add_argument("--max-minutes", type=int)
    sc.add_argument("--settle", action="append", help="OTHER=SECONDS: after a grant of this class, OTHER waits (0 removes)")
    sc.add_argument("--pool-create", help="makes a class a pool of named resources: a shell command that creates one and prints "
                    'a JSON object {"name": ..., ...}; "" removes it')
    sc.add_argument("--pool-start", help="shell command that starts a stopped resource (reads MOP_RESOURCE); \"\" removes it")
    sc.add_argument("--pool-stop", help="shell command that stops a released resource; \"\" removes it")
    sc.add_argument("--pool-delete", help="shell command that deletes a resource (resource remove --delete); \"\" removes it")
    sc.add_argument("--pool-idle-delete-hours", type=float, help="`watch pool` deletes an unheld resource idle this long (needs a delete command); 0 = never")
    sc.add_argument("--pool-stop-after-minutes", type=float, help="`watch pool` runs the stop command on an unheld running resource idle this long; 0 = never stop")
    sc.add_argument("--pool-max", type=int, help="most resources the pool may hold; 0 = no cap")
    sc.add_argument("--auto-acquire", choices=("on", "off"), help="on: `watch auto` grants this class's head entry when every gate passes")
    rc = csub.add_parser("remove-class")
    rc.add_argument("--by", required=True)
    rc.add_argument("--reason", help="why, for example the user's words")
    rc.add_argument("name", metavar="CLASS")
    cp = csub.add_parser("propose", help="class defaults from your observations; applies when every live coordinator agrees")
    cp.add_argument("--by", required=True)
    cp.add_argument("name", metavar="CLASS")
    cp.add_argument("--project-root", help="one project's class; default: the machine class registry")
    cp.add_argument("--default-gib", type=float, help="0 = no memory charge")
    cp.add_argument("--default-cpus", type=float, help="0 = no core charge")
    cp.add_argument("--max-minutes", type=int, help="0 = no limit")
    cp.add_argument("--reason", required=True, help="your observations, for example sizes figures and recent release peaks")
    for name in ("agree", "object"):
        cv = csub.add_parser(name)
        cv.add_argument("--by", required=True)
        cv.add_argument("--id", required=True)
        cv.add_argument("--text", required=name == "object", help="the reason (required to object)")
    csub.add_parser("proposals", help="open class proposals and who has not agreed")
    ck = csub.add_parser("project-key")
    ck.add_argument("path")
    m = sub.add_parser("say")
    m.add_argument("--from", dest="sender", required=True)
    m.add_argument("--message", required=True)
    m.add_argument("--to", help="coordinator or member name; omit to reach every live coordinator")
    m.add_argument("--no-direct", action="store_true", help="append to inbox.jsonl only")
    me = sub.add_parser("memory")
    mesub = me.add_subparsers(dest="mcmd", required=True)
    add_read_commands(sub, memory=mesub)
    ma = mesub.add_parser("add")
    ma.add_argument("--by", required=True)
    ma.add_argument("--text", required=True)
    ma.add_argument("--kind", choices=("rule", "note"), default="rule")
    ma.add_argument("--project-root")
    ma.add_argument("--reason", help="why, for example the user's words")
    mu = mesub.add_parser("update")
    mu.add_argument("--by", required=True)
    mu.add_argument("--id", required=True)
    mu.add_argument("--text", required=True, help="the full new text; the ID stays")
    mu.add_argument("--kind", choices=("rule", "note"))
    mu.add_argument("--project-root")
    mu.add_argument("--reason", help="why, for example the user's words")
    mr2 = mesub.add_parser("remove")
    mr2.add_argument("--by", required=True)
    mr2.add_argument("--id", required=True)
    mr2.add_argument("--project-root")
    mr2.add_argument("--reason", help="why, for example the user's words")
    nt = sub.add_parser("note")
    nt.add_argument("--by", required=True)
    nt.add_argument("--text", required=True)
    nt.add_argument("--pr", type=int)
    co = sub.add_parser("coordinate")
    co.add_argument("--name", required=True)
    co.add_argument("--tool", choices=TOOLS, required=True)
    co.add_argument("--session-id", required=True)
    co.add_argument("--focus", required=True)
    co.add_argument("--pr", type=int, nargs="+", action="extend", help="PR numbers, several allowed (--pr 1 2 or --pr 1 --pr 2)")
    co.add_argument("--takeover", action="store_true", help="replace a live coordinator of the same name (user approval only)")
    co.add_argument("--general", action="store_true", help="general-purpose coordinator with no fixed scope")
    hb = sub.add_parser("heartbeat")
    hb.add_argument("--name", required=True)
    hb.add_argument("--focus")
    hb.add_argument("--pr", type=int, nargs="+", action="extend", help="PR numbers, several allowed (--pr 1 2 or --pr 1 --pr 2)")
    hb.add_argument("--status", choices=("active", "idle"))
    rs = sub.add_parser("resign")
    rs.add_argument("--name", required=True)
    ls = sub.add_parser("leases")
    ls.add_argument("mode", choices=("on", "off"))
    ls.add_argument("--by", required=True)
    mb = sub.add_parser("member")
    msub = mb.add_subparsers(dest="mcmd", required=True)
    for name in ("add", "update"):
        mx = msub.add_parser(name)
        mx.add_argument("--coordinator", required=True)
        mx.add_argument("--name", required=True)
        mx.add_argument("--tool", choices=MEMBER_TOOLS)
        mx.add_argument("--session-id")
        mx.add_argument("--worktree")
        mx.add_argument("--task")
        mx.add_argument("--pr", type=int, nargs="+", action="extend", help="PR numbers, several allowed (--pr 1 2 or --pr 1 --pr 2); replaces the PR list")
        mx.add_argument("--repo", help="owner/repo for PR links; default: the worktree's GitHub origin")
        mx.add_argument("--status", choices=("pending", "active", "paused", "done"))
        mx.add_argument("--phase")
        mx.add_argument("--kind", choices=("ok", "work", "warn", "done"))
        mx.add_argument("--latest")
        mx.add_argument("--session", help="deep link for the dashboard; default: derived from --tool and --session-id")
        mx.add_argument("--stream", help='stream slug; "" clears it')
        mx.add_argument("--priority", type=int, help="task priority: 0 default, higher first, below 0 for background work")
        mx.add_argument("--parent", help="the member that started this one (JOIN parent field)")
    mt = msub.add_parser("transfer")
    mt.add_argument("--coordinator", required=True, help="the member's coordinator (you)")
    mt.add_argument("--name", required=True)
    mt.add_argument("--to", help="the receiving live coordinator")
    mt.add_argument("--note", help="the handoff note path")
    mt.add_argument("--cancel", action="store_true", help="withdraw the offer")
    mac = msub.add_parser("accept")
    mac.add_argument("--coordinator", required=True, help="the receiver (you)")
    mac.add_argument("--name", required=True)
    mac.add_argument("--from", dest="source", required=True, help="the offering coordinator")
    mr = msub.add_parser("remove")
    mr.add_argument("--coordinator", required=True)
    mr.add_argument("--name", required=True)
    ms = msub.add_parser("stale")
    ms.add_argument("--coordinator", required=True)
    ms.add_argument("--minutes", type=int, default=30)
    en = sub.add_parser("enroll")
    en.add_argument("--coordinator", required=True)
    en.add_argument("--by", help="member on whose behalf you start the task (it becomes the parent); default: the coordinator")
    en.add_argument("--task", required=True)
    en.add_argument("--name")
    en.add_argument("--pr", type=int, nargs="+", action="extend", help="PR numbers, several allowed (--pr 1 2 or --pr 1 --pr 2)")
    en.add_argument("--stream", help="stream slug (stream add)")
    en.add_argument("--priority", type=int, help="task priority: 0 default, higher first, below 0 for background work")
    ch = sub.add_parser("child")
    ch.add_argument("--coordinator", required=True)
    ch.add_argument("--parent", required=True, help="the member that sent CHILD TASK STARTED")
    ch.add_argument("--task", required=True)
    ch.add_argument("--tool", required=True, choices=MEMBER_TOOLS)
    ch.add_argument("--session-id", required=True, help="the child's session or thread id from the start confirmation")
    ch.add_argument("--pr", type=int, nargs="+", action="extend", help="PR numbers, several allowed (--pr 1 2 or --pr 1 --pr 2)")
    ch.add_argument("--stream", help="stream slug (stream add)")
    sm = sub.add_parser("stream")
    ssub = sm.add_subparsers(dest="scmd", required=True)
    for name in ("add", "update", "close", "reopen"):
        sx = ssub.add_parser(name)
        sx.add_argument("--coordinator", required=True)
        sx.add_argument("--name", required=True)
        if name in ("add", "update"):
            sx.add_argument("--label", help="at most 40 characters, about 4 words")
            sx.add_argument("--goal", help="one sentence, at most 140 characters")
            sx.add_argument("--pr", type=int, nargs="+", action="extend", help="PR numbers, several allowed (--pr 1 2 or --pr 1 --pr 2); replaces the PR list")
        if name == "update":
            sx.add_argument("--owner", help="hand the stream to this live coordinator")
            sx.add_argument("--auto-acquire", choices=("on", "off"), help="on: `watch auto` grants lease requests of this stream's members")
    sl = ssub.add_parser("list")
    sl.add_argument("--coordinator")
    sub.add_parser("host-check")
    cw = sub.add_parser("calm-wait")
    cw.add_argument("--settle", type=int, default=0, help="seconds to wait first, e.g. while a stack starts")
    cw.add_argument("--retry", type=int, default=20)
    mp = sub.add_parser("measure-peak")
    mp.add_argument("--id", required=True)
    mp.add_argument("--worktree", required=True)
    mp.add_argument("--interval", type=float, default=15)
    dr = sub.add_parser("drain-check")
    dr.add_argument("--worktree", required=True)
    dr.add_argument("--port", type=int, action="append", help="also check for listeners on this port")
    dr.add_argument("--process", action="append", help="also count processes matching this pattern (pgrep -f)")
    wa = sub.add_parser("watch")
    wa.add_argument("what", choices=("inbox", "expiry", "prs", "cloud", "auto", "pool"))
    wa.add_argument("--me", help="coordinator name (inbox, prs, cloud)")
    wa.add_argument("--interval", type=int, default=180, help="seconds between cloud task polls")
    ins = sub.add_parser("install")
    ins.add_argument("--replace", action="store_true",
                     help="replace live copies that differ: only the proposed update, approved by the user and agreed by every live coordinator")
    ins.add_argument("--by", help="the installing coordinator; required with --replace")
    ins.add_argument("--ignore-leases", action="store_true", help="install although leases are granted; only on the user's word")
    up = sub.add_parser("update")
    usub = up.add_subparsers(dest="ucmd", required=True)
    upr = usub.add_parser("propose")
    upr.add_argument("--by", required=True)
    upr.add_argument("--text", help="what changes, in one line")
    for name in ("agree", "object"):
        uv = usub.add_parser(name)
        uv.add_argument("--by", required=True)
        uv.add_argument("--text", required=name == "object", help="the reason (required to object)")
    uap = usub.add_parser("approve")
    uap.add_argument("--by", required=True)
    uap.add_argument("--quote", required=True, help="the user's own words in your session")
    ust = usub.add_parser("status")
    ust.add_argument("--ignore-leases", action="store_true", help="do not count granted leases as a blocker")
    args = p.parse_args()
    if args.cmd in ("roster", "whoami", "coordinate", "heartbeat", "status"):
        version_warning()
    for attr in ("cls", "pcls"):
        name = getattr(args, attr, None)
        if name and name not in registry():
            p.error(f"unknown lease class {name}; known: {', '.join(class_names())} (add one with config set-class)")

    if args.cmd in READS and (args.cmd != "memory" or args.mcmd == "list"):
        return read_cmd(args)
    if args.cmd == "say":
        return say_cmd(args)
    if args.cmd == "note":
        note(args.by, args.text, args.pr)
        return 0
    if args.cmd == "memory":
        return memory_cmd(args)
    unlocked = {"host-check": host_check_cmd, "calm-wait": calm_wait_cmd, "measure-peak": measure_peak_cmd,
                "drain-check": drain_check_cmd, "watch": watch_cmd, "install": install_cmd, "prs": prs_cmd}
    if args.cmd in unlocked:
        if args.cmd == "watch" and args.what != "expiry" and not args.me:
            p.error("watch inbox|prs|cloud|auto needs --me <coordinator>")
        return unlocked[args.cmd](args)
    if args.cmd == "decision":
        return decision_cmd(args)
    if args.cmd == "update":
        return update_cmd(args)
    if args.cmd in ("unwait", "up", "move"):
        return queue_edit_cmd(args)
    if args.cmd in ("park", "unpark"):
        return park_cmd(args)
    if args.cmd == "acquire":
        return acquire_cmd(args)
    if args.cmd == "resource":
        if args.rcmd != "list" and not args.name:
            p.error("resource add|mark|remove needs --name")
        return resource_cmd(args)

    lock()
    try:
        if args.cmd in ("coordinate", "heartbeat", "resign", "leases", "member", "enroll", "child", "stream"):
            return roster_cmd(args)
        if args.cmd == "config":
            return config_cmd(args)
        roster = load_roster()
        state = load()
        machine = load_machine()
        if args.cmd == "status":
            state["budget"] = budget(state, machine)
            if args.brief:
                print(brief(state))
            else:
                print(json.dumps(state, indent=1))
            return 0
        if args.cmd == "capacity":
            print(json.dumps(budget(state, machine), indent=1))
            return 0
        queue = state["queue"][args.cls]
        if args.cmd == "wait":
            try:
                prefer = parse_prefer(args.prefer)
            except ValueError as e:
                print(e)
                return 2
            if args.resource and not RESOURCE_NAME.match(args.resource):
                print(f"{args.resource} is not a valid resource name")
                return 2
            code, text = queue_entry(state, roster, args.cls, args.id, args.coordinator, args.holder, args.minutes,
                                     args.gib, args.cpus, args.commands, args.worktree, args.priority, args.front,
                                     changed_by=args.coordinator, prefer=prefer, resource=args.resource)
            if code == 0:
                save(state, machine)
            print(text)
            return code
        if args.cmd == "extend":
            for h in state[args.cls]:
                if h["id"] == args.id:
                    code, text = extend_lease(h, args.cls, args.minutes)
                    if code:
                        print(text)
                        return code
                    save(state, machine)
                    log(f"extend {args.cls} {args.id} until {text}")
                    return 0
            print(f"{args.cls} not held by {args.id}")
            return 3
        if args.cmd == "admission":
            return admission_cmd(args, state, machine)
        if args.cmd in ("hold", "ready"):
            entry = next((q for q in queue if q["id"] == args.id), None)
            if not entry:
                print(f"{args.id} is not queued for {args.cls}")
                return 3
            for key in ("hold", "review", "reason"):
                entry.pop(key, None)
            if args.cmd == "hold":
                entry["review" if args.review else "hold"] = True
                if args.reason:
                    entry["reason"] = args.reason
            save(state, machine)
            log(f"{args.cmd}{' review' if args.cmd == 'hold' and args.review else ''} {args.cls} {args.id}"
                + (f" reason={json.dumps(args.reason)}" if args.cmd == 'hold' and args.reason else ""))
            return 0
        if args.cmd == "deny":
            if args.by not in roster["coordinators"]:
                print(f"--by must be a registered coordinator, got {args.by}")
                return 2
            entry = next((q for q in queue if q["id"] == args.id), None)
            if not entry:
                print(f"{args.id} is not queued for {args.cls}")
                return 3
            queue.remove(entry)
            denied = state.setdefault("denied", {})
            denied[args.id] = {"class": args.cls, "reason": args.reason, "by": args.by, "at": now().isoformat()}
            for old in sorted(denied, key=lambda k: denied[k]["at"])[:-50]:
                del denied[old]
            save(state, machine)
            log(f"deny {args.cls} {args.id} by={args.by} reason={json.dumps(args.reason)}")
            print(f"denied {args.id}")
            return 0
    finally:
        unlock()


if __name__ == "__main__":
    code = main()
    for by, message, members in PENDING:
        broadcast(by, message, members)
    sys.exit(code)
