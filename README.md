<<<<<<< HEAD
# XR Fleet Operations Console

A browser-based operations console for a simulated robot fleet. A Python
backend runs a multi-agent warehouse simulation and streams robot poses over a
binary WebSocket at a fixed 20 Hz. A WebXR-capable three.js frontend renders
the entire fleet in a single instanced draw call with a hand-written GLSL
shader, interpolates between server snapshots, and lets you select a robot and
send it to a cell either with a mouse or with an XR controller.

```
server/main.py     FastAPI + WebSocket, 20 Hz fixed-tick fleet simulation
web/index.html     three.js + WebXR client, single file, no build step
```

## Run it

Requires Python 3.10+.

```bash
cd xr-fleet-console
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r server/requirements.txt
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>.

`localhost` counts as a secure context, which is what WebXR requires, so no TLS
setup is needed for local development. The frontend is served by the same
FastAPI process as the WebSocket, so there is no CORS configuration and no
second dev server.

**Controls.** Drag to orbit. Click a robot to select it, then click the floor to
send it there. The "Enter VR" button appears when a WebXR device or emulator is
available; in a session, the controller trigger does both actions.

**Without a headset.** Install the
[WebXR API Emulator](https://chromewebstore.google.com/detail/webxr-api-emulator/mjddjgeghkdijejnciaefnkjmkafnnje)
extension for Chrome, open DevTools, pick the WebXR tab, and choose a device.
That is enough to develop and demo the immersive path. It is **not** enough to
claim a measured on-device frame rate. If you own an Android phone with ARCore,
Chrome there runs real WebXR sessions and gives you a genuine device number.

## What to look at in the HUD

| Field | What it tells you |
|---|---|
| `cpu frame` | JS time per frame. Turns amber over 8 ms, red over 13.9 ms. |
| `budget @72Hz` | 13.9 ms. A Quest at 72 Hz gives you this much for *both* eyes. |
| `draw calls` | Should stay at roughly 4 whether you render 100 or 3000 robots. |
| `net latency` | Mean gap between server packets. Should hover near 50 ms at 20 Hz. |

Change the robot count in the dropdown and watch `draw calls` refuse to move.
That is the whole point of instancing.

## Design decisions worth defending

**One instanced draw call, not N meshes.** Draw calls are CPU-side driver
validation and state setup. XR pays that cost twice, once per eye. 3000
separate meshes will stall long before 3000 instances will.

**Binary frames, not JSON.** A frame is `16 + 24 * N` bytes: 12 KB for 500
robots, 72 KB for 3000. At 20 Hz, JSON would mean building and parsing
thousands of objects per second on the render thread, and the garbage collector
would show up as periodic frame spikes.

**Fixed 20 Hz sim, decoupled from render rate.** Simulation must not depend on
how fast the client's GPU happens to be. The client renders 60 ms in the past
so it always has two snapshots to interpolate between, rather than
extrapolating past the newest data every frame.

**Preallocated buffers, no per-frame allocation.** Instance matrices and
attribute arrays are written in place. One reused `Matrix4`, not 500 new ones
per frame.

**GPU-side animation.** The aerial hover bob runs in the vertex shader from a
uniform clock. Doing it on the CPU would mean rewriting every instance matrix
each frame for a purely cosmetic effect.

**Two-cell reservation during transit.** A robot holds both the cell it is
leaving and the cell it has reserved, releasing the origin only on arrival.
Releasing at departure lets another robot claim a cell that is still physically
occupied, and they visibly overlap mid-crossing.

**Deadlock escape.** Strict prioritised planning with no alternative action
gridlocks: every robot waits on a cell held by another waiting robot. Measured
on this map it degraded from about 20% blocked to 77% blocked within 120 ticks
and never recovered. After four blocked ticks a robot will accept any free
neighbour, even one that increases its distance to goal. Taking a locally worse
move to break a global deadlock is the entire idea. With the escape action the
blocked fraction plateaus around 11 to 17% at 500 robots.

## Verified

Checked programmatically against a running server:

- 20.3 Hz sustained tick rate, contiguous tick numbers, no dropped frames
- Frame size exactly matches the declared wire format at 500 and 3000 robots
- All robots stay inside world bounds; no NaN; status and kind always in range
- Per-tick displacement never exceeds max speed times dt (no teleporting)
- Zero same-plane robot pairs closer than 0.75 world units (no clipping)
- 500 goal commands applied over the WebSocket; mean grid distance to the
  commanded corner fell from 39.4 to 22.2 over 300 ticks
- Pause freezes the tick counter; resize reallocates and re-acks correctly
- Frontend passes `node --check` with no syntax errors

Frontend raycasting was verified separately by running three.js headless in
Node with the same camera, rig transform and instance layout: every on-screen
robot projects to a pixel that raycasts back to its own `instanceId`.

**Not verified:** the frontend has not been rendered by a real GPU or a headset
from this environment. Run it, confirm it draws, and record your own frame
numbers before quoting any.

### Fixed after first run

The first version scaled the world rig to 0.06 permanently, for XR ergonomics.
On desktop that made every robot about **0.4 pixels tall**: technically
rendered, technically clickable by a raycast, impossible to see or hit with a
mouse. The rig is now 1:1 on desktop and only shrinks to a tabletop diorama on
`sessionstart`. Related fixes: fog moved out past the camera distance, a manual
bounding sphere on the `InstancedMesh` so `raycast()` cannot early-out on a
stale cached sphere, robot bodies enlarged to most of a cell, and selection
moved to `pointerup` with a 5 px threshold so orbit drags no longer fire a
selection.

## Before you put this on a resume

Answer these four without looking at the code. If you cannot, the project is a
liability in an interview, not an asset.

1. Why one `InstancedMesh` instead of 500 meshes? What specifically gets
   expensive, and why does XR make it worse?
2. Why binary over the wire instead of JSON at 20 Hz? Name the two costs.
3. Why render 60 ms in the past instead of drawing the newest snapshot
   immediately? What does the failure look like on screen?
4. What is your per-frame budget at 72 Hz, and what is your measured `cpu frame`
   at 500 robots on your machine?

There are also two marked exercises in the shader in `web/index.html`. Work
through them. They are the difference between having used a shader and
understanding one.

## Honest resume line

Only claim what you measured on your own hardware:

> Rendered a 500 robot fleet in a WebXR-capable three.js console, batched all
> agents into a single instanced draw call with a custom GLSL shader and
> interpolated 20 Hz binary pose updates streamed from a FastAPI WebSocket
> backend, sustaining NN fps at N.N ms CPU frame time.

Do not write "shipped to headset" unless you shipped to a headset.
=======
# XR-fleet-console
>>>>>>> 5073bcaaeebf8b57fe14f098cfd0c47764d335d8
