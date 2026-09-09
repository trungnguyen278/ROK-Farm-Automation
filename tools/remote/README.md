# Discord remote control

Start, stop, and look at the farm from a phone. Runs entirely on this machine
and costs nothing — it talks to Discord's gateway and nothing else.

It is a **switch and a window, not a brain**. It cannot diagnose a wedged farm;
`watchdog2.py` still owns restarts. `!status` summarises the log, it does not
judge whether the run is healthy.

## Setup (once)

**1. Create the bot**

- <https://discord.com/developers/applications> → *New Application* → name it
- *Bot* tab → *Reset Token* → copy the token (shown once)
- Same tab, scroll to **Privileged Gateway Intents** → turn on
  **MESSAGE CONTENT INTENT** → *Save Changes*

  Without it the bot receives empty message text in the server and every
  command silently does nothing. (DMs to the bot work either way — that is the
  fallback if the checkbox gets missed.)

**2. Invite it to the server**

Take the *Application ID* from the *General Information* tab and open:

```
https://discord.com/api/oauth2/authorize?client_id=<APPLICATION_ID>&permissions=101376&scope=bot
```

`101376` = View Channel + Send Messages + Attach Files + Read Message History.
Nothing else — the bot never needs to manage the server.

**3. Get the two ids**

Discord → *Settings* → *Advanced* → **Developer Mode** ON. Then:

- right-click your own name → *Copy User ID* → `DISCORD_OWNER_ID`
- right-click `#chung` → *Copy Channel ID* → `DISCORD_CHANNEL_ID` (optional)

**4. Fill in `.env`**

Copy `.env.example` to `.env` at the project root (already gitignored) and fill
in the three values.

## Run

Double-click `tools\remote\start_bot.bat`. It relaunches the bot after a crash
or a dropped gateway connection — a remote control that quietly dies is worse
than none, because you only find out when you need it. Close the window to stop.

To have it up after every reboot: Task Scheduler → *Create Basic Task* →
trigger *When I log on* → action *Start a program* → point it at
`D:\ROK Farm Automation\tools\remote\start_bot.bat`.

Or, for one run in the foreground:

```
.venv\Scripts\python tools\remote\discord_bot.py
```

If the bot is in no server yet, the log prints a ready-made invite link for it.

Leave it running. It survives farm restarts and can control a run it did not
launch — the farm and watchdog are found by scanning command lines, not by a
remembered pid, so the bot itself can be restarted at any time.

## Starting a farming session

**1. Start the bot** (once — it can control runs it did not launch):

Double-click `tools\remote\start_bot.bat`. It posts "Bot online" in `#chung`
when it is ready.

**2. Start the farm** — from Discord, or locally.

From Discord: send `!start` in `#chung`. If you are sitting at the machine it
will refuse and ask for `!start force`, because the ESP32 would otherwise
fight you for the mouse. That refusal is the feature; `force` is the answer.

Locally, without the bot:

```
.venv\Scripts\python tools\dev\overnight\farm_full.py
```

and, in a second window, the supervisor (it needs the farm's pid):

```
.venv\Scripts\python tools\dev\overnight\watchdog2.py <farm pid>
```

The bot's `!start` does both, and starts the farm detached so restarting the
bot cannot take a live run down with it.

**Prefer starting with the game CLOSED.** The farm launches it itself. Attaching
to a client that is already running and sitting in the background costs the
first three mines: ROK stops redrawing when it is not in front, WGC keeps
handing back the last frame it got, and the flow fails mine after mine on an
identical template score for about 75 seconds before the frame stream resumes.
Measured on 2026-09-09: three runs that attached to a backgrounded client lost
mines 1-3 every time; the one run that launched the game itself lost none.

## Stopping

`!stop` in Discord, or `!stop game` to close the client too. Either way the
ESP32's idle jitter is turned off — the farm leaves it on while tabbed away,
and a board still nudging the pointer is the thing you notice first.

To stop the bot itself, close the `start_bot.bat` window.

## After a run

```
.venv\Scripts\python tools\dev\overnight\report.py
```

Throughput per segment, why mines failed, and the timings measured in
production rather than assumed.

## Commands

| | |
|---|---|
| `!status` | farm / watchdog / game state, counters for the current run, planned-wait countdown |
| `!shot` | screenshot of the game right now; falls back to the newest saved frame if the client is closed |
| `!log [n]` | last n interesting log lines (default 25, DEBUG and capture chatter stripped) |
| `!report` | full `report.py` output, posted as a text file |
| `!start` | farm + watchdog |
| `!start solo` | farm only, nothing supervising it |
| `!start force` | start even though someone is using the machine |
| `!stop` | stop farm + watchdog, turn ESP32 idle jitter off |
| `!stop game` | ...and close the client too |

The bot also speaks up on its own: when the farm process disappears it posts
the last few log lines to the pinned channel (or to wherever you last talked to
it, if no channel is pinned).

## Safety properties

- **Owner-locked.** Commands from any other account are ignored and logged.
  With `DISCORD_OWNER_ID` unset the bot refuses to start at all rather than
  exposing an unlocked control surface.
- **`!stop` always releases the HID.** `_tab_out()` leaves the ESP32 doing idle
  micro-jitter; killing the farm without turning it off leaves the board
  nudging a pointer the human is trying to use.
- **`!start` checks for a human.** If there has been real input in the last
  5 minutes it asks for `!start force` instead, because the ESP32 would
  otherwise fight the player for the mouse.
- **Screenshots show the whole client.** Keep the server private.
