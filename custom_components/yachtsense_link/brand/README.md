# YachtSense Link brand assets

Source art for the **YachtSense Link** integration icon.

- `icon.svg` — the source of truth (square app mark). Edit this and re-render.
- `icon.png` — 256×256 raster rendered from `icon.svg`
  (`cairosvg icon.svg -o icon.png -W 256 -H 256`).

## How this icon is used

This folder is a real runtime asset, not just source art. Home Assistant's
`brands` component serves a custom integration's icon from its **local `brand/`
directory first**, and only falls back to the central
[`home-assistant/brands`](https://github.com/home-assistant/brands) CDN if no
local file is found (`BrandsIntegrationView._serve_from_custom_integration` in
HA core reads `<integration>/brand/icon.png`). HACS validation mirrors this: its
"Check brands" step passes as long as the integration has a `brand/` directory
containing at least `icon.png`, otherwise it checks the domain in the
`home-assistant/brands` repo.

So shipping `icon.png` here is sufficient for HA to display the icon and for
HACS validation to pass — no PR to `home-assistant/brands` is required. HA's
brand server also fills in the higher-resolution and dark variants from
`icon.png` when the specific file is absent (`icon@2x.png`, `dark_icon.png`,
`logo.png`, …), so a single `icon.png` covers every request.
