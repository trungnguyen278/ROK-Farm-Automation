# UI Dashboard

> **AI Note:** tkinter dashboard chạy trên Main thread (tkinter bắt buộc). Logic chạy trên worker threads. 5 tab: Control, Monitor, Config, Profile, Stats. Tự detect ROK window qua shortcut `C:\Users\Public\Desktop\Rise of Kingdoms.lnk`.

## Layout

```
┌─────────────────────────────────────────────────────┐
│  ROK Farm Automation                        [─][□][×]│
├──────┬──────┬──────┬──────┬──────┬──────────────────┤
│Control│Monitor│Config│Profile│Stats│                  │
├──────┴──────┴──────┴──────┴──────┤                  │
│                                   │   Log Panel      │
│   Tab Content Area                │   (scrollable)   │
│   (changes per tab)               │                  │
│                                   │                  │
│                                   │                  │
├───────────────────────────────────┤                  │
│ Status Bar: state | session time  │                  │
│ | actions/min | ESP32 status      │                  │
└───────────────────────────────────┴──────────────────┘
```

## Tab 1: Control

```
┌─────────────────────────────────┐
│ Game: [Rise of Kingdoms ▾] [Launch] [Detect]  │
│                                               │
│ Strategy: [basic_gather ▾]                    │
│ Profile:  [default ▾]                         │
│                                               │
│ ┌─────────┐ ┌──────────┐ ┌──────────┐        │
│ │ ▶ START  │ │ ⏸ PAUSE  │ │ ■ STOP   │        │
│ └─────────┘ └──────────┘ └──────────┘        │
│                                               │
│ ESP32: COM3 [Connected ●]  [Reconnect]        │
│ State: CITY_VIEW  | Session: 12m 34s          │
└───────────────────────────────────────────────┘
```

### Game Launch
```python
# Resolve .lnk shortcut to target exe path
import win32com.client
shell = win32com.client.Dispatch("WScript.Shell")
shortcut = shell.CreateShortCut(r"C:\Users\Public\Desktop\Rise of Kingdoms.lnk")
game_exe = shortcut.Targetpath
subprocess.Popen(game_exe)
```

## Tab 2: Monitor

```
┌─────────────────────────────────┐
│ ┌─────────────────────────┐     │
│ │                         │     │
│ │   Game Screenshot       │     │
│ │   (resized preview)     │     │
│ │   + Vision overlay      │     │
│ │   (matched templates    │     │
│ │    drawn as rectangles) │     │
│ │                         │     │
│ └─────────────────────────┘     │
│ Refresh: [Auto 1s ▾] [Manual]  │
│                                 │
│ Matches: ok_btn(0.92) @(340,520)│
│ State: CITY_VIEW (conf: 0.95)  │
└─────────────────────────────────┘
```

### Screenshot Display
```python
# Convert OpenCV frame → tkinter PhotoImage
from PIL import Image, ImageTk
frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
img = Image.fromarray(frame_rgb).resize((640, 360))
photo = ImageTk.PhotoImage(img)
canvas.create_image(0, 0, anchor="nw", image=photo)

# Draw match rectangles overlay
for match in matches:
    canvas.create_rectangle(
        match.x * scale, match.y * scale,
        (match.x + match.w) * scale, (match.y + match.h) * scale,
        outline="lime", width=2
    )
```

## Tab 3: Config

```
┌─────────────────────────────────┐
│ Serial                          │
│   Port: [COM3    ▾]  Baud: 115200│
│   Heartbeat: [2.0]s             │
│                                 │
│ Capture                         │
│   Window: [Rise of Kingdoms   ] │
│   FPS: [5]                      │
│                                 │
│ Vision                          │
│   Threshold: [0.8] ████████░░   │
│   Scales: [0.8,0.9,1.0,1.1,1.2]│
│                                 │
│ Session                         │
│   Farm: [25]±[8] min            │
│   Break: [8]±[3] min            │
│   Daily max: [6] hrs            │
│   Active: [08:00]-[23:00]       │
│                                 │
│        [Save] [Reset Default]   │
└─────────────────────────────────┘
```

## Tab 4: Profile

```
┌─────────────────────────────────┐
│ Active: [default ▾]  [New] [Del]│
│                                 │
│ Mouse          │ Timing         │
│  Speed: [400]  │  Delay: [1200] │
│  Spread: [8]px │  Std: [400]    │
│  Overshoot: 15%│  Pause: 20%    │
│  Misclick: 1%  │  Fatigue: ON   │
│  Jitter: [2]px │                │
│                │                │
│        [Save Profile]           │
└─────────────────────────────────┘
```

## Tab 5: Stats

```
┌─────────────────────────────────┐
│ Session: 2h 15m  │ Today: 5h 30m│
│ Actions: 1,247   │ Errors: 3    │
│ Gathers: 42      │ Trains: 18   │
│                                 │
│ Actions/min ████████████░░ 9.2  │
│ Error rate  █░░░░░░░░░░░░ 0.2% │
│                                 │
│ Session History (last 7 days)   │
│ ┌─────────────────────────────┐ │
│ │ Mon ████████ 4.2h           │ │
│ │ Tue ██████████ 5.1h         │ │
│ │ Wed ███████ 3.8h            │ │
│ │ ...                         │ │
│ └─────────────────────────────┘ │
│         [Export CSV]            │
└─────────────────────────────────┘
```

## Files

```
ui/
├── __init__.py
├── app.py              # MainApp(tk.Tk), tab manager, startup
├── tab_control.py      # Start/stop, strategy, ESP32 status
├── tab_monitor.py      # Screenshot + vision overlay
├── tab_config.py       # Config editor, save/load
├── tab_profile.py      # Profile editor
├── tab_stats.py        # Statistics, charts, export
├── log_panel.py        # Scrollable log widget (right side)
├── status_bar.py       # Bottom status bar
└── utils.py            # LNK resolver, image conversion helpers
```

## Threading Model (updated)

```
Main Thread (tkinter)
  ├── UI event loop (app.mainloop)
  ├── Periodic refresh: after(1000, update_ui)
  │
  ├── Worker: Capture Thread
  ├── Worker: Logic Thread (was Main Thread in original design)
  └── Worker: Serial Thread
```

> **Change from original:** Logic thread tách ra khỏi Main thread vì tkinter phải chạy trên main thread.

## Dependencies (thêm)

```
Pillow>=10.0          # PIL for image display in tkinter
pywin32>=306          # win32com for .lnk shortcut resolution
```

## Key Implementation Patterns

```python
# Thread-safe UI update
def update_from_worker(self, data):
    self.after(0, self._apply_update, data)  # schedule on main thread

# Log panel append (thread-safe)
def log(self, msg: str, level: str = "INFO"):
    self.log_queue.put((level, msg))
    # main thread polls log_queue via after()
```

## Game Window Co-location

```python
# Position UI next to game window
import win32gui
game_hwnd = win32gui.FindWindow(None, "Rise of Kingdoms")
gx, gy, gw, gh = win32gui.GetWindowRect(game_hwnd)
# Place UI to the right of game
app.geometry(f"500x700+{gw + 10}+{gy}")
```
