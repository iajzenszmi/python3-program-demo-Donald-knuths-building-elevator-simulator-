gforth fib10.fs
1 1 2 3 5 8 13 21 34 55
Gforth 0.7.3, Copyright (C) 1995-2008 Free Software Foundation, Inc.
Gforth comes with # file: elevator_scan_demo.py
from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Iterable, Dict


class Dir(int, Enum):
    DOWN = -1
    IDLE = 0
    UP = 1


class Status(str, Enum):
    WAITING = "WAITING"
    ONBOARD = "ONBOARD"
    DONE = "DONE"


@dataclass
class Request:
    rid: int
    t_request: int
    src: int
    dst: int
    status: Status = Status.WAITING
    t_board: Optional[int] = None
    t_drop: Optional[int] = None

    @property
    def desired_dir(self) -> Dir:
        if self.dst > self.src:
            return Dir.UP
        if self.dst < self.src:
            return Dir.DOWN
        return Dir.IDLE  # pathological; ignored


@dataclass
class Elevator:
    floors: int
    current: int = 1
    direction: Dir = Dir.IDLE
    door_timer: int = 0  # ticks remaining with doors open
    onboard: List[Request] = field(default_factory=list)

    def in_bounds(self, floor: int) -> bool:
        return 1 <= floor <= self.floors

    def set_direction_towards(self, target_floor: int) -> None:
        # Why: establish a consistent direction from IDLE or after clearing a sweep
        if target_floor > self.current:
            self.direction = Dir.UP
        elif target_floor < self.current:
            self.direction = Dir.DOWN
        else:
            self.direction = Dir.IDLE

    def move_one_tick(self) -> None:
        if self.direction == Dir.UP:
            self.current = min(self.floors, self.current + 1)
        elif self.direction == Dir.DOWN:
            self.current = max(1, self.current - 1)
        # if IDLE, stay


class EventLog:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose

    def log(self, t: int, msg: str) -> None:
        if self.verbose:
            print(f"[t={t:04d}] {msg}")


def next_targets_in_direction(
    elev: Elevator,
    waiting: Iterable[Request],
    direction: Dir,
) -> List[int]:
    """
    Compute unique target floors in the given direction from:
      - waiting pickups whose desired direction == direction
      - onboard drop-offs
    Ordered to implement SCAN: ascending for UP, descending for DOWN.
    """
    cur = elev.current
    up = set()
    down = set()

    # Onboard drop-offs
    for r in elev.onboard:
        if r.dst > cur:
            up.add(r.dst)
        elif r.dst < cur:
            down.add(r.dst)

    # Waiting pickups (only halls that want this direction)
    for r in waiting:
        if r.status != Status.WAITING:
            continue
        if r.desired_dir == Dir.UP and r.src > cur:
            up.add(r.src)
        elif r.desired_dir == Dir.DOWN and r.src < cur:
            down.add(r.src)

    if direction == Dir.UP:
        return sorted(up)
    if direction == Dir.DOWN:
        return sorted(down, reverse=True)
    return []


def any_targets(elev: Elevator, waiting: Iterable[Request]) -> bool:
    if elev.onboard:
        return True
    for r in waiting:
        if r.status == Status.WAITING:
            return True
    return False


def nearest_target_floor(elev: Elevator, waiting: Iterable[Request]) -> Optional[int]:
    """When idle, pick the nearest source or destination."""
    candidates: List[int] = []
    for r in waiting:
        if r.status == Status.WAITING:
            candidates.append(r.src)
    for r in elev.onboard:
        candidates.append(r.dst)
    if not candidates:
        return None
    cur = elev.current
    # Tie-break upward to avoid dithering
    best = min(candidates, key=lambda f: (abs(f - cur), -f))
    return best


def run_sim(
    floors: int,
    ticks: int,
    dwell: int,
    speed_floors_per_tick: int,
    new_requests: List[Request],
    stop_when_done: bool,
    verbose: bool,
) -> Tuple[List[Request], Dict[str, float]]:
    assert speed_floors_per_tick == 1, "This demo assumes 1 floor/tick for clarity."
    elev = Elevator(floors=floors, current=1, direction=Dir.IDLE, door_timer=0)
    waiting: List[Request] = []
    req_by_time: Dict[int, List[Request]] = {}
    for r in new_requests:
        req_by_time.setdefault(r.t_request, []).append(r)

    log = EventLog(verbose)

    for t in range(ticks + 1):
        # Inject arrivals
        for r in req_by_time.get(t, []):
            waiting.append(r)
            log.log(t, f"REQ#{r.rid} arrives at floor {r.src} → {r.dst} ({r.desired_dir.name})")

        # If all done and stop_when_done: break early
        if stop_when_done and not any_targets(elev, waiting):
            log.log(t, "No pending targets. Simulation ends early.")
            break

        # Door dwell handling
        if elev.door_timer > 0:
            elev.door_timer -= 1
            log.log(t, f"Doors open at floor {elev.current} (dwell {elev.door_timer} left)")
            continue

        # Arrivals/Departures at current floor
        dropped = [r for r in elev.onboard if r.dst == elev.current]
        for r in dropped:
            r.status = Status.DONE
            r.t_drop = t
            elev.onboard.remove(r)
        boarded = []
        # Board only those whose src == current and whose desired direction matches the sweep.
        # If IDLE, we can decide direction opportunistically from first candidate.
        floor_waiters = [r for r in waiting if r.src == elev.current and r.status == Status.WAITING]
        if floor_waiters:
            if elev.direction == Dir.IDLE:
                # Choose direction that serves the majority (tie → up)
                up_count = sum(1 for r in floor_waiters if r.desired_dir == Dir.UP)
                down_count = sum(1 for r in floor_waiters if r.desired_dir == Dir.DOWN)
                elev.direction = Dir.UP if up_count >= down_count else Dir.DOWN

            for r in list(floor_waiters):
                if r.desired_dir == elev.direction:
                    r.status = Status.ONBOARD
                    r.t_board = t
                    elev.onboard.append(r)
                    waiting.remove(r)
                    boarded.append(r)

        if dropped or boarded:
            if dropped:
                ids = ",".join(f"#{r.rid}" for r in dropped)
                log.log(t, f"Drop-off complete at floor {elev.current} for {ids}")
            if boarded:
                ids = ",".join(f"#{r.rid}" for r in boarded)
                log.log(t, f"Boarded at floor {elev.current}: {ids} (dir {elev.direction.name})")
            elev.door_timer = dwell
            continue  # spend dwell time next ticks

        # Decide direction / move step
        targets = next_targets_in_direction(elev, waiting, elev.direction)
        if elev.direction == Dir.IDLE:
            # Idle: pick nearest target and set direction
            target = nearest_target_floor(elev, waiting)
            if target is not None:
                elev.set_direction_towards(target)
                log.log(t, f"IDLE→{elev.direction.name}; heading toward floor {target}")
            else:
                log.log(t, "IDLE; no targets")
        else:
            if not targets:
                # Nothing ahead → reverse if there exist any targets overall
                if any_targets(elev, waiting):
                    elev.direction = Dir.UP if elev.direction == Dir.DOWN else Dir.DOWN
                    log.log(t, f"Reverse direction → {elev.direction.name}")
                else:
                    elev.direction = Dir.IDLE
                    log.log(t, "No targets; going IDLE")

        # Move one floor if we have a direction
        if elev.direction != Dir.IDLE:
            prev = elev.current
            elev.move_one_tick()
            log.log(t, f"Move {prev} → {elev.current} ({elev.direction.name})")

    # Stats
    finished = [r for r in new_requests if r.status == Status.DONE]
    avg_wait = sum((r.t_board - r.t_request) for r in finished) / len(finished) if finished else 0.0
    avg_ride = sum((r.t_drop - r.t_board) for r in finished) / len(finished) if finished else 0.0
    avg_total = sum((r.t_drop - r.t_request) for r in finished) / len(finished) if finished else 0.0
    stats = {
        "requests_total": len(new_requests),
        "requests_done": len(finished),
        "avg_wait": avg_wait,
        "avg_ride": avg_ride,
        "avg_total": avg_total,
        "last_time": t if ticks >= 0 else 0,
    }
    return new_requests, stats


def generate_poisson_requests(
    floors: int,
    ticks: int,
    rate_per_tick: float,
    seed: Optional[int],
) -> List[Request]:
    # Why: poisson arrivals are a standard, simple traffic model
    rng = random.Random(seed)
    reqs: List[Request] = []
    rid = 1
    for t in range(ticks + 1):
        # Poisson(λ) via counting Bernoulli with small λ, adequate for demo
        num = sum(1 for _ in range(4) if rng.random() < rate_per_tick / 4.0)  # approx Poisson
        for _ in range(num):
            src = rng.randint(1, floors)
            dst = rng.randint(1, floors)
            while dst == src:
                dst = rng.randint(1, floors)
            reqs.append(Request(rid=rid, t_request=t, src=src, dst=dst))
            rid += 1
    return reqs


def main() -> None:
    p = argparse.ArgumentParser(
        description="Knuth-style Elevator (SCAN) Algorithm Demo: single car, hall calls + car calls synthesized."
    )
    p.add_argument("--floors", type=int, default=10, help="Number of floors [1..N]")
    p.add_argument("--ticks", type=int, default=300, help="Total simulation ticks")
    p.add_argument("--dwell", type=int, default=2, help="Door dwell ticks when boarding/dropping")
    p.add_argument("--speed", type=int, default=1, help="Floors per tick (fixed to 1 in this demo)")
    p.add_argument("--lambda", dest="lam", type=float, default=0.15, help="Avg requests per tick (Poisson-ish)")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument("--stop-when-done", action="store_true", help="Stop early when queue becomes empty")
    p.add_argument("--quiet", action="store_true", help="Suppress per-tick logs")
    p.add_argument("--no-random", action="store_true", help="Use a fixed small scenario instead of random arrivals")
    args = p.parse_args()

    if args.no_random:
        # A tiny deterministic scenario
        demo: List[Request] = [
            Request(1, 0, 1, 7),
            Request(2, 3, 3, 9),
            Request(3, 5, 9, 2),
            Request(4, 12, 4, 6),
            Request(5, 15, 8, 1),
        ]
    else:
        demo = generate_poisson_requests(args.floors, args.ticks, args.lam, args.seed)

    all_reqs, stats = run_sim(
        floors=args.floors,
        ticks=args.ticks,
        dwell=args.dwell,
        speed_floors_per_tick=args.speed,
        new_requests=demo,
        stop_when_done=args.stop_when_done,
        verbose=not args.quiet,
    )

    # Summary
    done = [r for r in all_reqs if r.status == Status.DONE]
    print("\n=== SUMMARY ===")
    print(f"Floors: {args.floors}, ticks: {args.ticks}, dwell: {args.dwell}, λ: {args.lam}, seed: {args.seed}")
    print(
        f"Requests: total={stats['requests_total']} done={stats['requests_done']} "
        f"avg_wait={stats['avg_wait']:.2f} avg_ride={stats['avg_ride']:.2f} avg_total={stats['avg_total']:.2f}"
    )
    # Distribution samples
    if done:
        waits = sorted((r.t_board - r.t_request) for r in done)
        rides = sorted((r.t_drop - r.t_board) for r in done)
        print(f"Wait p50={percentile(waits, 50):.1f} p90={percentile(waits, 90):.1f}")
        print(f"Ride p50={percentile(rides, 50):.1f} p90={percentile(rides, 90):.1f}")


def percentile(sorted_values: List[int], pctl: float) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    k = (pctl / 100.0) * (n - 1)
    f = int(k)
    c = min(f + 1, n - 1)
    if f == c:
        return float(sorted_values[f])
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


if __name__ == "__main__":
    main()
