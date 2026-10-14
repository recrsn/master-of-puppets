#!/usr/bin/env python3
"""Member ("puppet") commands for master-of-puppets. A member reads the roster and
the skill's memory, waits for its lease grant and releases its own lease. It never
writes the roster, ledger, dashboard or shared inbox; it messages its coordinator,
which records everything with coordinator.py. Shared code is in moplib.py.

State lives in $MACHINE_LEASE_DIR (default ~/.local/state/machine-leases).

Usage: python3 -I puppet.py <command> ...

  roster | whoami --session-id ID
       coordinators (with live: heartbeat newer than 40 minutes), members and streams
  memory list [--project-root P] [--json]      machine rules and notes, then the project's
  await-grant CLASS --id ID [--timeout-min N] [--appear-timeout S]
       prints GRANTED or NOT-GRANTED <reason>. Exit 0 granted (the only grant);
       3 left the queue without a grant; 5 timeout while still queued; 6 never queued
       within --appear-timeout (default 600 s), so a member may start before the
       coordinator queues the ID it proposed
  release CLASS --id ID [--peak-gib N]
       release your own lease, never another's; records its run minutes and peak
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
    load, save, READS, add_read_commands, read_cmd,
)


# ---------------------------------------------------------------- leases


def await_grant(args):
    """Poll without the lock. A member may start before the coordinator queues the
    entry, so the ID gets --appear-timeout to show up before it is judged. Prints
    one line, GRANTED or NOT-GRANTED <reason>; only exit 0 means granted."""
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
    """Release the caller's own lease: record its run minutes and measured peak."""
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
        log(f"release {args.cls} {args.id} ran {ran} min" + (f" peak {round(peak, 1)} GiB" if peak else ""))
        return 0
    finally:
        unlock()


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    add_read_commands(sub)
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
    args = p.parse_args()
    name = getattr(args, "cls", None)
    if name and name not in registry():
        p.error(f"unknown lease class {name}; known: {', '.join(class_names())}")
    if args.cmd in READS:
        return read_cmd(args)
    if args.cmd == "await-grant":
        return await_grant(args)
    return release(args)


if __name__ == "__main__":
    sys.exit(main())
