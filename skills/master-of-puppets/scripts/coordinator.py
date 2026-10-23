#!/usr/bin/env python3
"""Coordinator commands for master-of-puppets: roster, members, streams, ledger,
memory, peer messaging, leases, the host gate, watchers, config and install.
Members use puppet.py. Shared code is in moplib.py.

Configuration (asked once through the skill's first-run setup):
  machine  $DIR/config.json             reserveGiB, diskFloorGiB, diskAlarmGiB, maxSwapouts,
                                        swapIntervalS, loadPerCore, dashboardPort, maxSlots, classes
  project  $DIR/projects/<key>.json     root, baseBranch, mergeMethod, leasesDefault and per
                                        class maxMinutes, peakMode (learn|fixed), defaultGiB, samples
The project key comes from the repository's git common dir, so all worktrees of one
repository share a file; nothing is written into the repository.

Every limit is a number in this config, and coordinator.py enforces it: memory
budget, slot caps, settle times, max lease minutes, swap-outs, load and the disk
floor. Never put a limit in `memory`; set it with `config`.

Lease classes are a registry in config.json: any shared action that sessions must
take turns on (builds, local stacks, one browser window, a shared tunnel, a test
database, a device). Leases are optional and machine-wide. Default registry:
  BUILD: builds (incl. setup scripts that build), typecheck, lint/format, test runs, codegen.
  E2E:   starting local servers/stacks and interacting with them.
Each class has a description, defaultGiB (0 = not memory-bound; then only maxSlots
limits it), maxMinutes and settle {OTHER: seconds} (after a grant of this class,
OTHER waits that long; E2E settles BUILD for 60 s by default). Names are upper-case.
No lease: a plain dependency install, source edits, reading code, browser-only work
against remote sites (unless a class or a project rule in `memory` covers it).
Use it or return it: a lease covers the granted commands and their resource cleanup.
No edits or repairs while holding one. When a check fails, clean up owned resources
(stop owned E2E servers), release promptly with the failure, repair without a lease,
then join the queue again at the back.

Capacity is adaptive. There is no fixed slot count. A grant is admitted when the
expected peak memory of all holders plus the request fits in the memory budget:
  sum(held GiB) + request GiB <= total RAM - reserve
A request's GiB defaults to its project's class peak. In learn mode that is the max
of the last 5 measured peaks (`measure-peak` writes peaks/<id>.gib; release
records it), with the default as a floor until 3 samples exist; in fixed mode it is
the default. Example: on a 24 GiB machine with a 6 GiB reserve, BUILD ~10 GiB and
E2E ~8 GiB admit one of each; 64 GiB admits more. A 0 GiB class uses no budget.
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
  wait CLASS --coordinator C --holder NAME --id ID [--minutes N] [--gib N] [--commands TEXT] [--worktree P]
       [--priority N] [--front]
       for an existing ID every flag is optional and only the given fields change.
       exit 2 when --minutes is over the class limit: split the run.
       --priority: default the task's priority, else 0; a change moves the entry to its
       place among the others. --front: the head, at the highest priority in the queue.
       Members queue their own requests with puppet.py request; watch inbox shows each
       as a "request" event. Only acquire grants.
  acquire CLASS --coordinator C --holder NAME --id ID --worktree P --minutes N [--gib N]
          [--commands TEXT] [--measure]
       runs the host check itself (about 2 × swapIntervalS), then checks again under the lock.
       exit 0 granted, 2 --minutes over the class limit (split the run), 3 queued behind
       another entry, at a slot cap or in a settle window (another class's grant settles
       this one), 4 over the memory budget, 5 host BUSY or disk below the floor.
       --commands records the granted scope; --measure starts measure-peak itself.
       The holder releases with puppet.py release.
  unwait | hold | ready CLASS --id ID
  up CLASS --id ID                move a ready entry ahead of the ready entry in front of it;
                                  it takes that entry's priority when that is higher
       unwait and up take --notify (the dashboard's queue buttons): each affected
       coordinator gets an inbox message from "dashboard", delivered directly as say does
  extend CLASS --id ID --minutes N   expires N minutes from now; exit 2 when the lease would
                                  run longer than the class limit
  host-check                      admission gate; exit 0 CALM, 1 BUSY (pressure or disk below
                                  the floor); prints disk=ok|alarm|blocked
  calm-wait [--settle S] [--retry S]           one CALM line when the host is calm
  measure-peak --id ID --worktree P [--interval S]   run in the background after acquire
  drain-check --worktree P [--port N ...] [--process PATTERN ...]   exit 0 when nothing is left; never kills

Config
  config show [--project-root P] | set-machine ... | set-project --root P ... | project-key P
       machine: --reserve-gib --disk-floor-gib --disk-alarm-gib --max-swapouts --swap-interval-s
                --load-per-core --dashboard-port --max-slots CLASS=N (N=0 removes the cap)
  config set-class NAME [--description T] [--default-gib N] [--max-minutes N] [--settle OTHER=S ...]
  config remove-class NAME        refused while the class has holders or queue entries
       project: --name --base-branch --merge-method merge|squash|rebase|auto --leases-default
                [--class CLASS --max-minutes N --minutes learn|fixed --peak learn|fixed --default-gib N]
       release records run minutes; with --minutes learn the limit is p90 of the last 10
       runs + 25% (at least 5, at most --max-minutes); config show prints maxMinutesEffective.

Roster and members (coordinators write; members send messages, and request and release their own leases)
  roster | whoami --session-id ID
  coordinate --name C --tool claude|codex --session-id ID --focus TEXT [--pr N ...] [--takeover] [--general]
       --general: a general-purpose coordinator with no fixed scope
  heartbeat --name C [--focus TEXT] [--pr N ...] [--status active|idle] | resign --name C
       --status idle: no work can move. Refused (exit 3) while a member is active or
       pending. Paused members and their PRs stay C's as parked work. An idle
       coordinator is not reported stale; resuming a member wakes it.
  stream add|update --coordinator C --name SLUG [--label TEXT] [--goal TEXT] [--pr N ...]
       update --owner C2 hands the stream to live coordinator C2
  stream close|reopen --coordinator C --name SLUG | stream list [--coordinator C]
       a stream is a named goal (one or more PR stacks) that groups members on the
       dashboard. The slug is unique on the machine; only its coordinator changes it.
       add needs --label (at most 40 characters); --goal at most 140.
  enroll --coordinator C --task TEXT [--by MEMBER] [--name NAME] [--pr N ...] [--stream SLUG] [--priority N]
       registers a task before it starts and prints the kickoff line for its prompt
  member add|update --coordinator C --name NAME [--tool] [--session-id] [--worktree] [--task]
       [--pr N ...] [--repo owner/repo] [--status] [--phase] [--kind] [--latest] [--session URL]
       [--stream SLUG] [--priority N]   (--stream "" clears it)
       --priority: the task's priority (default 0; higher first, below 0 for background
       work). A change also moves the task's queued lease entries and prints their ids
       updates the roster and the member's row in dashboard/<C>-state.json. Without
       --session the row links to the session from --tool and --session-id; without
       --repo, PR links use the worktree's GitHub origin (a warning when there is none)
  member remove --coordinator C --name NAME
  member stale --coordinator C [--minutes 30]   members (not done) with no update for N minutes
  park --coordinator C --name MEMBER [--until YYYY-MM-DD] [--notify]
  unpark --coordinator C --name MEMBER [--notify]
       park sets the member to paused; the task leaves Needs you and returns there as
       "Revisit" after --until. The dashboard's Park/Unpark buttons use --notify.
  decision add --by C --text TEXT [--task ID] [--href URL] [--option TEXT ...]
       prints the decision id. Each --option (at most 4, 60 characters each) is a
       suggested answer: the dashboard shows it as a button on the decision
  decision answer --by C --id ID --choice N [--notify]
       the user's answer, option N (from 1): clears the decision and notes it in the
       ledger. The dashboard's option buttons use --notify, so C gets the answer
  decision clear --by C (--task ID | --all)
  note --by C --text TEXT [--pr N]   shared ledger

Memory (the skill's own memory; coordinators write it, everyone reads it)
  memory add --by NAME --text TEXT [--kind rule|note] [--project-root P]
  memory list [--project-root P] [--json]      machine entries, then the project's
  memory remove --id ID [--project-root P]
       Stored on this machine, in the state dir, never in a repository.
       Machine scope: memory/machine.json. Project scope (with --project-root):
       memory/<project-key>.json, shared by every worktree of the repository.
       Project-specific rules (for example which git hooks need a lease) live here,
       not in the skill text. Limits (GiB, slots, minutes, disk, swap, load) do not:
       they are config numbers.

Peer-coordinator messaging
  say --from NAME --message TEXT [--to NAME] [--no-direct]
       appends to inbox.jsonl, then delivers directly: a Claude session through its inbox
       socket (protocol: github.com/PeterSR/claude-code-socket-transport, reverse-engineered,
       not an Anthropic interface), a Codex thread through `codex queue`. --to names a
       registered coordinator; without it, every live peer coordinator. Only registered
       coordinators use say. A receiver that bypasses
       permission prompts holds a socket message for the user's approval.

Watchers and install
  watch inbox --me C | watch expiry | watch prs --me C [--interval S] | watch cloud --me C [--interval S]
       Monitor sources. watch cloud reads cloud-<C>.txt (a CodeRabbit cloud task id or URL,
       then the member name, per line) and prints each task's state change from
       `coderabbit code show --agent`
  install [--replace]         copy moplib.py, coordinator.py and puppet.py into the state dir when absent.
       A live copy that differs stops the install (all or nothing) unless --replace, which only
       follows the agreement of the other coordinators and the user. A full install removes
       obsolete helpers (lease.py). Each run records this skill copy in source.json; roster,
       whoami, coordinate, heartbeat and status then warn on stderr when an update is due

A coordinator is live while its heartbeat is newer than 40 minutes. coordinate and
heartbeat exit 3 when a PR is owned by another live coordinator; enroll and member
exit 3 when the coordinator is not live.
"""
import argparse
import datetime as dt
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
    DIR, CONFIG, TOOLS, MEMBER_TOOLS, SLUG, FILES, OBSOLETE, SOURCE, version_warning, PEAKS, LOG,
    INBOX, CLASS_NAME, read_json, write_json, load_machine, registry,
    class_names, project_key, load_project, save_project, class_peak, typical_minutes,
    max_minutes, length_limit, over_limit, now, lock, unlock, log, note,
    load_roster, save_roster, live, load, save, budget, order, queue_entry,
    say, deliver, notify, READS, memory_path, add_read_commands,
    read_cmd,
)


# ---------------------------------------------------------------- config


def config_cmd(args):
    machine = load_machine()
    if args.ccmd == "project-key":
        key, base = project_key(args.path)
        print(json.dumps({"key": key, "root": base}))
        return 0
    if args.ccmd == "set-machine":
        raw = read_json(CONFIG) or {}
        for flag, field in (("reserve_gib", "reserveGiB"), ("disk_floor_gib", "diskFloorGiB"), ("disk_alarm_gib", "diskAlarmGiB"),
                            ("max_swapouts", "maxSwapouts"), ("swap_interval_s", "swapIntervalS"),
                            ("load_per_core", "loadPerCore"), ("dashboard_port", "dashboardPort")):
            if getattr(args, flag) is not None:
                raw[field] = getattr(args, flag)
        merged = {**machine, **raw}
        if merged["diskAlarmGiB"] < merged["diskFloorGiB"]:
            print(f"--disk-alarm-gib ({merged['diskAlarmGiB']:g}) must be at least --disk-floor-gib ({merged['diskFloorGiB']:g})")
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
        log(f"config machine {json.dumps(raw)}")
        print(json.dumps(load_machine(), indent=1))
        return 0
    if args.ccmd in ("set-class", "remove-class"):
        if not CLASS_NAME.match(args.name):
            print("class names are upper-case, for example BROWSER or TEST-DB")
            return 2
        raw = read_json(CONFIG) or {}
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
            c = reg.setdefault(args.name, {"description": "", "defaultGiB": 0, "maxMinutes": 20, "settle": {}})
            for flag, field in (("description", "description"), ("default_gib", "defaultGiB"), ("max_minutes", "maxMinutes")):
                if getattr(args, flag) is not None:
                    c[field] = getattr(args, flag)
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
        log(f"config class {args.ccmd} {args.name}")
        print(json.dumps(reg, indent=1))
        return 0
    if args.ccmd == "set-project":
        key, base = project_key(args.root)
        proj = load_project(key, base)
        proj["root"] = base
        for flag, field in (("name", "name"), ("base_branch", "baseBranch"), ("merge_method", "mergeMethod"), ("leases_default", "leasesDefault")):
            if getattr(args, flag) is not None:
                proj[field] = getattr(args, flag)
        if args.pcls:
            c = proj["classes"][args.pcls]
            for flag, field in (("max_minutes", "maxMinutes"), ("minutes", "minutesMode"), ("peak", "peakMode"), ("default_gib", "defaultGiB")):
                if getattr(args, flag) is not None:
                    c[field] = getattr(args, flag)
        proj["configured"] = True
        proj["updatedAt"] = now().isoformat()
        save_project(proj)
        log(f"config project {key}")
        print(json.dumps(proj, indent=1))
        return 0
    out = {"machine": machine}
    missing = [] if machine["configured"] else ["machine"]
    if args.project_root:
        key, base = project_key(args.project_root)
        proj = load_project(key, base)
        for c in class_names():
            proj["classes"][c]["peakGiB"] = class_peak(proj, c)
            proj["classes"][c]["maxMinutesEffective"] = max_minutes(proj, c)
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
        targets = [(n, c.get("tool"), c.get("sessionId")) for n, c in roster["coordinators"].items() if n != args.sender and live(c)]
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
    return (
        f"{KICKOFF_MARK} — {coord} has enrolled you as member {name}{by}. "
        f"First action: run /puppet and send {coord} your JOIN message as {name}; "
        f"then follow {coord}'s directions. Start every child task you create with "
        f"puppet enrollment: send {coord} an ENROLL REQUEST and put its kickoff line first in the new prompt."
    )


def roster_cmd(args):
    roster = load_roster()
    coords = roster["coordinators"]
    if args.cmd == "leases":
        roster["leases"] = args.mode
        save_roster(roster)
        log(f"leases {args.mode} by={args.by}")
        note(args.by, f"leases {args.mode}")
        return 0
    if args.cmd in ("coordinate", "heartbeat", "resign"):
        cur = coords.get(args.name)
        if args.cmd == "coordinate":
            if not SLUG.match(args.name):
                print("--name must be a lowercase slug, for example claude-scope-ux")
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
                parked = [m["name"] for m in mlist if m.get("status") == "paused"]
                if parked or cur.get("prs"):
                    print(json.dumps({"parked": {"prs": cur.get("prs", []), "members": parked}}))
            if args.status and args.status != cur.get("status", "active"):
                cur["status"] = args.status
                log(f"{args.status} {args.name}")
                note(args.name, f"{args.name} is {args.status}")
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
    wakes = args.cmd == "enroll" or (args.cmd == "member" and (args.mcmd == "add" or (args.mcmd == "update" and args.status in ("active", "pending"))))
    if wakes and cur.get("status") == "idle":
        cur["status"] = "active"
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
    m = next((x for x in members if x["name"] == args.name), None)
    if args.cmd == "member" and args.mcmd == "remove":
        members[:] = [x for x in members if x["name"] != args.name]
        save_roster(roster)
        remove_task(args.coordinator, args.name)
        note(args.coordinator, f"{args.name} left")
        return 0
    if args.mcmd == "add":
        if m is None:
            m = {"name": args.name, "joinedAt": now().isoformat()}
            members.append(m)
        m["status"] = "active"
        m.setdefault("joinedAt", now().isoformat())
    elif m is None:
        print(f"{args.name} is not a member of {args.coordinator}")
        return 3
    for flag, field in (("tool", "tool"), ("session_id", "sessionId"), ("worktree", "worktree"), ("task", "task"), ("status", "status"),
                        ("stream", "stream"), ("repo", "repo")):
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
        note(args.coordinator, f"{args.name} joined: {m.get('task', '')} (PRs {' '.join('#' + str(n) for n in m.get('prs', [])) or 'none'})")
    if moved:
        print(json.dumps({"moved": moved}))
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
                log(f"priority {c} {q['id']} {priority}")
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


def decision_cmd(args):
    """add, answer and clear. answer is the user's choice from the dashboard; it runs in
    another process than the owner's, so it takes the lock."""
    if args.dcmd == "add" and args.option:
        if len(args.option) > MAX_OPTIONS or any(len(o) > MAX_OPTION_CHARS or not o.strip() for o in args.option):
            print(f"at most {MAX_OPTIONS} options, each 1 to {MAX_OPTION_CHARS} characters")
            return 2
    if args.dcmd == "clear" and not (args.task or args.all):
        print("decision clear needs --task ID or --all")
        return 2
    path = state_path(args.by)
    lock()
    try:
        data = read_json(path) or {}
        items = data.setdefault("decisions", [])
        if args.dcmd == "add":
            item = {"id": uuid.uuid4().hex[:8], "text": args.text}
            if args.task:
                item["task"] = args.task
            if args.href:
                item["href"] = args.href
            if args.option:
                item["options"] = args.option
            items.append(item)
            done = f"decision {item['id']} added"
        elif args.dcmd == "answer":
            item = next((d for d in items if isinstance(d, dict) and d.get("id") == args.id), None)
            options = (item or {}).get("options") or []
            if item is None or not 1 <= args.choice <= len(options):
                print(f"decision {args.id} of {args.by} has changed or is answered; reload the dashboard")
                return 3
            answer = options[args.choice - 1]
            data["decisions"] = [d for d in items if d is not item]
            task = item.get("task", "")
            done = f"Answered{' for ' + task if task else ''}: {answer}"
            message = (f"The user answered the decision{' for ' + task if task else ''} on the dashboard: \"{answer}\" "
                       f"(question: \"{item.get('text', '')}\"). This is the user's answer; act on it.")
        else:
            data["decisions"] = [] if args.all else [d for d in items if not isinstance(d, dict) or d.get("task") != args.task]
            done = "cleared"
        data["updated"] = now().strftime("%H:%MZ")
        write_json(path, data)
        if args.dcmd == "answer":
            log(f"decision answer {args.by} {args.id} choice={args.choice}" + (" by=dashboard" if args.notify else ""))
            note("dashboard" if args.notify else args.by, f"User decision{' for ' + task if task else ''}: {answer} ({item.get('text', '')})")
    finally:
        unlock()
    print(f"{done} · {len(data['decisions'])} decisions for {args.by}")
    if args.dcmd == "answer" and args.notify:
        print(notify(args.by, message))
    return 0


# ---------------------------------------------------------------- memory


def memory_cmd(args):
    path, name = memory_path(args.project_root)
    lock()
    try:
        data = read_json(path) or {"entries": []}
        if args.mcmd == "add":
            entry = {"id": f"m-{os.urandom(3).hex()}", "kind": args.kind, "text": args.text, "by": args.by, "at": now().isoformat()}
            data["entries"].append(entry)
            write_json(path, data)
            log(f"memory add {name} {entry['id']} by={args.by}")
            print(entry["id"])
            return 0
        before = len(data["entries"])
        data["entries"] = [x for x in data["entries"] if x["id"] != args.id]
        if len(data["entries"]) == before:
            print(f"no memory entry {args.id} in {name}")
            return 3
        write_json(path, data)
        log(f"memory remove {name} {args.id}")
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
            lines.append(f"{c} held  {h['id']} ({h['coordinator']}, {h['gib']} GiB) {status} — {h['holder'][:60]}")
            if h.get("commands"):
                lines.append(f"           covers: {h['commands'][:120]}")
        q = state["queue"][c]
        ready = [x for x in q if not x.get("hold")]
        prio = f", priority {ready[0]['priority']}" if ready and ready[0].get("priority") else ""
        head = f"head {ready[0]['id']} ({ready[0]['coordinator']}{prio})" if ready else "no ready entry"
        lines.append(f"{c} queue {len(ready)} ready, {len(q) - len(ready)} on hold — {head}")
    b = state["budget"]
    lines.append(f"budget {b['freeGiB']} of {b['limitGiB']} GiB free · capacity {b['capacity']} · peaks {b['peakGiB']}")
    return "\n".join(lines)


def queue_edit_cmd(args):
    """unwait and up. With --notify, tell each affected coordinator after the lock is released."""
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
            ahead = next((n for n in range(i - 1, -1, -1) if not queue[n].get("hold")), None)
            if ahead is None:
                print(f"{args.id} is already first among ready {args.cls} entries")
                return 0
            other = queue[ahead]
            raised = other.get("priority", 0) > entry.get("priority", 0)
            if raised:
                entry["priority"] = other["priority"]
            queue.insert(ahead, queue.pop(i))
            pos = sum(1 for q in queue[: ahead + 1] if not q.get("hold"))
            prio = f" at priority {entry['priority']}" if raised else ""
            done = f"moved {args.id} to {args.cls} position {pos}{prio}, ahead of {other['id']}"
            message = (f"The user moved {args.cls} queue entry {args.id} ({entry['holder']}) up to position {pos}{prio}, "
                       f"ahead of {other['id']} ({other['holder']}), on the dashboard. Tell the affected members their new turn.")
            to = list(dict.fromkeys([entry["coordinator"], other["coordinator"]]))
            log(f"up {args.cls} {args.id} ahead of {other['id']}" + (" by=dashboard" if args.notify else ""))
        save(state, machine)
    finally:
        unlock()
    print(done)
    for name in to if args.notify else []:
        print(notify(name, message))
    return 0


def acquire_checks(args, state, machine):
    """Every acquire gate except the host and the memory budget. Returns (exit, text) to refuse, else None."""
    queue, holders = state["queue"][args.cls], state[args.cls]
    if any(h["id"] == args.id for h in holders):
        return 0, "already held"
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
    check again under the lock (another grant may have landed) and the memory budget."""
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
        key = entry.get("project") or project_key(args.worktree)[0]
        gib = args.gib or entry.get("gib") or class_peak(load_project(key), args.cls)
        b = budget(state, machine)
        if gib > b["freeGiB"]:
            why = f"needs {gib} GiB, {b['freeGiB']} GiB free of {b['limitGiB']} GiB budget"
            print(json.dumps({"memory": why, "held": [h["id"] for c in class_names(machine) for h in state[c]]}))
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
        log(f"acquire {args.cls} {args.coordinator} {args.id} {args.holder} until {holders[-1]['expiresAt']} ({gib} GiB, {round(b['freeGiB'] - gib, 1)} GiB left)")
        return 0
    finally:
        unlock()


# ---------------------------------------------------------------- host


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


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


def worktree_pids(tree):
    tree = os.path.realpath(tree)
    pids, pid = set(), None
    for line in run(["lsof", "-nP", "-d", "cwd", "-Fpn"]).splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid:
            path = line[1:]
            if path == tree or path.startswith(tree + "/"):
                pids.add(pid)
    return sorted(pids, key=int)


def measure_peak_cmd(args):
    """While ID holds a lease, sum RSS of processes working in the worktree; keep the max
    in peaks/<id>.gib for release. RSS counts shared pages twice, so it errs high."""
    os.makedirs(PEAKS, exist_ok=True)
    out = os.path.join(PEAKS, f"{args.id}.gib")
    peak = 0.0
    time.sleep(2)
    while any(h["id"] == args.id for c in class_names() for h in load()[c]):
        pids = worktree_pids(args.worktree)
        if pids:
            kib = sum(int(x) for x in run(["ps", "-o", "rss=", "-p", ",".join(pids)]).split() if x.isdigit())
            gib = round(kib / 2**20, 1)
            if gib > peak:
                peak = gib
                with open(out, "w") as f:
                    f.write(str(peak))
        time.sleep(args.interval)
    print(f"peak {args.id} {peak} GiB")
    return 0


def drain_check_cmd(args):
    """Report what a released lease left behind: processes working in the worktree (with
    their listeners), listeners on the given ports, and processes matching each
    --process pattern (for example a tunnel or a browser started for the run).
    Exit 0 when nothing is left, 1 otherwise. It only reports; it never kills."""
    left = 0
    pids = worktree_pids(args.worktree)
    for pid in pids:
        cmd = run(["ps", "-o", "command=", "-p", pid]).strip()[:100]
        if not cmd:
            continue
        left += 1
        ports = [l[1:] for l in run(["lsof", "-nP", "-a", "-p", pid, "-iTCP", "-sTCP:LISTEN", "-Fn"]).splitlines() if l.startswith("n")]
        print(f"  worktree {pid} {'[listen ' + ' '.join(ports) + '] ' if ports else ''}{cmd}")
    for port in args.port or []:
        for line in run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"]).splitlines():
            if line.startswith("p"):
                pid = line[1:]
                left += 1
                print(f"  port {port} {pid} {run(['ps', '-o', 'command=', '-p', pid]).strip()[:100]}")
    for pattern in args.process or []:
        for line in run(["pgrep", "-fl", pattern]).splitlines():
            left += 1
            print(f"  process {pattern}: {line[:110]}")
    print(f"{'drained' if not left else 'not drained'}: {left} left for {args.worktree}")
    return 0 if not left else 1


# ---------------------------------------------------------------- watchers and install


def follow(paths):
    """Yield (path, line) for lines appended to the files after start."""
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
        time.sleep(2)


def watch_inbox(me):
    """Messages to me or to all, and other coordinators' roster and lease events."""
    for path, line in follow([INBOX, LOG]):
        if path == INBOX:
            try:
                rec = json.loads(line)
            except ValueError:
                print(f"INBOX {line}", flush=True)
                continue
            if rec.get("from") != me and rec.get("to") in (None, me):
                print(f"INBOX {rec.get('from')}: {rec.get('message')}", flush=True)
            continue
        f = line.split()
        if len(f) < 3:
            continue
        own = (
            (f[1] in ("wait", "acquire", "refuse") and len(f) > 3 and f[3] == me)
            or (f[1] in ("release", "unwait", "hold", "ready", "extend", "priority") and f[3 if len(f) > 3 else -1].startswith(me + "-"))
            or (f[1] in ("coordinate", "resign") and f[2] == me)
            or f"by={me}" in f
        )
        if not own:
            print(f"EVENT {line}", flush=True)


def watch_expiry():
    """Each lease past its expiry, once. An expired lease still holds its slot."""
    seen = set()
    while True:
        t = now()
        state = load()
        for c in class_names():
            for h in state[c]:
                key = (c, h["id"])
                if key not in seen and dt.datetime.fromisoformat(h["expiresAt"]) < t:
                    seen.add(key)
                    print(f'{c} {h["id"]} ({h["coordinator"]}) expired at {h["expiresAt"][11:16]}Z holder={h["holder"][:60]}', flush=True)
        time.sleep(60)


def watch_prs(me, interval):
    """State changes of the PRs listed in prs-<me>.txt ("owner/repo#123" per line)."""
    path = os.path.join(DIR, f"prs-{me}.txt")
    open(path, "a").close()
    last = {}
    fields = "state,baseRefName,isDraft,mergeStateStatus,autoMergeRequest,reviewDecision,mergeCommit"
    while True:
        for raw in open(path).read().splitlines():
            ref = raw.split()[0] if raw.split() else ""
            if not ref or ref.startswith("#") or "#" not in ref:
                continue
            repo, num = ref.rsplit("#", 1)
            r = subprocess.run(["gh", "pr", "view", num, "--repo", repo, "--json", fields], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if r.returncode != 0:
                line = "error " + " ".join(r.stderr.split())[:200]
            else:
                d = json.loads(r.stdout)
                sha = f" sha={d['mergeCommit']['oid'][:12]}" if d.get("mergeCommit") else ""
                line = (f"{d['state']} base={d['baseRefName']} draft={str(d['isDraft']).lower()} merge={d['mergeStateStatus']} "
                        f"automerge={'on' if d.get('autoMergeRequest') else 'off'} review={d.get('reviewDecision') or 'none'}{sha}")
            if last.get(ref) != line:
                print(f"PR {ref} {line}", flush=True)
                last[ref] = line
        time.sleep(interval)


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
        else:
            watch_prs(args.me, args.interval)
    except KeyboardInterrupt:
        return 0
    return 0


def install_cmd(args):
    """Copy the helpers into the state dir when absent. All or nothing: when a live copy
    differs, print every diff and install none, so live files never mix versions; with
    --replace, replace every differing copy. After a full install, remove obsolete helpers.
    Each run records this skill copy as the source, so later runs can warn when an update is due."""
    here = os.path.dirname(os.path.realpath(__file__))
    if os.path.realpath(DIR) == here:
        print("this is the live copy")
        return 0
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
        print(f"DIFFERS {dst} (not overwritten; agree the change with the other coordinators and the user, then use --replace)")
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
    dn = dsub.add_parser("answer")
    dn.add_argument("--by", required=True)
    dn.add_argument("--id", required=True)
    dn.add_argument("--choice", type=int, required=True, help="the option number, from 1")
    dn.add_argument("--notify", action="store_true", help="tell the coordinator (sender: dashboard)")
    dl = dsub.add_parser("clear")
    dl.add_argument("--by", required=True)
    dl.add_argument("--task")
    dl.add_argument("--all", action="store_true")
    sub.add_parser("capacity")
    a = sub.add_parser("acquire")
    a.add_argument("cls", metavar="CLASS")
    a.add_argument("--coordinator", required=True)
    a.add_argument("--holder", required=True)
    a.add_argument("--id", required=True)
    a.add_argument("--worktree", required=True)
    a.add_argument("--minutes", type=int, required=True)
    a.add_argument("--gib", type=float, help="expected peak GiB; default: queue entry estimate, then class peak")
    a.add_argument("--commands", help="the exact granted commands; default: the queue entry's")
    a.add_argument("--measure", action="store_true", help="start measure-peak in the background for this lease")
    w = sub.add_parser("wait")
    w.add_argument("cls", metavar="CLASS")
    w.add_argument("--coordinator", help="required for a new entry")
    w.add_argument("--holder", help="required for a new entry; an existing entry keeps its holder text unless given")
    w.add_argument("--id", required=True)
    w.add_argument("--minutes", type=int)
    w.add_argument("--gib", type=float)
    w.add_argument("--commands", help="the exact commands the lease would cover")
    w.add_argument("--worktree", help="sets the project whose class peak applies")
    w.add_argument("--priority", type=int, help="higher goes first; default: the task's priority, else 0")
    w.add_argument("--front", action="store_true", help="re-queue at the head (only for a run aborted by the coordinator)")
    for name in ("unwait", "up"):
        u = sub.add_parser(name)
        u.add_argument("cls", metavar="CLASS")
        u.add_argument("--id", required=True)
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
    cf = sub.add_parser("config")
    csub = cf.add_subparsers(dest="ccmd", required=True)
    cs = csub.add_parser("show")
    cs.add_argument("--project-root")
    cm = csub.add_parser("set-machine")
    cm.add_argument("--reserve-gib", type=float)
    cm.add_argument("--disk-floor-gib", type=float, help="below this many GiB free, no lease is granted")
    cm.add_argument("--disk-alarm-gib", type=float, help="below this many GiB free, the host check raises the disk alarm")
    cm.add_argument("--max-swapouts", type=int)
    cm.add_argument("--swap-interval-s", type=int)
    cm.add_argument("--load-per-core", type=float)
    cm.add_argument("--dashboard-port", type=int)
    cm.add_argument("--max-slots", action="append", help="CLASS=N hard cap; N=0 removes it")
    cpj = csub.add_parser("set-project")
    cpj.add_argument("--root", required=True)
    cpj.add_argument("--name")
    cpj.add_argument("--base-branch")
    cpj.add_argument("--merge-method", choices=("merge", "squash", "rebase", "auto"),
                     help="auto: run gh pr merge --auto with no method flag (merge queue or repository default)")
    cpj.add_argument("--leases-default", choices=("on", "off"))
    cpj.add_argument("--class", dest="pcls", metavar="CLASS")
    cpj.add_argument("--max-minutes", type=int)
    cpj.add_argument("--minutes", choices=("learn", "fixed"), help="learn: adapt the limit to recorded run times, capped by --max-minutes")
    cpj.add_argument("--peak", choices=("learn", "fixed"))
    cpj.add_argument("--default-gib", type=float)
    sc = csub.add_parser("set-class")
    sc.add_argument("name", metavar="CLASS")
    sc.add_argument("--description")
    sc.add_argument("--default-gib", type=float, help="expected peak; 0 = not memory-bound")
    sc.add_argument("--max-minutes", type=int)
    sc.add_argument("--settle", action="append", help="OTHER=SECONDS: after a grant of this class, OTHER waits (0 removes)")
    rc = csub.add_parser("remove-class")
    rc.add_argument("name", metavar="CLASS")
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
    mr2 = mesub.add_parser("remove")
    mr2.add_argument("--id", required=True)
    mr2.add_argument("--project-root")
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
    mr = msub.add_parser("remove")
    mr.add_argument("--coordinator", required=True)
    mr.add_argument("--name", required=True)
    ms = msub.add_parser("stale")
    ms.add_argument("--coordinator", required=True)
    ms.add_argument("--minutes", type=int, default=30)
    en = sub.add_parser("enroll")
    en.add_argument("--coordinator", required=True)
    en.add_argument("--by", help="member that asked for the task; default: the coordinator")
    en.add_argument("--task", required=True)
    en.add_argument("--name")
    en.add_argument("--pr", type=int, nargs="+", action="extend", help="PR numbers, several allowed (--pr 1 2 or --pr 1 --pr 2)")
    en.add_argument("--stream", help="stream slug (stream add)")
    en.add_argument("--priority", type=int, help="task priority: 0 default, higher first, below 0 for background work")
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
    wa.add_argument("what", choices=("inbox", "expiry", "prs", "cloud"))
    wa.add_argument("--me", help="coordinator name (inbox, prs, cloud)")
    wa.add_argument("--interval", type=int, default=180, help="seconds between PR or cloud task polls")
    ins = sub.add_parser("install")
    ins.add_argument("--replace", action="store_true",
                     help="replace live copies that differ; only after the other coordinators and the user agree")
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
                "drain-check": drain_check_cmd, "watch": watch_cmd, "install": install_cmd}
    if args.cmd in unlocked:
        if args.cmd == "watch" and args.what != "expiry" and not args.me:
            p.error("watch inbox|prs|cloud needs --me <coordinator>")
        return unlocked[args.cmd](args)
    if args.cmd == "decision":
        return decision_cmd(args)
    if args.cmd in ("unwait", "up"):
        return queue_edit_cmd(args)
    if args.cmd in ("park", "unpark"):
        return park_cmd(args)
    if args.cmd == "acquire":
        return acquire_cmd(args)

    lock()
    try:
        if args.cmd in ("coordinate", "heartbeat", "resign", "leases", "member", "enroll", "stream"):
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
            code, text = queue_entry(state, roster, args.cls, args.id, args.coordinator, args.holder, args.minutes,
                                     args.gib, args.commands, args.worktree, args.priority, args.front)
            if code == 0:
                save(state, machine)
            print(text)
            return code
        if args.cmd == "extend":
            for h in state[args.cls]:
                if h["id"] == args.id:
                    expires = now() + dt.timedelta(minutes=args.minutes)
                    total = (expires - dt.datetime.fromisoformat(h["grantedAt"])).total_seconds() / 60
                    limit = length_limit(args.cls, h.get("project"))
                    if total > limit:
                        print(f"the lease would run {total:.0f} min, over the {limit}-min {args.cls} limit; release it and queue the rest")
                        return 2
                    h["expiresAt"] = expires.isoformat()
                    save(state, machine)
                    log(f"extend {args.cls} {args.id} until {h['expiresAt']}")
                    return 0
            print(f"{args.cls} not held by {args.id}")
            return 3
        if args.cmd in ("hold", "ready"):
            for q in queue:
                if q["id"] == args.id:
                    q["hold"] = args.cmd == "hold"
            save(state, machine)
            log(f"{args.cmd} {args.cls} {args.id}")
            return 0
    finally:
        unlock()


if __name__ == "__main__":
    sys.exit(main())
