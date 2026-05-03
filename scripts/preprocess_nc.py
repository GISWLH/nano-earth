from __future__ import annotations

import argparse
import itertools
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr


SKIP_VARIABLES = {"data"}

VARIABLE_LABELS = {
    "mean_top_net_short_wave_radiation_flux": ("Top net short-wave flux", "radiation"),
    "mean_top_net_long_wave_radiation_flux": ("Top net long-wave flux", "radiation"),
    "large_scale_rain_rate": ("Large-scale rain", "rain"),
    "convective_rain_rate": ("Convective rain", "rain"),
    "boundary_layer_height": ("Boundary layer height", "height"),
    "total_column_cloud_ice_water": ("Cloud ice water", "cloud"),
    "total_cloud_cover": ("Total cloud cover", "cloud"),
    "top_net_solar_radiation_clear_sky": ("Top solar radiation", "radiation"),
    "10m_u_component_of_wind": ("10m wind U", "wind"),
    "10m_v_component_of_wind": ("10m wind V", "wind"),
    "2m_dewpoint_temperature": ("2m dew point", "temperature"),
    "2m_temperature": ("2m temperature", "temperature"),
    "mean_eastward_turbulent_surface_stress": ("Eastward surface stress", "wind"),
    "mean_northward_turbulent_surface_stress": ("Northward surface stress", "wind"),
    "surface_latent_heat_flux": ("Latent heat flux", "flux"),
    "surface_sensible_heat_flux": ("Sensible heat flux", "flux"),
    "mean_surface_net_short_wave_radiation_flux": ("Surface short-wave flux", "radiation"),
    "mean_surface_net_long_wave_radiation_flux": ("Surface long-wave flux", "radiation"),
    "surface_net_solar_radiation": ("Surface solar radiation", "radiation"),
    "surface_net_thermal_radiation": ("Surface thermal radiation", "radiation"),
    "surface_pressure": ("Surface pressure", "pressure"),
    "volumetric_soil_water_layer": ("Soil water", "soil"),
    "volumetric_soil_water": ("Soil water", "soil"),
    "mean_sea_level_pressure": ("Mean sea-level pressure", "pressure"),
    "sea_ice_cover": ("Sea ice cover", "ice"),
    "sea_surface_temperature": ("Sea surface temperature", "temperature"),
    "total_precipitation": ("Total precipitation", "rain"),
    "runoff": ("Runoff", "rain"),
    "soil_temperature": ("Soil temperature", "temperature"),
    "upper_ozone_mass_mixing_ratio": ("Ozone mixing ratio", "ozone"),
    "upper_geopotential": ("Geopotential", "height"),
    "upper_temperature": ("Upper-air temperature", "temperature"),
    "upper_u_component_of_wind": ("Upper-air wind U", "wind"),
    "upper_v_component_of_wind": ("Upper-air wind V", "wind"),
    "upper_vertical_velocity": ("Vertical velocity", "velocity"),
    "upper_specific_humidity": ("Specific humidity", "humidity"),
    "upper_fraction_of_cloud_cover": ("Upper-air cloud cover", "cloud"),
    "upper_specific_cloud_ice_water_content": ("Cloud ice content", "ice"),
    "upper_specific_cloud_liquid_water_content": ("Cloud liquid content", "cloud"),
}


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "-", value)
    return value.strip("-")


def parse_time_values(ds: xr.Dataset) -> list[dict[str, str | int | float]]:
    time = ds["time"]
    values = time.values.tolist()
    units = str(time.attrs.get("units", ""))
    base = None
    if "since" in units:
        _, raw_base = units.split("since", 1)
        raw_base = raw_base.strip().replace("Z", "")
        for fmt, length in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
            try:
                base = datetime.strptime(raw_base[:length], fmt)
                break
            except ValueError:
                continue

    result = []
    week_starts = ds["week_start"].values.tolist() if "week_start" in ds.coords else []
    week_ends = ds["week_end"].values.tolist() if "week_end" in ds.coords else []

    for index, value in enumerate(values):
        iso = str(value)
        if base is not None and isinstance(value, (int, float)):
            dt = base + timedelta(days=float(value))
            iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            label = dt.strftime("%Y-%m-%d")
        else:
            label = str(value)
        item: dict[str, str | int | float] = {
            "index": index,
            "value": value,
            "iso": iso,
            "label": label,
            "week": index + 1,
        }
        if index < len(week_starts):
            item["start"] = str(week_starts[index])
        if index < len(week_ends):
            item["end"] = str(week_ends[index])
            if "start" in item:
                item["label"] = f"{item['start']} to {item['end']}"
        result.append(item)
    return result


def finite_stats(arr: np.ndarray) -> dict[str, float | None]:
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {
            "min": None,
            "max": None,
            "p02": None,
            "p05": None,
            "p50": None,
            "p95": None,
            "p98": None,
        }
    qs = np.percentile(finite, [2, 5, 50, 95, 98])
    return {
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "p02": float(qs[0]),
        "p05": float(qs[1]),
        "p50": float(qs[2]),
        "p95": float(qs[3]),
        "p98": float(qs[4]),
    }


def merge_stats(items: list[dict[str, float | None]]) -> dict[str, float | None]:
    keys = ("min", "max", "p02", "p05", "p50", "p95", "p98")
    merged: dict[str, float | None] = {}
    for key in keys:
        vals = [item[key] for item in items if item[key] is not None and math.isfinite(float(item[key]))]
        if not vals:
            merged[key] = None
        elif key == "min":
            merged[key] = float(min(vals))
        elif key == "max":
            merged[key] = float(max(vals))
        else:
            merged[key] = float(np.median(vals))
    return merged


def layer_specs(ds: xr.Dataset, da: xr.DataArray) -> list[dict[str, object]]:
    extra_dims = [dim for dim in da.dims if dim not in {"time", "latitude", "longitude"}]
    if not extra_dims:
        return [{"index": 0, "label": "surface", "selection": {}, "suffix": "surface"}]

    dim_indexes = [range(int(da.sizes[dim])) for dim in extra_dims]
    specs = []
    for layer_index, combo in enumerate(itertools.product(*dim_indexes)):
        selection = dict(zip(extra_dims, combo))
        labels = []
        suffix_parts = []
        for dim, idx in selection.items():
            if dim in ds.coords:
                raw = ds[dim].values[idx]
                value = raw.item() if hasattr(raw, "item") else raw
            else:
                value = idx
            if dim == "level":
                labels.append(f"{value} hPa")
            else:
                labels.append(f"{dim}={value}")
            suffix_parts.append(f"{slugify(dim)}-{slugify(str(value)) or idx}")
        specs.append(
            {
                "index": layer_index,
                "label": ", ".join(labels),
                "selection": selection,
                "suffix": "__".join(map(str, suffix_parts)),
            }
        )
    return specs


def vertical_domain(da: xr.DataArray) -> str:
    if "level" in da.dims:
        return "upper"
    return "surface"


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert ERA5-like NetCDF fields into web-ready grids.")
    parser.add_argument("nc_file", type=Path)
    parser.add_argument("--out", type=Path, default=Path("public/data"))
    parser.add_argument("--lat-step", type=int, default=4)
    parser.add_argument("--lon-step", type=int, default=4)
    args = parser.parse_args()

    if not args.nc_file.exists():
        raise FileNotFoundError(args.nc_file)

    out_dir = args.out
    field_dir = out_dir / "fields"
    field_dir.mkdir(parents=True, exist_ok=True)

    ds = xr.open_dataset(args.nc_file, decode_times=False)
    lat = ds["latitude"].isel(latitude=slice(0, None, args.lat_step)).values.astype("float32")
    lon = ds["longitude"].isel(longitude=slice(0, None, args.lon_step)).values.astype("float32")
    times = parse_time_values(ds)

    candidates = []
    for name, da in ds.data_vars.items():
        if name in SKIP_VARIABLES:
            continue
        if {"time", "latitude", "longitude"}.issubset(set(da.dims)):
            candidates.append(name)

    variables = []
    for name in candidates:
        label, family = VARIABLE_LABELS.get(name, (name.replace("_", " ").title(), "scalar"))
        slug = slugify(name)
        var_dir = field_dir / slug
        var_dir.mkdir(parents=True, exist_ok=True)
        layers = []
        all_stats = []

        for spec in layer_specs(ds, ds[name]):
            files = []
            stats_by_time = []
            layer_selection = {dim: int(idx) for dim, idx in dict(spec["selection"]).items()}

            for time_info in times:
                time_index = int(time_info["index"])
                arr = (
                    ds[name]
                    .isel(
                        {
                            "time": time_index,
                            "latitude": slice(0, None, args.lat_step),
                            "longitude": slice(0, None, args.lon_step),
                            **layer_selection,
                        }
                    )
                    .values.astype("<f4", copy=False)
                )
                filename = f"l{int(spec['index']):02d}_t{time_index:02d}.bin"
                relative = f"data/fields/{slug}/{filename}"
                arr.tofile(var_dir / filename)
                stats = finite_stats(arr)
                stats_by_time.append(stats)
                all_stats.append(stats)
                files.append({"time": time_index, "path": relative, "stats": stats})
                print(f"wrote {relative} {arr.shape}")

            layers.append(
                {
                    "index": int(spec["index"]),
                    "label": str(spec["label"]),
                    "selection": layer_selection,
                    "files": files,
                    "stats": merge_stats(stats_by_time),
                }
            )

        variables.append(
            {
                "id": name,
                "slug": slug,
                "label": label,
                "family": family,
                "domain": vertical_domain(ds[name]),
                "shape": [int(lat.size), int(lon.size)],
                "layers": layers,
                "stats": merge_stats(all_stats),
            }
        )

    manifest = {
        "title": "Nano Earth",
        "source": args.nc_file.name,
        "generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attributes": {key: str(value) for key, value in ds.attrs.items()},
        "dimensions": {
            "latitude": int(lat.size),
            "longitude": int(lon.size),
            "time": len(times),
            "latStep": args.lat_step,
            "lonStep": args.lon_step,
        },
        "coordinates": {
            "latitudeStart": float(lat[0]),
            "latitudeEnd": float(lat[-1]),
            "longitudeStart": float(lon[0]),
            "longitudeEnd": float(lon[-1]),
        },
        "times": times,
        "vectorPairs": [
            {
                "id": "surface_wind",
                "label": "10m wind",
                "domain": "surface",
                "u": "10m_u_component_of_wind",
                "v": "10m_v_component_of_wind",
                "layerMode": "surface",
            },
            {
                "id": "upper_wind",
                "label": "Upper-air wind",
                "domain": "upper",
                "u": "upper_u_component_of_wind",
                "v": "upper_v_component_of_wind",
                "layerMode": "matched",
            },
        ],
        "variables": variables,
    }

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
