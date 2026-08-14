# Templates

OpenCV templates used by `run_farm.py`.

## Directory Structure

```text
templates/
buttons/    # gather, march, city/world-map buttons
resources/  # gem icon and gem mine templates
states/     # city/world-map state hints
ui/         # close/reconnect/mail/alliance templates used by popup handling
```

## Capture

Use `tools/capture_templates.py` when you need to recapture a stable UI element.
Template names are referenced without `.png`, for example `buttons/gather_btn`.
