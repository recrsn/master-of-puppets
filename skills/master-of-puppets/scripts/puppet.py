#!/usr/bin/env python3
"""Member ("puppet") commands for master-of-puppets. A member reads the roster and
the skill's memory, queues its own lease request, waits for the grant, asks for more
time and releases its own lease. Only a coordinator grants (coordinator.py acquire) and
extends (coordinator.py extend). A member never
writes the roster, ledger, dashboard or shared inbox; it messages its coordinator,
which records everything with coordinator.py. Shared code is in moplib.py.

State lives in $MACHINE_LEASE_DIR (default ~/.local/state/machine-leases).

Usage: python3 -I puppet.py <command> ...

  roster | whoami --session-id ID
       coordinators (with live: heartbeat newer than 40 minutes), members and streams
  memory list [--project-root P] [--json]      machine rules and notes, then the project's
  inbox | ledger | events | who     the shared records, read-only (coordinator.py has the
       same commands and flags); for example events --id ID shows a lease's grant and release
  sizes --worktree P [--class CLASS]
       the project's recorded run minutes, peak GiB and peak cores per class, the figures
       your coordinator charges and checks against, and the size margin: size from these
  request CLASS --coordinator C --name NAME --id ID --minutes N --commands TEXT --worktree P
          [--gib N] [--cpus N] [--what TEXT]
       queue your own lease request; prints its position. You size the run: --minutes always,
       --gib and --cpus (peak memory and cores) when you know them; your coordinator charges
       its own figure for a size you leave out. The ID must start with C-q-NAME-,
       and NAME must be a member of C. The entry takes your task's priority; only your
       coordinator or the user changes it. A repeat with the same ID changes the given fields.
       Prints a warning when --gib or --cpus is below the observed peak by more than the
       size margin: your coordinator then refuses the grant unless you tell it why.
       exit 0 queued, 2 over the class limit or the whole budget (split the run), 3 refused: leases off, not a
       member of C, a foreign ID, or the ID is already held
  await-grant CLASS --id ID [--timeout-min N] [--appear-timeout S]
       prints GRANTED or NOT-GRANTED <reason>. Exit 0 granted (the only grant);
       3 left the queue without a grant; 5 timeout while still queued; 6 never queued
       within --appear-timeout (default 600 s)
  extend CLASS --coordinator C --name NAME --id ID --minutes N --reason TEXT
       ask your coordinator to extend your own granted lease to expire N minutes from now.
       It does not change the expiry: the coordinator decides. Writes one event line,
         extend-request CLASS ID N min by=NAME coordinator=C reason="TEXT"
       and puts an EXTEND message in your coordinator's inbox. The coordinator
       replies LEASE EXTENDED or tells you to release.
       exit 0 asked, 2 the lease would run longer than the class limit (release it and
       request the rest), 3 refused: not a member of C, not your lease, or not held
  release CLASS --id ID --result pass|fail|partial [--note TEXT] [--peak-gib N] [--peak-cpus N]
          [--port N ...] [--process PATTERN ...]
       release your own lease, never another's; records its run minutes and peaks, then
       counts what the run left in the lease's worktree (agent session processes and bare
       shells do not count) and writes one event line:
         release CLASS ID ran N min peak N GiB N cores result=R drained=N coordinator=C note="TEXT"
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
    load_project, save_project, project_key, undersized, now, lock, unlock, log, say,
    load, save, load_roster, queue_entry, extension_refusal, READS, add_read_commands, read_cmd, version_warning, drain,
)


# ---------------------------------------------------------------- leases


def request(args):
    """Queue the member's own entry. The member cannot grant, set a priority or jump the
    queue; its coordinator gets a REQUEST message in its inbox and grants."""
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
                                 args.gib, args.cpus, args.commands, args.worktree, by=args.name)
        if code == 0:
            save(state, machine)
        print(text)
        why = code == 0 and undersized(args.cls, project_key(args.worktree)[0], args.gib, machine["sizeMargin"])
        if why:
            print(f"warning: {why}")
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


def extend(args):
    """Ask for more time on the member's own granted lease. Extension is the coordinator's
    decision (coordinator.py extend), so this only checks the request and logs it."""
    roster, state = load_roster(), load()
    if not any(m["name"] == args.name for m in roster["members"].get(args.coordinator, [])):
        print(f"{args.name} is not a member of {args.coordinator}; send JOIN first")
        return 3
    held = next((h for h in state[args.cls] if h["id"] == args.id), None)
    if held is None:
        print(f"{args.cls} not held by {args.id}; request a new lease")
        return 3
    # A transferred member keeps its old ID prefix, so match the name part and the holder's coordinator.
    if f"-q-{args.name}-" not in args.id or held["coordinator"] != args.coordinator:
        print(f"{args.id} is not yours; extend only a lease granted to you")
        return 3
    why = extension_refusal(held, args.cls, args.minutes)
    if why:
        print(why)
        return 2
    log(f"extend-request {args.cls} {args.id} {args.minutes} min by={args.name} coordinator={args.coordinator} reason={json.dumps(args.reason)}")
    say(args.name, f"EXTEND {args.cls} {args.id} {args.minutes} min: coordinator.py extend {args.cls} --id {args.id} "
        f"--minutes {args.minutes} when the queue allows, else ask the member to release. Reason: {args.reason}", args.coordinator)
    print(f"asked {args.coordinator} to extend {args.cls} {args.id} to {args.minutes} min from now; it still expires at "
          f"{held['expiresAt'][11:16]}Z until {args.coordinator} extends it")
    return 0


def read_peak(path):
    """A measure-peak figure, or None when the file is missing or unreadable."""
    try:
        return float(open(path).read().strip())
    except (OSError, ValueError):
        return None


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
        peak, cores = args.peak_gib, args.peak_cpus
        files = [os.path.join(PEAKS, f"{args.id}.{ext}") for ext in ("gib", "cpus")]
        if peak is None:
            peak = read_peak(files[0])
        if cores is None:
            cores = read_peak(files[1])
        held = next(h for h in holders if h["id"] == args.id)
        key = held["project"]
        ran = round((now() - dt.datetime.fromisoformat(held["grantedAt"])).total_seconds() / 60, 1)
        if key:
            proj = load_project(key, held.get("worktree"))
            c = proj["classes"][args.cls]
            for field, value in (("samples", peak), ("cpuSamples", cores)):
                if value:
                    c[field].append(round(value, 1))
                    del c[field][:-SAMPLES_KEPT]
            c["runMinutes"].append(ran)
            del c["runMinutes"][:-MINUTES_KEPT]
            save_project(proj)
        for path in files:
            if os.path.exists(path):
                os.remove(path)
        state[args.cls] = [h for h in holders if h["id"] != args.id]
        save(state, machine)
    finally:
        unlock()
    left = drain(held["worktree"], args.port or [], args.process or []) if held.get("worktree") else []
    for line in left:
        print(f"  {line}")
    peaks = [f"{round(v, 1)} {unit}" for v, unit in ((peak, "GiB"), (cores, "cores")) if v]
    log(f"release {args.cls} {args.id} ran {ran} min" + (f" peak {' '.join(peaks)}" if peaks else "")
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
    rq.add_argument("--gib", type=float, help="expected peak GiB; omit to let your coordinator charge its own figure")
    rq.add_argument("--cpus", type=float, help="expected peak cores; omit to let your coordinator charge its own figure")
    rq.add_argument("--what", help="short label for the dashboard; default: the commands")
    ag = sub.add_parser("await-grant")
    ag.add_argument("cls", metavar="CLASS")
    ag.add_argument("--id", required=True)
    ag.add_argument("--timeout-min", type=float, default=30)
    ag.add_argument("--appear-timeout", type=float, default=600, help="seconds the ID may take to be queued")
    ag.add_argument("--interval", type=float, default=10)
    x = sub.add_parser("extend")
    x.add_argument("cls", metavar="CLASS")
    x.add_argument("--coordinator", required=True)
    x.add_argument("--name", required=True, help="your member name")
    x.add_argument("--id", required=True)
    x.add_argument("--minutes", type=int, required=True, help="ask for the lease to expire this many minutes from now")
    x.add_argument("--reason", required=True, help="one short line: what is still running")
    r = sub.add_parser("release")
    r.add_argument("cls", metavar="CLASS")
    r.add_argument("--id", required=True)
    r.add_argument("--peak-gib", type=float, help="measured peak; default: peaks/<id>.gib from measure-peak")
    r.add_argument("--peak-cpus", type=float, help="measured peak cores; default: peaks/<id>.cpus from measure-peak")
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
    if args.cmd == "extend":
        return extend(args)
    return release(args)


if __name__ == "__main__":
    sys.exit(main())
