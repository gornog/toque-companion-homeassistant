# AI Agent Guide — Installing & Customizing the Toque Companion Dashboard Tile

Use this guide when a Home Assistant user asks you to add the **Monsieur Cuisine Connect (Toque)** interactive tile to their dashboard.

## 1. Check Prerequisites First (Read-Only)

1. Confirm the **`toque_companion`** custom integration is installed and active in Home Assistant.
2. Confirm **`custom:button-card`** (from HACS) is registered in the user's Home Assistant Lovelace resources. If it is missing, ask the user to install `button-card` from HACS before proceeding.
3. Discover the user's exact entity prefix by listing entities matching `monsieur_cuisine` or `toque` in Home Assistant:
   - Common patterns: `monsieur_cuisine_connect_` (no area prefix) or `<area>_monsieur_cuisine_connect_` (e.g., `my_area_monsieur_cuisine_connect_`).
   - Verify all **26 enabled entities** exist under that prefix (`15` sensors, `7` binary sensors, `3` buttons, `1` event; `turbo` is disabled by default and not required).

## 2. Back Up Before Modifying Live Files

Before copying or editing any dashboard YAML on Home Assistant:
- Create a dated backup copy of the target dashboard YAML (for example, `dashboard.yaml.bak` or in a dated backup folder).
- Preserve all existing views, cards, automations, and helper entities.

## 3. Deploy Static SVG Assets

Copy both files from `www/toque/` to Home Assistant's static web folder (`/config/www/toque/`):
- `www/toque/monsieur-cuisine-connect-frame.svg` → `/config/www/toque/monsieur-cuisine-connect-frame.svg`
- `www/toque/touch-target.svg` → `/config/www/toque/touch-target.svg`

Home Assistant serves `/config/www/toque/...` at `/local/toque/...`. If the user stores assets under a custom subfolder (e.g., `/local/custom-cards/toque`), pass `--asset-base /local/custom-cards/toque` when generating the YAML.

## 4. Generate & Validate the Card YAML

Run the included generator for the user's exact entity prefix and preferred language (`en` or `fr`):

```bash
python tools/generate_card.py --prefix <detected_prefix> --lang en --out generated-toque-card.yaml
python tools/validate_card.py generated-toque-card.yaml
```

- Confirm `validate_card.py` exits with code `0` and verifies all 26 entities and SVG XML outputs before deploying.
- Note: Home Assistant's `time_remaining` entity may report `unit_of_measurement: min` or `s`; the generated JS template handles both automatically and falls back to `estimated_end` when running.
- Note: On the Monsieur Cuisine Connect, `temperature` is `unknown` below `37 °C`. The card intentionally displays `<37°` when `base_link` is `ready` rather than fabricating `0 °C`.

## 5. Recommended Dashboard Placement

- **Sections view (`type: sections`, `max_columns: 3`)**: Wrap the card inside a **2-column grid section** (`column_span: 2`) so the `1024×600` Toque interface and bottom-right `Pause` / `Stop` / `Tare` buttons stay large, crisp, and touch-friendly on both desktop monitors and wall-mounted tablets.
- **Masonry / Panel views**: Works directly as a standalone card (`picture-elements` maintains its `1200:920` aspect ratio automatically).
- **Optional theme background**: If the user's theme makes `picture-elements` transparent or sharp-cornered, you may optionally add `card_mod: { style: 'ha-card { background: var(--ha-card-background); overflow: hidden; }' }` if `card-mod` is installed.

## 6. Live Verification & Safety Rules

- After deploying the YAML, ask Home Assistant (or refresh the Lovelace dashboard) to reload and perform a hard browser refresh (`Ctrl+Shift+R`) so cached SVGs do not interfere.
- Verify in the browser (read-only) that:
  1. Both `/local/toque/monsieur-cuisine-connect-frame.svg` and `/local/toque/touch-target.svg` return HTTP `200`.
  2. The dark Toque screen sits cleanly inside the vector bezel with zero clipping or spillover.
  3. Live idle telemetry appears (`Ready`/`Prêt`, `<37 °C`, `Base ready`/`Base prête`, `Scale: 0 g`, `Pause`/`Stop` dimmed when `unavailable`, `Tare` active when available).
- **Safety**: Do **NOT** press `button.<prefix>pause`, `button.<prefix>stop`, or `button.<prefix>tare_scale` during automated verification unless the user explicitly asks you to test a live button press. Never invent remote start, temperature, or speed-control services that `toque_companion` intentionally omits for safety.

## 7. Customization Tips

- **Language / Labels**: Edit the `I18N` dictionary in `tools/generate_card.py` and re-run `generate_card.py` + `validate_card.py`.
- **Colors**: Screen tokens are defined inline in `build_screen_js()` inside `tools/generate_card.py` (`#16294A` / `#0D1A31` / `#070E1B` background gradient, `#131D2E` cards, `#FF8A3D` accent, `#5CC8FF` cool/motor, `#3DDC97` ready, `#FFC14D` warning, `#FF5A5F` fault).
- **Custom Hardware Frame**: If replacing `www/toque/monsieur-cuisine-connect-frame.svg` with another frame (e.g., for Monsieur Cuisine Smart), update `SCREEN_RECT` (`left`, `top`, `width`, `height` in `%`) in `tools/generate_card.py` to match the new screen cutout and re-generate.
