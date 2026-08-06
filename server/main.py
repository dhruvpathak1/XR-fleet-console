"""
XR Fleet Operations Console - simulation backend.

Runs a continuous-space warehouse fleet simulation on a discrete grid and
streams robot poses to connected clients over a WebSocket at a fixed tick rate.

Design decisions you should be able to defend:

1. FIXED TICK RATE, DECOUPLED FROM RENDER RATE.
   The sim advances at TICK_HZ (20). The browser renders at 60-90 Hz. These are
   deliberately different. Physics/planning at render rate makes behaviour
   depend on the client's GPU, which is a correctness bug, not just a style
   choice. The client interpolates between snapshots to cover the gap.

2. BINARY FRAMES, NOT JSON.
   At 20 Hz with 500 robots, JSON would be ~500 objects serialized 20x/sec.
   That is megabytes per second of string building on the server and
   JSON.parse on the main thread of the client, every frame budget, forever.
   A packed Float32 buffer is 16 + 24*N bytes (12 KB for 500 robots) and the
   client reads it with a DataView at zero allocation cost.

3. SERVER IS AUTHORITATIVE.
   Clients send intents ("assign this goal"), never positions. This is the
   same reason multiplayer games do it: any other arrangement means a client
   can desync or lie.

Wire format (little-endian):
    Header (16 bytes):
        uint32  tick
        float32 sim_time_seconds
        uint32  robot_count
        uint32  reserved (keeps header 16-byte aligned)
    Per robot (24 bytes):
        float32 x          world X position
        float32 z          world Z position
        float32 heading    radians
        float32 speed      world units/sec
        float32 status     0 idle, 1 moving, 2 blocked
        float32 kind       0 ground, 1 aerial

Status and kind are floats rather than packed bytes purely so the client can
upload them straight into a Float32 instanced attribute with no conversion.
That is a deliberate trade: 6 wasted bytes per robot to avoid per-frame CPU
work on the client. At 500 robots it costs 3 KB per frame. Worth it.
"""

import asyncio
import json
import math
import random
import struct
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

TICK_HZ = 20                 # simulation updates per second
DT = 1.0 / TICK_HZ
GRID_N = 40                  # warehouse is GRID_N x GRID_N cells
CELL = 1.5                   # world units per cell
DEFAULT_ROBOTS = 500
MAX_ROBOTS = 4000
GROUND_SPEED = 3.2           # world units / second
AERIAL_SPEED = 4.6
AERIAL_FRACTION = 0.25       # share of the fleet that flies
ESCAPE_AFTER_TICKS = 4       # blocked this long -> accept any free neighbour
IDLE_DWELL_TICKS = 20        # 1 second parked at goal, then re-task

STATUS_IDLE, STATUS_MOVING, STATUS_BLOCKED = 0.0, 1.0, 2.0
KIND_GROUND, KIND_AERIAL = 0.0, 1.0

HEADER = struct.Struct("<IfII")
ROBOT = struct.Struct("<6f")


def cell_to_world(i: int) -> float:
    """Centre of grid index i in world coordinates, grid centred on origin."""
    return (i - (GRID_N - 1) / 2.0) * CELL


class Robot:
    __slots__ = ("id", "kind", "x", "z", "cx", "cz", "gx", "gz",
                 "tx", "tz", "heading", "speed", "status",
                 "blocked_ticks", "idle_ticks")

    def __init__(self, rid: int, kind: float, cx: int, cz: int):
        self.id = rid
        self.kind = kind
        self.cx, self.cz = cx, cz              # current cell
        self.x, self.z = cell_to_world(cx), cell_to_world(cz)
        self.gx, self.gz = cx, cz              # goal cell
        self.tx, self.tz = cx, cz              # cell currently moving into
        self.heading = 0.0
        self.speed = 0.0
        self.status = STATUS_IDLE
        self.blocked_ticks = 0
        self.idle_ticks = 0

    @property
    def max_speed(self) -> float:
        return AERIAL_SPEED if self.kind == KIND_AERIAL else GROUND_SPEED


class Fleet:
    """
    Prioritised multi-agent planner, continuous motion between grid cells.

    This is the same movement strategy as the Warehouse Robot Management
    System project (move on X first, then Z, priority by Euclidean distance
    to goal, ground and aerial robots occupy separate collision planes), but
    lifted from a discrete step simulation into continuous space so the poses
    are smooth enough to render.
    """

    def __init__(self, count: int = DEFAULT_ROBOTS):
        self.robots: list[Robot] = []
        self.paused = False
        self.tick = 0
        self.sim_time = 0.0
        # Two occupancy sets: ground robots and aerial robots do not collide
        # with each other because they are on different planes.
        self._reserved: dict[float, set[tuple[int, int]]] = {
            KIND_GROUND: set(), KIND_AERIAL: set()
        }
        self.resize(count)

    # -- fleet management ---------------------------------------------------

    def resize(self, count: int) -> None:
        count = max(1, min(MAX_ROBOTS, count))
        self.robots.clear()
        for s in self._reserved.values():
            s.clear()

        free = [(i, j) for i in range(GRID_N) for j in range(GRID_N)]
        random.shuffle(free)
        for rid in range(count):
            kind = KIND_AERIAL if random.random() < AERIAL_FRACTION else KIND_GROUND
            cx, cz = free[rid % len(free)]
            r = Robot(rid, kind, cx, cz)
            self._reserved[kind].add((cx, cz))
            self.robots.append(r)
        self.scatter_goals()

    def scatter_goals(self) -> None:
        for r in self.robots:
            r.gx = random.randrange(GRID_N)
            r.gz = random.randrange(GRID_N)

    def assign_goal(self, rid: int, gx: int, gz: int) -> bool:
        if 0 <= rid < len(self.robots):
            self.robots[rid].gx = max(0, min(GRID_N - 1, gx))
            self.robots[rid].gz = max(0, min(GRID_N - 1, gz))
            return True
        return False

    # -- simulation ---------------------------------------------------------

    def step(self) -> None:
        if self.paused:
            return
        self.tick += 1
        self.sim_time += DT

        # Priority: robots closest to their goal move first. Ties broken
        # randomly so the same robot does not always win a contested cell,
        # which is what produces livelock in naive prioritised planners.
        order = sorted(
            self.robots,
            key=lambda r: (math.dist((r.cx, r.cz), (r.gx, r.gz)), random.random()),
        )

        for r in order:
            self._advance(r)

    def _advance(self, r: Robot) -> None:
        target_x, target_z = cell_to_world(r.tx), cell_to_world(r.tz)
        dx, dz = target_x - r.x, target_z - r.z
        dist = math.hypot(dx, dz)
        step = r.max_speed * DT
        occupied = self._reserved[r.kind]

        if dist > 1e-4:
            # In transit. The robot holds TWO cells while crossing: the one it
            # is physically leaving and the one it has reserved. Releasing the
            # origin cell at departure instead of at arrival is a classic bug:
            # another robot claims the cell while this one is still standing
            # in it, and they visibly overlap mid-crossing.
            if dist <= step:
                r.x, r.z = target_x, target_z
                occupied.discard((r.cx, r.cz))     # release origin on ARRIVAL
                r.cx, r.cz = r.tx, r.tz
            else:
                r.x += dx / dist * step
                r.z += dz / dist * step
                r.heading = math.atan2(dx, dz)
            r.speed = r.max_speed
            r.status = STATUS_MOVING
            return

        # ---- arrived, choose the next cell ----------------------------------
        if (r.cx, r.cz) == (r.gx, r.gz):
            r.speed = 0.0
            r.status = STATUS_IDLE
            r.blocked_ticks = 0
            # An idle robot still occupies a cell, and a cell parked in the
            # middle of a corridor is a permanent obstacle for everyone else.
            # Re-tasking after a short dwell keeps the floor from silting up.
            r.idle_ticks += 1
            if r.idle_ticks >= IDLE_DWELL_TICKS:
                r.idle_ticks = 0
                r.gx, r.gz = random.randrange(GRID_N), random.randrange(GRID_N)
            return

        r.idle_ticks = 0

        # Preference order: primary axis (X) first, then the secondary axis.
        # This is the prioritised strategy from the warehouse planner.
        cands: list[tuple[int, int]] = []
        if r.cx != r.gx:
            cands.append((r.cx + (1 if r.gx > r.cx else -1), r.cz))
        if r.cz != r.gz:
            cands.append((r.cx, r.cz + (1 if r.gz > r.cz else -1)))

        # DEADLOCK ESCAPE.
        # Strict prioritised planning with no alternative action deadlocks:
        # every robot waits on a cell held by a robot that is itself waiting.
        # Measured on this map it degrades from ~20% blocked to ~77% blocked
        # within 120 ticks and never recovers. After a robot has been stuck for
        # ESCAPE_AFTER_TICKS it will accept ANY free neighbour, even one that
        # increases its distance to goal. Taking a locally worse move to break
        # a global deadlock is the whole idea.
        if r.blocked_ticks >= ESCAPE_AFTER_TICKS:
            detour = [(r.cx + 1, r.cz), (r.cx - 1, r.cz),
                      (r.cx, r.cz + 1), (r.cx, r.cz - 1)]
            random.shuffle(detour)
            cands.extend(detour)

        for nx, nz in cands:
            if not (0 <= nx < GRID_N and 0 <= nz < GRID_N):
                continue
            if (nx, nz) in occupied:
                continue
            occupied.add((nx, nz))            # reserve destination now,
            r.tx, r.tz = nx, nz               # origin is released on arrival
            r.status = STATUS_MOVING
            r.blocked_ticks = 0
            return

        # Everything it could move into is taken. Hold position this tick.
        r.speed = 0.0
        r.status = STATUS_BLOCKED
        r.blocked_ticks += 1

    # -- serialisation ------------------------------------------------------

    def encode(self) -> bytes:
        n = len(self.robots)
        buf = bytearray(HEADER.size + ROBOT.size * n)
        HEADER.pack_into(buf, 0, self.tick, self.sim_time, n, 0)
        off = HEADER.size
        for r in self.robots:
            ROBOT.pack_into(buf, off, r.x, r.z, r.heading, r.speed, r.status, r.kind)
            off += ROBOT.size
        return bytes(buf)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

fleet = Fleet()
clients: set[WebSocket] = set()


async def sim_loop() -> None:
    """
    Fixed-rate loop. Sleeps to the next deadline rather than sleeping DT, so
    the tick rate does not drift under load. If a tick overruns we skip ahead
    instead of accumulating debt.
    """
    next_deadline = asyncio.get_event_loop().time()
    while True:
        fleet.step()
        if clients:
            frame = fleet.encode()
            dead = []
            for ws in clients:
                try:
                    await ws.send_bytes(frame)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                clients.discard(ws)

        next_deadline += DT
        delay = next_deadline - asyncio.get_event_loop().time()
        if delay < 0:
            next_deadline = asyncio.get_event_loop().time()
            delay = 0
        await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(sim_loop())
    yield
    task.cancel()


app = FastAPI(title="XR Fleet Operations Console", lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_text(json.dumps({
        "type": "hello",
        "tick_hz": TICK_HZ,
        "grid_n": GRID_N,
        "cell": CELL,
        "robot_count": len(fleet.robots),
    }))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "assign_goal":
                fleet.assign_goal(int(msg["id"]), int(msg["gx"]), int(msg["gz"]))
            elif kind == "scatter":
                fleet.scatter_goals()
            elif kind == "set_count":
                fleet.resize(int(msg["n"]))
                await ws.send_text(json.dumps({
                    "type": "hello", "tick_hz": TICK_HZ, "grid_n": GRID_N,
                    "cell": CELL, "robot_count": len(fleet.robots),
                }))
            elif kind == "pause":
                fleet.paused = True
            elif kind == "resume":
                fleet.paused = False
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


# Serving the frontend from the same origin as the WebSocket avoids CORS and
# keeps this a one-process app. localhost counts as a secure context, which is
# what WebXR requires, so no TLS setup is needed for local development.
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
