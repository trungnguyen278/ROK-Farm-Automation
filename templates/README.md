# Templates

Place game screenshot templates here. PNG format, BGR color.

## Directory Structure

```
templates/
├── buttons/       # ok.png, cancel.png, attack.png, ...
├── popups/        # march_confirm.png, scout_report.png, ...
├── states/        # city_view.png, world_map.png, ...
└── resources/     # food_icon.png, wood_icon.png, ...
```

## How to Capture

1. Open ROK on PC
2. Navigate to target screen/state
3. Use Snipping Tool or similar to crop the unique UI element
4. Save as PNG in the appropriate subdirectory
5. Name should match the template_name used in code (e.g., `states/city_view.png`)
