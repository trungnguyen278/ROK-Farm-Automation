# Setup guide — ROK Farm

Written for someone who is **not technical**. Follow it in order.

Bản tiếng Việt: [SETUP.vi.md](SETUP.vi.md)

---

## What you need

| | |
|---|---|
| PC | Windows 10 or 11 |
| Game | Rise of Kingdoms for PC, installed and logged in at least once |
| Board | ESP32-S3 DevKitC-1, the **N16R8** variant |
| Cable | A USB **data** cable — see the warning below |
| Discord | A Discord account, if you want to control it from your phone |

### ⚠️ The USB cable is the most common failure

A charge-only cable and a data cable **look identical**. With the wrong one the
PC never sees the board, and the app reports "no board found" — exactly what it
reports when nothing is plugged in at all.

**If the app says it cannot find the board, change the cable first.**

### ⚠️ The ESP32-S3 has TWO USB sockets

Read the silkscreen next to each socket:

- **UART** or **COM** — use this one
- **USB** or **OTG** — the other one; the app **cannot flash** through it

Get it wrong and the app says so: *"Found the board's native USB socket — move
the cable to the UART/COM socket."*

---

## Option 1 — The packaged app (recommended)

No Python, no installation.

### Step 1. Extract

Extract `ROK-Farm-portable.zip` into a plain folder, e.g. `D:\ROKFarm`.

> Do not run it from inside the zip. Windows opens that in a temp folder, and
> everything the app writes — screenshots, logs, your settings — disappears.

### Step 2. Run it

Right-click `ROK Farm.exe` → **Run as administrator**.

> Why admin: Rise of Kingdoms' `launcher.exe` requires administrator rights.
> If the app already has them, the launcher starts silently. If not, Windows
> shows a UAC prompt — and the **bot cannot click it for you**, because
> Windows' secure desktop is invisible to every screen-capture method.

### Step 3. Pick item 1 — First-run setup

Five steps. Each one reports what it found before changing anything, so
**re-running it is safe** — that is also how you fix a step that went wrong.

| Step | What it does | What you do |
|---|---|---|
| 1 | Check libraries | Nothing (the packaged build always has them) |
| 2 | Find the board, flash it | Plug the board into the UART/COM socket |
| 3 | Find Rise of Kingdoms | Paste the path if it cannot find it |
| 4 | Configure Discord | Paste a token + your user ID (see below) |
| 5 | Summary | Read which steps did not finish |

**Step 2 is the important one — and you build nothing.** The prebuilt firmware
ships in the `firmware/` folder. The app finds the board, checks whether it is
already flashed, and only writes when it needs to:

- Already flashed → it asks PING, the board answers PONG, flashing is skipped
- Blank board → it flashes, waits for the reboot, then verifies

Do not unplug it while it is writing.

### Step 4. Start farming

Back at the menu → **item 2**.

> **Prefer the game CLOSED before you press it.** The bot launches it itself.
> Attaching to a client already running in the background **costs the first
> three mines**: ROK stops redrawing when it is not in front, the capture layer
> keeps handing back the last frame it got, and the flow fails mine after mine
> for about 75 seconds.

---

## Option 2 — From source

For people who want to change the code.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Flash the board (uses the prebuilt images, no PlatformIO needed):

```powershell
.venv\Scripts\python tools\flash_board.py --check    # what is attached
.venv\Scripts\python tools\flash_board.py            # flash if needed
```

Run:

```powershell
.venv\Scripts\python -m app.main            # the menu
.venv\Scripts\python run_farm.py --count 2  # straight to the farm
```

Rebuild the firmware from the C++ source (only if you edit
`esp32-s3/src/main.cpp`):

```powershell
cd esp32-s3
pio run
```

> Run `pio` from **PowerShell or CMD**, never Git Bash — the pioarduino
> installer refuses MSys/Mingw environments and fails with an unhelpful error.

---

## Controlling it from your phone, over Discord

The Discord bot is the day-to-day interface: start and stop the farm and look
at screenshots from anywhere.

### Create the bot

1. <https://discord.com/developers/applications> → **New Application** → name it
2. **Bot** tab → **Reset Token** → copy it. **Shown ONCE.**
3. Same tab, scroll to **Privileged Gateway Intents** → turn on
   **MESSAGE CONTENT INTENT** → **Save Changes**

   Without it the bot receives empty message text in a server and every command
   silently does nothing. (DMs to the bot work either way — that is the
   fallback if the checkbox gets missed.)

### Invite it to your server

Take the **Application ID** from *General Information* and open:

```
https://discord.com/api/oauth2/authorize?client_id=<APPLICATION_ID>&permissions=101376&scope=bot
```

`101376` = View Channel + Send Messages + Attach Files + Read Message History.
Nothing more.

### Get your IDs

Discord → **Settings** → **Advanced** → turn on **Developer Mode**. Then:

- right-click **your own name** → *Copy User ID* → `DISCORD_OWNER_ID`
- right-click the **channel** → *Copy Channel ID* → `DISCORD_CHANNEL_ID` (optional)

> The bot **obeys exactly one account**. Commands from anyone else are ignored
> and logged. With `DISCORD_OWNER_ID` unset it **refuses to start** — no remote
> control is better than one anybody can press.

### Start the bot

Menu → **item 4**. It posts "Bot online" in the pinned channel.

### Commands

| Command | What it does |
|---|---|
| `!status` | Farm / watchdog / game state, counters, planned-wait countdown |
| `!shot` | Screenshot of the game right now |
| `!log [n]` | Last n interesting log lines (default 25) |
| `!report` | Full report, posted as a text file |
| `!start` | Farm + watchdog |
| `!start solo` | Farm only, nothing supervising it |
| `!start force` | Start even though someone is using the machine |
| `!stop` | Stop the farm, close the client, board jitter off |
| `!stop keep` | ...but leave the client running |

> `!start` **refuses** if there has been real input in the last 5 minutes,
> because the ESP32 would otherwise fight you for the mouse. That refusal is
> the feature; `force` is the answer.

---

## When something goes wrong

| Symptom | Usual cause |
|---|---|
| "No board found" | Charge-only cable. **Change the cable first.** |
| "Found the native USB socket" | Wrong socket. Move to **UART/COM**. |
| Flashed but no answer | Unplug and replug once. |
| Flashing keeps failing | Hold the **BOOT** button while plugging the cable in. |
| Answers PING but Windows shows no mouse | Unplug and replug. |
| Farm runs but the mouse never moves | An older farm process still holds the COM port. Menu item 3 stops everything. |
| Loses the first three mines every run | You started with the game already open. Close it and start again. |
| A UAC prompt appears and nothing happens | Run the app with **Run as administrator**. |
| Closing the menu leaves the farm running | By design. It runs detached. Stop it with **item 3** or `!stop`. |
| The Discord bot ignores commands in a server | **MESSAGE CONTENT INTENT** is off. |

### Where the logs are

```
logs\overnight\farm_run.log      what the farm is doing
logs\overnight\watchdog.log      what the supervisor sees
logs\overnight\discord_bot.log   commands the bot received
screenshots\gem_farm_test\       frames the bot saved
```

---

## Things worth knowing

**Closing the menu does NOT stop the farm.** It is launched detached, on
purpose: restarting the menu or the bot must never take a live run down.
Stop it with menu item 3, or `!stop` in Discord.

**Stopping always releases the board.** Killing the farm process alone leaves
the ESP32 nudging the pointer — the first thing you notice when you try to use
the machine. Item 3 and `!stop` both turn that off.

**The bot closes the game with ALT+F4, never a process kill.** A hard kill
reads as a crash.

**`!shot` shows the whole client.** Keep your Discord server private.
