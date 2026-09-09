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
