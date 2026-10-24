#!/usr/bin/env python3
"""Member ("puppet") commands for master-of-puppets. A member reads the roster and
the skill's memory, queues its own lease request, waits for the grant and releases
its own lease. Only a coordinator grants (coordinator.py acquire). A member never
writes the roster, ledger, dashboard or shared inbox; it messages its coordinator,
which records everything with coordinator.py. Shared code is in moplib.py.

State lives in $MACHINE_LEASE_DIR (default ~/.local/state/machine-leases).

Usage: python3 -I puppet.py <command> ...

  roster | whoami --session-id ID
       coordinators (with live: heartbeat newer than 40 minutes), members and streams
  memory list [--project-root P] [--json]      machine rules and notes, then the project's
  inbox | ledger | events | who     the shared records, read-only (coordinator.py has the
       same commands and flags); for example events --id ID shows a lease's grant and release
  request CLASS --coordinator C --name NAME --id ID --minutes N --commands TEXT --worktree P
          [--gib N] [--what TEXT]
       queue your own lease request; prints its position. The ID must start with C-q-NAME-,
       and NAME must be a member of C. The entry takes your task's priority; only your
       coordinator or the user changes it. A repeat with the same ID changes the given fields.
       exit 0 queued, 2 over the class limit (split the run), 3 refused: leases off, not a
       member of C, a foreign ID, or the ID is already held
  await-grant CLASS --id ID [--timeout-min N] [--appear-timeout S]
       prints GRANTED or NOT-GRANTED <reason>. Exit 0 granted (the only grant);
       3 left the queue without a grant; 5 timeout while still queued; 6 never queued
       within --appear-timeout (default 600 s)
  release CLASS --id ID --result pass|fail|partial [--note TEXT] [--peak-gib N] [--port N ...] [--process PATTERN ...]
       release your own lease, never another's; records its run minutes and peak, then
       counts what the run left in the lease's worktree (agent session processes and bare
       shells do not count) and writes one event line:
         release CLASS ID ran N min result=R drained=N coordinator=C note="TEXT"
       That line is the record of the release: coordinators read it with `events`.
"""
import argparse
import datetime as dt
import json
import time
import os
import sys

# python3 -I keeps the script's own directory off sys.path; moplib is its sibling.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True  # no __pycache__ in the shared state dir
from moplib import (
    PEAKS, SAMPLES_KEPT, MINUTES_KEPT, load_machine, registry, class_names,
    load_project, save_project, now, lock, unlock, log,
    load, save, load_roster, queue_entry, READS, add_read_commands, read_cmd, version_warning, drain,
)


# ---------------------------------------------------------------- leases


def request(args):
    """Queue the member's own entry. The member cannot grant, set a priority or jump the
    queue; its coordinator sees the "request" event in watch inbox and grants."""
    lock()
    try:
        roster, state, machine = load_roster(), load(), load_machine()
        if roster["leases"] != "on":
            print("leases are off; run the commands without a lease")
            return 3
        if not any(m["name"] == args.name for m in roster["members"].get(args.coordinator, [])):
            print(f"{args.name} is not a member of {args.coordinator}; send JOIN first")
            return 3
        prefix = f"{args.coordinator}-q-{args.name}-"
        if not args.id.startswith(prefix):
            print(f"{args.id} is not yours; use an ID that starts with {prefix}")
            return 3
        if any(h["id"] == args.id for h in state[args.cls]):
            print(f"{args.id} is already held; release it or use a new ID")
            return 3
        queued = any(q["id"] == args.id for q in state["queue"][args.cls])
        holder = f"{args.name} {args.what or args.commands}" if args.what or not queued else None
        code, text = queue_entry(state, roster, args.cls, args.id, args.coordinator, holder, args.minutes,
                                 args.gib, args.commands, args.worktree, by=args.name)
        if code == 0:
            save(state, machine)
        print(text)
        return code
    finally:
        unlock()


def await_grant(args):
    """Poll without the lock. The coordinator may queue the ID for the member, so the
    ID gets --appear-timeout to show up before it is judged. Prints one line,
    GRANTED or NOT-GRANTED <reason>; only exit 0 means granted."""
    start = time.time()
    seen = False
    while True:
        state = load()
        if any(h["id"] == args.id for h in state[args.cls]):
            print(f"GRANTED {args.cls} {args.id}")
            return 0
        entry = next((q for q in state["queue"][args.cls] if q["id"] == args.id), None)
        waited = time.time() - start
        if entry is not None:
            seen = True
        elif seen:
            print(f"NOT-GRANTED {args.cls} {args.id}: left the queue without a grant; ask your coordinator")
            return 3
        elif waited >= args.appear_timeout:
            print(f"NOT-GRANTED {args.cls} {args.id}: never queued within {args.appear_timeout:g} s; check the id with your coordinator")
            return 6
        if waited >= args.timeout_min * 60:
            ready = [q["id"] for q in state["queue"][args.cls] if not q.get("hold")]
            pos = ready.index(args.id) + 1 if args.id in ready else "on hold" if entry else "not queued"
            print(f"NOT-GRANTED {args.cls} {args.id}: timeout after {args.timeout_min:g} min; position {pos}; still queued, wait again")
            return 5
        time.sleep(args.interval)


def release(args):
    """Release the caller's own lease: record its run minutes and measured peak, then
    check what the run left in its worktree (after the lock: the check scans every
    process) and write one event line with the result and the drain count. That line is
    the shared record of the release; other coordinators read it, no one sends a receipt."""
    lock()
    try:
        state, machine = load(), load_machine()
        holders = state[args.cls]
        if not any(h["id"] == args.id for h in holders):
            print(f"{args.cls} not held by {args.id}: {json.dumps(holders)}")
            return 3
        peak = args.peak_gib
        peak_file = os.path.join(PEAKS, f"{args.id}.gib")
        if peak is None and os.path.exists(peak_file):
            try:
                peak = float(open(peak_file).read().strip())
            except ValueError:
                peak = None
        held = next(h for h in holders if h["id"] == args.id)
        key = held["project"]
        ran = round((now() - dt.datetime.fromisoformat(held["grantedAt"])).total_seconds() / 60, 1)
        if key:
            proj = load_project(key, held.get("worktree"))
            c = proj["classes"][args.cls]
            if peak:
                c["samples"].append(round(peak, 1))
                del c["samples"][:-SAMPLES_KEPT]
            c["runMinutes"].append(ran)
            del c["runMinutes"][:-MINUTES_KEPT]
            save_project(proj)
        if os.path.exists(peak_file):
            os.remove(peak_file)
        state[args.cls] = [h for h in holders if h["id"] != args.id]
        save(state, machine)
    finally:
        unlock()
    left = drain(held["worktree"], args.port or [], args.process or []) if held.get("worktree") else []
    for line in left:
        print(f"  {line}")
    log(f"release {args.cls} {args.id} ran {ran} min" + (f" peak {round(peak, 1)} GiB" if peak else "")
        + f" result={args.result} drained={len(left)} coordinator={held['coordinator']}"
        + (f" note={json.dumps(args.note)}" if args.note else ""))
    print(f"released {args.cls} {args.id} ({args.result}); {'drained' if not left else 'not drained'}: {len(left)} left in {held.get('worktree')}")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    add_read_commands(sub)
    rq = sub.add_parser("request")
    rq.add_argument("cls", metavar="CLASS")
    rq.add_argument("--coordinator", required=True)
    rq.add_argument("--name", required=True, help="your member name")
    rq.add_argument("--id", required=True, help="<coordinator>-q-<name>-<n>")
    rq.add_argument("--minutes", type=int, required=True, help="your estimate")
    rq.add_argument("--commands", required=True, help="the exact commands the lease would cover")
    rq.add_argument("--worktree", required=True, help="sets the project whose class peak applies")
    rq.add_argument("--gib", type=float, help="expected peak GiB, if known")
    rq.add_argument("--what", help="short label for the dashboard; default: the commands")
    ag = sub.add_parser("await-grant")
    ag.add_argument("cls", metavar="CLASS")
    ag.add_argument("--id", required=True)
    ag.add_argument("--timeout-min", type=float, default=30)
    ag.add_argument("--appear-timeout", type=float, default=600, help="seconds the ID may take to be queued")
    ag.add_argument("--interval", type=float, default=10)
    r = sub.add_parser("release")
    r.add_argument("cls", metavar="CLASS")
    r.add_argument("--id", required=True)
    r.add_argument("--peak-gib", type=float, help="measured peak; default: peaks/<id>.gib from measure-peak")
    r.add_argument("--result", required=True, choices=("pass", "fail", "partial"), help="the outcome of the granted commands")
    r.add_argument("--note", help="one short line, for example 'pushed #123' or the first failure")
    r.add_argument("--port", type=int, action="append", help="also check for listeners on this port (E2E)")
    r.add_argument("--process", action="append", help="also count processes matching this pattern (pgrep -f)")
    args = p.parse_args()
    name = getattr(args, "cls", None)
    if name and name not in registry():
        p.error(f"unknown lease class {name}; known: {', '.join(class_names())}")
    if args.cmd in ("roster", "whoami"):
        version_warning()
    if args.cmd in READS:
        return read_cmd(args)
    if args.cmd == "request":
        return request(args)
    if args.cmd == "await-grant":
        return await_grant(args)
    return release(args)


if __name__ == "__main__":
    sys.exit(main())
