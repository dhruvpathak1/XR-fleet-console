# XR Fleet Operations Console

A web page where you can watch a warehouse full of robots move around in 3D, click one, and tell it where to go. It also works in VR.

Everything runs on your own machine. No accounts, no cloud services, no build step.

![screenshot](/screenshot.png)

<!-- Take a screenshot of the running app and save it as docs/screenshot.png -->

## What it does

- A Python program pretends to be a warehouse with up to 3000 robots in it. The robots pick destinations, drive toward them, and get out of each other's way.
- Twenty times a second, it sends every robot's position to your browser.
- Your browser draws all of them in 3D, in real time.
- You can click a robot to select it, then click the floor to send it there.
- If you have a VR headset, you can put it on and see the warehouse as a table-sized model in front of you, and point at robots with the controller.

Colours tell you what each robot is doing:

| Colour | Meaning |
|---|---|
| Blue to green | Driving. Greener means faster. |
| Amber | Blocked. Something is in the way. |
| Grey | Idle. Sitting at its destination. |
| Flashing white | Currently selected. |

## Getting started

You need **Python 3.10 or newer**. Check with `python3 --version`.

**1. Open a terminal in the project folder.**

**2. Create a virtual environment.** This keeps the project's packages separate from the rest of your system.

```bash
python3 -m venv .venv
```

**3. Activate it.**

```bash
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows
```

You'll know it worked when `(.venv)` appears at the start of your terminal prompt.

**4. Install the two packages it needs.**

```bash
pip install -r server/requirements.txt
```

**5. Start it.**

```bash
python -m uvicorn server.main:app --port 8000
```

**6. Open <http://127.0.0.1:8000> in your browser.**

You should see a dark grid with a few hundred small blocks moving around on it.

To stop the server, press `Ctrl+C` in the terminal.

## How to use it

| Action | How |
|---|---|
| Look around | Click and drag |
| Zoom | Scroll |
| Select a robot | Click it |
| Send it somewhere | With a robot selected, click a spot on the floor |
| Change fleet size | Use the dropdown, bottom left |
| Shuffle destinations | Click "Scatter goals" |
| Freeze everything | Click "Pause" |

The panel in the top left shows live statistics. The one worth watching is **draw calls**: switch from 100 robots to 3000 and notice it barely changes. That is the main trick this project is built around, explained below.


To try the VR view without owning a headset, install the free
[WebXR API Emulator](https://chromewebstore.google.com/detail/webxr-api-emulator/mjddjgeghkdijejnciaefnkjmkafnnje)
extension for Chrome, then open DevTools (F12), find the **WebXR** tab, and pick a device. The "Enter VR" button will start working.

## How it works

```
   Python (server)                          Browser (client)
   ┌──────────────────┐                     ┌──────────────────┐
   │  warehouse sim   │   20 times/second   │  three.js draws  │
   │  moves robots    │ ──── positions ───► │  all robots in   │
   │  20 times/second │                     │  3D, 60+ fps     │
   │                  │ ◄─── commands ───── │  you click stuff │
   └──────────────────┘                     └──────────────────┘
```

Three ideas do most of the work:

**Drawing 3000 robots as if they were one object.** Normally, each object you draw costs the graphics card a separate instruction from the CPU. Three thousand robots would mean three thousand instructions per frame, and everything would crawl. Instead all robots share one shape and one instruction, with a list of positions attached. This is called *instancing*. It's why the "draw calls" number stays flat no matter how many robots there are.

**Sending positions as raw numbers, not text.** Most web apps send data as JSON, which is text your browser has to read and convert. At twenty updates a second with hundreds of robots, that adds up fast. This sends the numbers directly instead: 24 bytes per robot, about 12 KB per update for 500 robots. The browser reads them without any conversion work.

**Smoothing between updates.** The server only sends positions 20 times a second, but the screen refreshes 60 or more times a second. If the browser just drew the newest position each time, the robots would visibly stutter. Instead it deliberately draws what happened 60 milliseconds ago, which lets it blend smoothly between the last two updates.

There is more detail, including the bugs found while building this and how they were fixed, in [NOTES.md](NOTES.md).

## Project structure

```
server/
  main.py            the warehouse simulation and the WebSocket server
  requirements.txt   the two packages needed
web/
  index.html         the entire frontend: 3D view, shaders, controls
```

That's it. Two files of real code. The frontend loads three.js straight from a CDN, so there is no `npm install` and no build step.

## Built with

| Piece | What it does |
|---|---|
| [Python](https://www.python.org/) + [FastAPI](https://fastapi.tiangolo.com/) | Runs the simulation, serves the page, handles the WebSocket |
| [three.js](https://threejs.org/) | Draws 3D graphics in the browser |
| [WebXR](https://immersiveweb.dev/) | The browser standard for VR and AR |
| GLSL | The small shader program that colours each robot on the graphics card |
| WebSockets | Keeps a live two-way connection open between browser and server |

## Known limitations

- The robots are simulated. There is no real hardware behind this.
- Path planning is deliberately simple: robots move along one axis, then the other. It is not A* and it is not optimal.
- Tested on desktop Chrome. The VR path has been tested with the WebXR emulator, not on a physical headset.

## License

MIT
