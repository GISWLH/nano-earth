# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Nano Earth is a local weather-field viewer for ERA5-like NetCDF datasets. The repository has two main parts:

- A Python preprocessing script that converts large NetCDF files into browser-friendly binary grids plus a manifest.
- A no-build static frontend that loads the manifest and selected grids, then renders the field in Canvas 2D.

Keep the current static-site workflow unless the user explicitly asks for a heavier frontend or backend architecture.

## Common Commands

### Run the app

Serve `public/` as a static site:

```bash
python -m http.server 8000 -d public
```

Open `http://localhost:8000`.

If port 8000 is busy:

```bash
python -m http.server 8001 -d public
```

### Regenerate browser data from NetCDF

Default downsampling:

```bash
python scripts/preprocess_nc.py canglong_allvars_2026-04-30_2026-06-10.nc --out public/data
```

Finer grid:

```bash
python scripts/preprocess_nc.py canglong_allvars_2026-04-30_2026-06-10.nc --out public/data --lat-step 2 --lon-step 2
```

The preprocessing script expects a local NetCDF file and writes generated assets under `public/data/`.

### Validation / checks

Python syntax check:

```bash
python -m py_compile scripts/preprocess_nc.py
```

JavaScript syntax check:

```bash
node --check public/app.js
```

Basic static-server verification after starting the app:

```bash
curl http://localhost:8000/
curl http://localhost:8000/data/manifest.json
```

Optional visual smoke test with Playwright:

```bash
npx --yes playwright screenshot --wait-for-timeout=3000 http://localhost:8000/ ./nano-earth-screenshot.png
```

## Architecture

### Data pipeline

The core contract is:

```text
NetCDF file
  -> scripts/preprocess_nc.py
  -> public/data/manifest.json
  -> public/data/fields/<variable>/lXX_tXX.bin
  -> public/app.js
  -> Canvas renderer
```

`scripts/preprocess_nc.py`:

- Opens the dataset with `xarray` using `decode_times=False`.
- Detects candidate variables by requiring `time`, `latitude`, and `longitude` dimensions.
- Treats extra dimensions, especially `level`, as selectable layers in the frontend.
- Downsamples latitude/longitude using `--lat-step` and `--lon-step`.
- Exports each `(variable, layer, time)` slice as a little-endian `Float32Array` binary file.
- Computes per-slice and merged statistics used by the frontend for color scaling.
- Writes `manifest.json`, including dataset metadata, time windows, variable descriptors, layer descriptors, and vector-pair metadata.

Important preprocessing details:

- `manifest.json` is the browser/backend contract. If you change manifest shape, update the frontend together.
- Variable labels and palette families are assigned in `VARIABLE_LABELS` inside `scripts/preprocess_nc.py`.
- Upper-air detection is currently driven by the presence of a `level` dimension.
- Binary grids are row-major `Float32Array` data indexed as `latIndex * lonCount + lonIndex`.
- Latitude is north-to-south; longitude is treated as 0..360 in the generated grids.

### Frontend runtime

The frontend is a single no-build app split across:

- `public/index.html`: canvas layers and HUD controls.
- `public/styles.css`: dark full-screen viewer styling and layout.
- `public/app.js`: all runtime logic.

`public/app.js` handles five main concerns:

1. Manifest-driven UI setup
   - Loads `data/manifest.json` at startup.
   - Builds grouped variable options for surface vs upper-air fields.
   - Builds layer selectors and the six-week timeline from manifest data.

2. Grid loading and caching
   - Fetches one selected `.bin` field at a time.
   - Caches loaded grids in memory with `state.cache` keyed by variable/layer/time.
   - Uses `setField()` as the central state transition for variable, layer, and time changes.

3. Scalar-field rendering
   - Converts sampled grid values into colors using palette families and percentile stats from the manifest.
   - Supports both globe and plate projections.
   - Renders the field into an offscreen canvas, then composites to the visible canvas.

4. Map overlays and interaction
   - Draws graticules and TopoJSON coastlines from `public/data/land-110m.json`.
   - Supports drag rotation, wheel zoom, mouse readout, opacity changes, and projection toggle.

5. Wind/vector animation
   - Uses manifest `vectorPairs` to find the correct U/V variables.
   - Surface fields use the 10m wind pair.
   - Upper-air fields use matched `upper_u_component_of_wind` / `upper_v_component_of_wind` for the selected pressure layer.
   - Particle animation is independent from scalar rendering and runs on a separate canvas.

## Important Extension Points

When changing behavior, these are the main places to look:

- Add or rename variable labels/palette families: `scripts/preprocess_nc.py` (`VARIABLE_LABELS`)
- Change manifest schema or exported metadata: `scripts/preprocess_nc.py`
- Change unit formatting: `public/app.js` (`formatValue()`)
- Change color ramps: `public/app.js` (`palettes`, `colorFor()`)
- Change projection behavior: `public/app.js` (`project()`, `invert()`)
- Change vector-pair behavior: `scripts/preprocess_nc.py` (`vectorPairs`) and `public/app.js` (`vectorPairFor()`, `loadVectorPair()`)
- Add UI controls: `public/index.html` + `public/app.js` + `public/styles.css`
- Change coastline data: replace `public/data/land-110m.json` with compatible TopoJSON or update `drawLand()` accordingly

## Repository-Specific Constraints

- Do not make the browser load raw NetCDF directly.
- Keep generated files under `public/data/` as generated artifacts, not hand-edited source.
- Do not commit raw NetCDF or GRIB files; `.gitignore` already excludes them.
- Be careful with the large local datasets in the repo root; avoid duplicating or moving them unnecessarily.
- Avoid introducing a build system unless the user asks for one; the current workflow intentionally has no frontend build step.
- Do not copy protected assets or directly mirror earth.nullschool.net; keep implementations original.

## Current Repo Reality

- There is no existing Python package config, Node package manifest, or committed automated test suite to rely on.
- The main verification path today is syntax checks plus running the local static server and visually validating the app.
- `tests/` exists but is currently empty in the checked-in repo state.
