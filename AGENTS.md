# Agent Handoff Notes

This file is for future coding agents or developers taking over Nano Earth.

## Project Goal

Build a local browser viewer for ERA5-like NetCDF weather files. The user wants an interaction style similar to earth.nullschool.net: full-screen earth visualization, variable switching, time playback, wind animation, and support for files that may contain multiple variables and multiple layers.

Do not copy protected site assets or directly mirror earth.nullschool.net. The current implementation is independent and uses only the general interaction pattern.

## Current Implementation

The project is a static web app plus a Python preprocessing script:

- `scripts/preprocess_nc.py`
  - Opens NetCDF with xarray.
  - Finds data variables containing `time`, `latitude`, and `longitude`.
  - Exports each variable/time/layer slice as little-endian `Float32Array` binary.
  - Writes `public/data/manifest.json`.
  - Supports extra dimensions by turning them into selectable layers.
- `public/index.html`
  - Defines the Canvas layers and UI controls.
- `public/styles.css`
  - Defines the dark HUD, layout, responsive behavior, and controls.
- `public/app.js`
  - Loads the manifest and field binaries.
  - Renders a globe or plate projection with Canvas 2D.
  - Draws color fields, graticules, TopoJSON land outlines, mouse readouts, six-week timeline controls, and animated wind particles.
  - Uses surface wind for surface variables and matched pressure-level wind for upper-air variables when vector pairs are present in the manifest.
- `public/data`
  - Generated browser assets.
- `docs/assets`
  - README artwork and preview screenshots.

The original `.nc` file is around 2GB. Browsers should not load it directly.
The raw `.nc` file is ignored by `.gitignore`; do not attempt to commit it to GitHub.

## Start The App

Use a static HTTP server:

```powershell
python -m http.server 8000 -d public
```

Open:

```text
http://localhost:8000
```

If port 8000 is already in use, use 8001 or another free port.

## Regenerate Data

Run:

```powershell
python scripts/preprocess_nc.py canglong_allvars_2026-04-30_2026-06-10.nc --out public/data
```

Optional resolution controls:

```powershell
python scripts/preprocess_nc.py canglong_allvars_2026-04-30_2026-06-10.nc --out public/data --lat-step 2 --lon-step 2
```

Lower step values produce larger and slower browser data.

## Data Contract

`manifest.json` is the contract between Python and the browser. Each variable entry should have:

- `id`: original NetCDF variable name
- `slug`: folder-safe variable name
- `label`: display name
- `family`: palette family
- `domain`: `surface` or `upper`
- `shape`: `[latCount, lonCount]`
- `layers`: layer list
- `stats`: global-ish display stats

Each layer should have:

- `index`
- `label`
- `selection`
- `files`
- `stats`

Each file should have:

- `time`
- `path`
- `stats`

Binary files are flat `Float32Array` grids in row-major order:

```text
index = latitudeIndex * longitudeCount + longitudeIndex
```

Latitude is ordered north to south. Longitude is 0 to 360.

## How To Add Variables

Most variables are discovered automatically if they include:

```text
time, latitude, longitude
```

For better labels and palettes, update `VARIABLE_LABELS` in `scripts/preprocess_nc.py`.

Example:

```python
"2m_temperature": ("2m temperature", "temperature")
```

Available palette families are currently:

```text
temperature, rain, pressure, wind, cloud, ice, flux, soil, radiation, scalar
```

Add new palette families in `public/app.js` under `palettes`.

The current all-variable Canglong dataset includes 26 surface variables and 10 upper-air variables. Upper-air variables have five pressure layers:

```text
200 hPa, 300 hPa, 500 hPa, 700 hPa, 850 hPa
```

## How To Add Features

Use these entry points:

- New UI control: edit `public/index.html`, bind it in `public/app.js`, style it in `public/styles.css`.
- New unit formatting: edit `formatValue()` in `public/app.js`.
- New color ramps: edit `palettes` and `colorFor()` in `public/app.js`.
- New projection: add logic to `project()` and `invert()` in `public/app.js`.
- New vector animation: generalize the wind-field loading currently tied to `10m_u_component_of_wind` and `10m_v_component_of_wind`.
- Higher coastline detail: replace `public/data/land-110m.json` with a compatible TopoJSON file and keep the same `objects.land` expectation or update `drawLand()`.

## Verification

Run syntax checks:

```powershell
python -m py_compile scripts/preprocess_nc.py
node --check public/app.js
```

Run the server and verify key files return 200:

```powershell
Invoke-WebRequest -Uri http://localhost:8000/ -UseBasicParsing
Invoke-WebRequest -Uri http://localhost:8000/data/manifest.json -UseBasicParsing
```

For visual verification, use Playwright screenshot:

```powershell
npx --yes playwright screenshot --wait-for-timeout=3000 http://localhost:8000/ .\nano-earth-screenshot.png
```

Check that the screenshot shows:

- A full-screen globe or plate map
- Variable HUD
- Time controls
- Color legend
- Coastlines and graticules
- Nonblank field colors

## Important Constraints

- Keep generated field data out of hand-written logic.
- Do not make the browser parse raw NetCDF directly.
- Do not commit raw NetCDF/GRIB files. Keep large data external or publish it separately.
- Avoid adding a heavy build system unless the user asks for larger frontend architecture.
- Preserve the static-site workflow unless there is a clear reason to introduce a backend.
- Be careful with the large `.nc` file; do not duplicate it.
