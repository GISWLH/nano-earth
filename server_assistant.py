from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib import error, request

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "public" / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
LOCAL_CONFIG_PATH = ROOT / "server_assistant.local.json"
HOST = os.getenv("ASSISTANT_HOST", "127.0.0.1")
PORT = int(os.getenv("ASSISTANT_PORT", "8765"))


_DATASET: xr.Dataset | None = None
_DATASET_PATH: Path | None = None


def load_local_config() -> dict[str, Any]:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))


LOCAL_CONFIG = load_local_config()
DEEPSEEK_BASE_URL = str(LOCAL_CONFIG.get("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/anthropic")
DEEPSEEK_MODEL = str(LOCAL_CONFIG.get("DEEPSEEK_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-pro")
DEEPSEEK_API_KEY = str(LOCAL_CONFIG.get("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "")

PHASE_LABELS = {
    "reading_data": "正在读取数据",
    "processing_analysis": "正在处理分析",
    "generating_report": "正在生成报告",
}

REGIONS = {
    "china": {"label": "China", "lat": (18, 54), "lon": (73, 135), "aliases": ["china", "中国", "我国", "中国大陆"]},
    "global": {"label": "Global", "lat": (-90, 90), "lon": (-180, 180), "aliases": ["global", "world", "全球", "全世界"]},
    "europe": {"label": "Europe", "lat": (35, 72), "lon": (-12, 40), "aliases": ["europe", "european", "欧洲", "欧陆"]},
    "east_asia": {"label": "East Asia", "lat": (20, 55), "lon": (100, 145), "aliases": ["east asia", "东亚", "japan", "korea", "日本", "韩国"]},
    "south_asia": {"label": "South Asia", "lat": (5, 35), "lon": (65, 95), "aliases": ["south asia", "南亚", "india", "印度"]},
    "north_america": {"label": "North America", "lat": (15, 72), "lon": (-168, -52), "aliases": ["north america", "北美", "usa", "united states", "canada", "美国", "加拿大"]},
    "arctic": {"label": "Arctic", "lat": (66, 90), "lon": (-180, 180), "aliases": ["arctic", "北极"]},
}

VARIABLE_HINTS = [
    {
        "kind": "temperature",
        "variable_id": "2m_temperature",
        "aliases": ["temperature", "temp", "heat", "hot", "warm", "高温", "热浪", "气温", "温度", "extreme heat"],
    },
    {
        "kind": "precipitation",
        "aliases": ["precipitation", "rain", "rainfall", "storm", "wet", "降水", "降雨", "暴雨", "雨", "强降水", "极端降水"],
    },
    {
        "kind": "pressure",
        "variable_id": "mean_sea_level_pressure",
        "aliases": ["pressure", "slp", "气压", "低压", "高压"],
    },
    {
        "kind": "wind",
        "aliases": ["wind", "gust", "风", "大风", "风速"],
    },
    {
        "kind": "cloud",
        "variable_id": "total_cloud_cover",
        "aliases": ["cloud", "cloud cover", "云", "云量"],
    },
]

CONTEXT_HINT_TOKENS = [
    "当前", "现在看的", "现在这张", "这个变量", "这个场", "这一层", "这周这个", "眼前", "目前这张",
    "current", "this field", "this layer", "this variable", "what am i looking at",
]


@dataclass
class ParsedQuestion:
    region_id: str
    region_label: str
    variable_id: str
    variable_label: str
    kind: str
    layer_index: int
    week_indices: list[int]
    anchor_week: int
    question: str
    resolution_source: str
    used_context_variable: bool


ProgressFn = Callable[[str, float], None]


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))



def source_nc_path(manifest: dict[str, Any]) -> Path:
    source = str(manifest.get("source") or "").strip()
    if not source:
        raise FileNotFoundError("manifest source is missing; cannot locate the NC file.")
    path = ROOT / source
    if not path.exists():
        raise FileNotFoundError(f"Source NC file not found: {path}")
    return path



def load_dataset(manifest: dict[str, Any]) -> xr.Dataset:
    global _DATASET, _DATASET_PATH
    path = source_nc_path(manifest)
    if _DATASET is not None and _DATASET_PATH == path:
        return _DATASET
    if _DATASET is not None:
        _DATASET.close()
    _DATASET = xr.open_dataset(path, decode_times=False)
    _DATASET_PATH = path
    return _DATASET



def variable_by_id(manifest: dict[str, Any], variable_id: str) -> dict[str, Any] | None:
    for variable in manifest["variables"]:
        if variable["id"] == variable_id:
            return variable
    return None



def available_variable_ids(manifest: dict[str, Any]) -> set[str]:
    return {variable["id"] for variable in manifest["variables"]}



def question_uses_context(question: str) -> bool:
    q = question.lower()
    return any(token in q for token in CONTEXT_HINT_TOKENS)



def detect_region(question: str) -> tuple[str, str]:
    q = question.lower()
    for region_id, region in REGIONS.items():
        if any(alias in q for alias in region["aliases"]):
            return region_id, region["label"]
    return "global", REGIONS["global"]["label"]



def resolve_precipitation_variable(manifest: dict[str, Any]) -> tuple[str, str, str]:
    available = available_variable_ids(manifest)
    if "total_precipitation" in available:
        variable = variable_by_id(manifest, "total_precipitation")
        return "total_precipitation", variable["label"], "precipitation"
    if "large_scale_rain_rate" in available and "convective_rain_rate" in available:
        return "__precipitation_signal__", "Precipitation signal", "precipitation"
    for variable_id in ["large_scale_rain_rate", "convective_rain_rate", "runoff"]:
        if variable_id in available:
            variable = variable_by_id(manifest, variable_id)
            return variable_id, variable["label"], "precipitation"
    default_id = "2m_temperature" if "2m_temperature" in available else manifest["variables"][0]["id"]
    variable = variable_by_id(manifest, default_id)
    return default_id, variable["label"], variable.get("family", "scalar")



def resolve_wind_variable(manifest: dict[str, Any]) -> tuple[str, str, str]:
    available = available_variable_ids(manifest)
    if {"10m_u_component_of_wind", "10m_v_component_of_wind"}.issubset(available):
        return "__wind_speed__", "10m wind speed", "wind"
    if "10m_u_component_of_wind" in available:
        variable = variable_by_id(manifest, "10m_u_component_of_wind")
        return variable["id"], variable["label"], "wind"
    default_id = "2m_temperature" if "2m_temperature" in available else manifest["variables"][0]["id"]
    variable = variable_by_id(manifest, default_id)
    return default_id, variable["label"], variable.get("family", "scalar")



def detect_variable(question: str, context: dict[str, Any], manifest: dict[str, Any]) -> tuple[str, str, str, str, bool]:
    q = question.lower()
    available = available_variable_ids(manifest)
    for hint in VARIABLE_HINTS:
        if not any(alias in q for alias in hint["aliases"]):
            continue
        if hint["kind"] == "precipitation":
            variable_id, variable_label, kind = resolve_precipitation_variable(manifest)
            return variable_id, variable_label, kind, "question", False
        if hint["kind"] == "wind":
            variable_id, variable_label, kind = resolve_wind_variable(manifest)
            return variable_id, variable_label, kind, "question", False
        variable_id = hint.get("variable_id")
        if variable_id in available:
            variable = variable_by_id(manifest, variable_id)
            return variable_id, variable["label"], hint["kind"], "question", False

    if question_uses_context(question):
        context_id = context.get("variableId")
        if context_id in available:
            variable = variable_by_id(manifest, context_id)
            return context_id, variable["label"], variable.get("family", "scalar"), "context", True

    default_id = "2m_temperature" if "2m_temperature" in available else manifest["variables"][0]["id"]
    variable = variable_by_id(manifest, default_id)
    return default_id, variable["label"], variable.get("family", "scalar"), "default", False



def parse_week_indices(question: str, context: dict[str, Any], manifest: dict[str, Any]) -> tuple[list[int], int]:
    q = question.lower()
    total = len(manifest["times"])
    anchor = int(context.get("timeIndex") or 0)
    anchor = max(0, min(anchor, total - 1))

    range_match = re.search(r"(?:第|w|week\s*)(\d+)\s*(?:到|至|-|to)\s*(?:第|w|week\s*)(\d+)", q)
    if range_match:
        start = max(1, int(range_match.group(1))) - 1
        end = min(total, int(range_match.group(2))) - 1
        if end < start:
            start, end = end, start
        return list(range(start, end + 1)), anchor

    explicit_week = re.search(r"(?:第|w|week\s*)(\d+)\s*周?", q)
    if explicit_week:
        index = max(1, min(total, int(explicit_week.group(1)))) - 1
        return [index], anchor

    future_match = re.search(r"(?:未来|接下来|后续|next|upcoming)\s*(\d+)\s*(?:周|weeks?)", q)
    if future_match:
        count = max(1, int(future_match.group(1)))
        end = min(total, anchor + count)
        return list(range(anchor, end)), anchor

    if any(token in q for token in ["未来", "接下来", "next", "upcoming"]):
        end = min(total, anchor + 3)
        return list(range(anchor, end)), anchor

    return [anchor], anchor



def parse_question(question: str, context: dict[str, Any], manifest: dict[str, Any]) -> ParsedQuestion:
    region_id, region_label = detect_region(question)
    variable_id, variable_label, kind, resolution_source, used_context_variable = detect_variable(question, context, manifest)
    week_indices, anchor_week = parse_week_indices(question, context, manifest)
    layer_index = int(context.get("layerIndex") or 0)
    variable = variable_by_id(manifest, variable_id) if not variable_id.startswith("__") else None
    if variable is not None:
        max_layer = len(variable.get("layers") or []) - 1
        layer_index = max(0, min(layer_index, max_layer))
    else:
        layer_index = 0
    return ParsedQuestion(
        region_id=region_id,
        region_label=region_label,
        variable_id=variable_id,
        variable_label=variable_label,
        kind=kind,
        layer_index=layer_index,
        week_indices=week_indices,
        anchor_week=anchor_week,
        question=question,
        resolution_source=resolution_source,
        used_context_variable=used_context_variable,
    )



def coordinate_arrays(ds: xr.Dataset) -> tuple[np.ndarray, np.ndarray]:
    lat = ds["latitude"].values.astype(np.float32)
    lon = ds["longitude"].values.astype(np.float32)
    lon = ((lon + 180.0) % 360.0) - 180.0
    return lat, lon



def region_mask(lat: np.ndarray, lon: np.ndarray, region_id: str) -> np.ndarray:
    region = REGIONS[region_id]
    lat_min, lat_max = region["lat"]
    lon_min, lon_max = region["lon"]
    lat_ok = (lat >= lat_min) & (lat <= lat_max)
    lon_ok = (lon >= lon_min) & (lon <= lon_max)
    return lat_ok[:, None] & lon_ok[None, :]



def layer_selection(variable: dict[str, Any], layer_index: int) -> dict[str, int]:
    layers = variable.get("layers") or []
    if not layers:
        return {}
    index = max(0, min(layer_index, len(layers) - 1))
    return {key: int(value) for key, value in (layers[index].get("selection") or {}).items()}



def load_runtime_grid(ds: xr.Dataset, variable: dict[str, Any], layer_index: int, time_index: int) -> np.ndarray:
    name = variable["id"]
    if name not in ds.data_vars:
        raise KeyError(f"Variable {name} is not available in the source NC file.")
    da = ds[name]
    indexers: dict[str, int] = {"time": int(time_index)}
    for dim, idx in layer_selection(variable, layer_index).items():
        if dim in da.dims:
            indexers[dim] = int(idx)
    arr = da.isel(indexers).values.astype(np.float32, copy=False)
    return np.asarray(arr, dtype=np.float32)



def load_analysis_grid(ds: xr.Dataset, manifest: dict[str, Any], parsed: ParsedQuestion, time_index: int) -> np.ndarray:
    if parsed.variable_id == "__precipitation_signal__":
        parts = []
        for variable_id in ["large_scale_rain_rate", "convective_rain_rate"]:
            variable = variable_by_id(manifest, variable_id)
            if variable is not None:
                parts.append(load_runtime_grid(ds, variable, 0, time_index))
        if not parts:
            raise KeyError("No precipitation variables are available for composite analysis.")
        return np.sum(parts, axis=0, dtype=np.float32)

    variable = variable_by_id(manifest, parsed.variable_id)
    if variable is None:
        raise KeyError(f"Variable {parsed.variable_id} could not be resolved.")
    return load_runtime_grid(ds, variable, parsed.layer_index, time_index)



def to_display_values(variable_id: str, values: np.ndarray) -> tuple[np.ndarray, str]:
    if variable_id in {"__wind_speed__"}:
        return values, "m/s"
    if variable_id in {"__precipitation_signal__"}:
        return values, "signal"
    if "temperature" in variable_id or "dewpoint" in variable_id:
        return values - 273.15 if np.nanmean(values) > 150 else values, "C"
    if "pressure" in variable_id and np.nanmean(values) > 20000:
        return values / 100.0, "hPa"
    if "wind" in variable_id:
        return values, "m/s"
    if "precip" in variable_id or variable_id.endswith("rain_rate") or "runoff" in variable_id:
        return values, "signal"
    if "cloud" in variable_id or "ice_cover" in variable_id:
        return values * 100.0, "%"
    return values, "raw units"



def hotspot_list(values: np.ndarray, mask: np.ndarray, lat: np.ndarray, lon: np.ndarray, limit: int = 3) -> list[dict[str, float]]:
    flat_mask = mask.reshape(-1)
    flat_values = values.reshape(-1)
    region_indices = np.flatnonzero(flat_mask & np.isfinite(flat_values))
    if region_indices.size == 0:
        return []
    region_values = flat_values[region_indices]
    take = min(limit, region_values.size)
    top_local = np.argpartition(region_values, -take)[-take:]
    top_local = top_local[np.argsort(region_values[top_local])[::-1]]
    result = []
    n_lon = values.shape[1]
    for local_idx in top_local:
        flat_index = int(region_indices[int(local_idx)])
        y, x = divmod(flat_index, n_lon)
        result.append({
            "lat": float(lat[y]),
            "lon": float(lon[x]),
            "value": float(flat_values[flat_index]),
        })
    return result



def analyze_scalar_question(manifest: dict[str, Any], ds: xr.Dataset, parsed: ParsedQuestion, progress: ProgressFn | None = None) -> dict[str, Any]:
    lat, lon = coordinate_arrays(ds)
    mask = region_mask(lat, lon, parsed.region_id)
    weeks = []
    total_weeks = max(1, len(parsed.week_indices))

    for idx, week_index in enumerate(parsed.week_indices):
        if progress is not None:
            progress(f"正在读取第 {week_index + 1} 周并计算区域统计…", 0.18 + 0.72 * (idx / total_weeks))
        grid = load_analysis_grid(ds, manifest, parsed, week_index)
        display_grid, unit = to_display_values(parsed.variable_id, grid)
        region_values = display_grid[mask]
        finite = region_values[np.isfinite(region_values)]
        if finite.size == 0:
            continue
        week = manifest["times"][week_index]
        item: dict[str, Any] = {
            "timeIndex": week_index,
            "week": int(week.get("week", week_index + 1)),
            "label": week.get("label") or f"Week {week_index + 1}",
            "start": week.get("start"),
            "end": week.get("end"),
            "mean": float(np.mean(finite)),
            "min": float(np.min(finite)),
            "p90": float(np.percentile(finite, 90)),
            "p95": float(np.percentile(finite, 95)),
            "max": float(np.max(finite)),
            "unit": unit,
            "hotspots": hotspot_list(display_grid, mask, lat, lon),
        }
        if parsed.kind == "temperature":
            item["areaAbove35"] = float(np.mean(finite >= 35.0) * 100.0)
            item["areaAbove38"] = float(np.mean(finite >= 38.0) * 100.0)
            item["areaAbove40"] = float(np.mean(finite >= 40.0) * 100.0)
        elif parsed.kind == "precipitation":
            threshold = float(np.percentile(finite, 95))
            item["areaAboveRegionalP95"] = float(np.mean(finite >= threshold) * 100.0)
        weeks.append(item)

    if progress is not None:
        progress("正在汇总热点与周次排序…", 0.95)

    if not weeks:
        raise ValueError("No valid regional data was found for this request.")

    if parsed.kind == "temperature":
        ranked = sorted(weeks, key=lambda item: (item["areaAbove35"], item["max"]), reverse=True)
    elif parsed.kind == "precipitation":
        ranked = sorted(weeks, key=lambda item: (item.get("areaAboveRegionalP95", 0.0), item["max"]), reverse=True)
    else:
        ranked = sorted(weeks, key=lambda item: item["max"], reverse=True)

    suggestions = [
        {
            "label": f"{parsed.variable_label} / W{item['week']} / {item['label']}",
            "variableId": "large_scale_rain_rate" if parsed.variable_id == "__precipitation_signal__" else parsed.variable_id,
            "timeIndex": item["timeIndex"],
            "layerIndex": parsed.layer_index,
            "variableLabel": parsed.variable_label,
        }
        for item in ranked[:3]
    ]

    return {
        "parsed": {
            "question": parsed.question,
            "region": parsed.region_label,
            "variableId": parsed.variable_id,
            "variableLabel": parsed.variable_label,
            "kind": parsed.kind,
            "layerIndex": parsed.layer_index,
            "weeks": parsed.week_indices,
            "resolutionSource": parsed.resolution_source,
            "usedContextVariable": parsed.used_context_variable,
        },
        "weeks": weeks,
        "topWeeks": ranked[:3],
        "suggestions": suggestions,
    }



def analyze_wind_question(manifest: dict[str, Any], ds: xr.Dataset, parsed: ParsedQuestion, progress: ProgressFn | None = None) -> dict[str, Any]:
    lat, lon = coordinate_arrays(ds)
    mask = region_mask(lat, lon, parsed.region_id)
    u_var = variable_by_id(manifest, "10m_u_component_of_wind")
    v_var = variable_by_id(manifest, "10m_v_component_of_wind")
    if u_var is None or v_var is None:
        raise ValueError("Wind vector variables are not available in this dataset.")

    weeks = []
    total_weeks = max(1, len(parsed.week_indices))
    for idx, week_index in enumerate(parsed.week_indices):
        if progress is not None:
            progress(f"正在读取第 {week_index + 1} 周风场并计算风速…", 0.18 + 0.72 * (idx / total_weeks))
        u = load_runtime_grid(ds, u_var, 0, week_index)
        v = load_runtime_grid(ds, v_var, 0, week_index)
        speed = np.sqrt(np.square(u) + np.square(v))
        region_values = speed[mask]
        finite = region_values[np.isfinite(region_values)]
        if finite.size == 0:
            continue
        week = manifest["times"][week_index]
        weeks.append(
            {
                "timeIndex": week_index,
                "week": int(week.get("week", week_index + 1)),
                "label": week.get("label") or f"Week {week_index + 1}",
                "mean": float(np.mean(finite)),
                "p90": float(np.percentile(finite, 90)),
                "p95": float(np.percentile(finite, 95)),
                "max": float(np.max(finite)),
                "areaAbove17": float(np.mean(finite >= 17.0) * 100.0),
                "areaAbove25": float(np.mean(finite >= 25.0) * 100.0),
                "unit": "m/s",
                "hotspots": hotspot_list(speed, mask, lat, lon),
            }
        )

    if progress is not None:
        progress("正在汇总风速热点与周次排序…", 0.95)

    if not weeks:
        raise ValueError("No valid wind data was found for this request.")

    ranked = sorted(weeks, key=lambda item: (item["areaAbove17"], item["max"]), reverse=True)
    return {
        "parsed": {
            "question": parsed.question,
            "region": parsed.region_label,
            "variableId": "__wind_speed__",
            "variableLabel": "10m wind speed",
            "kind": "wind",
            "layerIndex": 0,
            "weeks": parsed.week_indices,
            "resolutionSource": parsed.resolution_source,
            "usedContextVariable": parsed.used_context_variable,
        },
        "weeks": weeks,
        "topWeeks": ranked[:3],
        "suggestions": [
            {
                "label": f"10m wind / W{item['week']} / {item['label']}",
                "variableId": "10m_u_component_of_wind",
                "timeIndex": item["timeIndex"],
                "layerIndex": 0,
                "variableLabel": "10m wind",
            }
            for item in ranked[:3]
        ],
    }



def analyze_question(manifest: dict[str, Any], ds: xr.Dataset, parsed: ParsedQuestion, progress: ProgressFn | None = None) -> dict[str, Any]:
    if parsed.kind == "wind":
        return analyze_wind_question(manifest, ds, parsed, progress)
    return analyze_scalar_question(manifest, ds, parsed, progress)



def build_summary(analysis: dict[str, Any]) -> str:
    parsed = analysis["parsed"]
    top = analysis["topWeeks"][0]
    if parsed["kind"] == "temperature":
        return (
            f"{parsed['region']} heat signal is strongest in W{top['week']} ({top['label']}), "
            f"with regional max {top['max']:.1f}{top['unit']} and {top['areaAbove35']:.1f}% of sampled cells at or above 35{top['unit']}."
        )
    if parsed["kind"] == "precipitation":
        return (
            f"{parsed['region']} precipitation signal is strongest in W{top['week']} ({top['label']}), "
            f"with regional max {top['max']:.2f} {top['unit']} and p95 {top['p95']:.2f} {top['unit']}."
        )
    if parsed["kind"] == "wind":
        return (
            f"{parsed['region']} wind signal is strongest in W{top['week']} ({top['label']}), "
            f"with regional max {top['max']:.1f}{top['unit']} and {top['areaAbove17']:.1f}% of sampled cells at or above 17 {top['unit']}."
        )
    return (
        f"{parsed['region']} {parsed['variableLabel']} is strongest in W{top['week']} ({top['label']}), "
        f"with regional max {top['max']:.2f} {top['unit']} and p95 {top['p95']:.2f} {top['unit']}."
    )



def build_fallback_report(analysis: dict[str, Any]) -> str:
    parsed = analysis["parsed"]
    lines = [
        f"# Conclusion",
        f"- Question: {parsed['question']}",
        f"- Region: {parsed['region']}",
        f"- Variable: {parsed['variableLabel']}",
        f"- Resolution source: {parsed.get('resolutionSource', 'question')}",
        "",
        "# Evidence",
    ]
    for item in analysis["weeks"]:
        base = f"- W{item['week']} ({item['label']}): mean {item['mean']:.2f} {item['unit']}, p95 {item['p95']:.2f} {item['unit']}, max {item['max']:.2f} {item['unit']}"
        if parsed["kind"] == "temperature":
            base += f", >=35C area {item['areaAbove35']:.1f}%, >=38C area {item['areaAbove38']:.1f}%"
        elif parsed["kind"] == "precipitation":
            base += f", area above regional p95 {item.get('areaAboveRegionalP95', 0.0):.1f}%"
        elif parsed["kind"] == "wind":
            base += f", >=17 m/s area {item['areaAbove17']:.1f}%"
        lines.append(base)
        hotspots = item.get("hotspots") or []
        if hotspots:
            peak = hotspots[0]
            lines.append(f"  - hotspot near {peak['lat']:.1f}, {peak['lon']:.1f} with {peak['value']:.2f} {item['unit']}")

    lines.extend(
        [
            "",
            "# Caveat",
            "- This report is grounded in the forecast dataset only. Extremes are interpreted from absolute thresholds or dataset-relative statistics, not from a historical climatology baseline.",
        ]
    )
    return "\n".join(lines)



def call_deepseek(question: str, analysis: dict[str, Any]) -> str:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    payload = {
        "model": DEEPSEEK_MODEL,
        "max_tokens": 1200,
        "temperature": 0.2,
        "system": (
            "You are a forecast-analysis assistant. Answer only from the supplied dataset evidence. "
            "Do not invent values. Mention specific week/date windows and state uncertainty or caveats clearly. "
            "If the user asks in Chinese, answer in Chinese. Return Markdown."
        ),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"User question:\n{question}\n\n"
                            f"Structured dataset evidence:\n{json.dumps(analysis, ensure_ascii=False)}\n\n"
                            "Write a concise Markdown report with: conclusion, supporting evidence, and caveats."
                        ),
                    }
                ],
            }
        ],
    }

    endpoint = DEEPSEEK_BASE_URL.rstrip("/") + "/v1/messages"
    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": DEEPSEEK_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API request failed: {exc.code} {detail[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"DeepSeek API network error: {exc.reason}") from exc

    content = body.get("content") or []
    text = "\n".join(block.get("text", "") for block in content if block.get("type") == "text").strip()
    if not text:
        raise RuntimeError("DeepSeek API returned no text content.")
    return text


class AssistantHandler(BaseHTTPRequestHandler):
    server_version = "NanoEarthAssistant/0.2"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/api/forecast-assistant":
            self.send_error(404, "Not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self.send_error(400, "Missing request body")
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            question = str(payload.get("question", "")).strip()
            context = payload.get("context") or {}
            if not question:
                raise ValueError("Question is required.")
        except Exception as exc:
            self.send_error(400, str(exc))
            return

        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()

        try:
            self.emit_phase("reading_data", "正在解析问题与读取数据源…", 0.12)
            manifest = load_manifest()
            time.sleep(0.12)
            ds = load_dataset(manifest)
            self.emit_phase("reading_data", "正在识别变量、区域和时间范围…", 0.42)
            parsed = parse_question(question, context, manifest)
            time.sleep(0.12)
            self.emit_phase("reading_data", f"已锁定 {parsed.variable_label} / {parsed.region_label}，正在准备数据切片…", 0.88)
            time.sleep(0.14)

            def on_progress(detail: str, progress: float) -> None:
                self.emit_phase("processing_analysis", detail, progress)

            self.emit_phase("processing_analysis", "正在初始化分析任务…", 0.08)
            analysis = analyze_question(manifest, ds, parsed, on_progress)
            self.emit_phase("processing_analysis", "区域统计与热点提取完成。", 1.0)
            time.sleep(0.12)

            self.emit_phase("generating_report", "正在整理证据摘要…", 0.2)
            summary = build_summary(analysis)
            fallback_report = build_fallback_report(analysis)
            time.sleep(0.12)
            self.emit_phase("generating_report", "正在撰写 Markdown 报告…", 0.62)
            report = fallback_report
            warnings = []
            try:
                report = call_deepseek(question, analysis)
            except Exception as exc:
                warnings.append(str(exc))
            self.emit_phase("generating_report", "报告已生成，正在完成输出…", 0.96)
            time.sleep(0.1)

            result = {
                "summary": summary if not warnings else f"{summary} Model report unavailable; showing deterministic summary.",
                "report": report if not warnings else f"{fallback_report}\n\nModel status: {warnings[0]}",
                "suggestions": analysis.get("suggestions", []),
                "resolved": analysis.get("parsed", {}),
            }
            self.emit({"type": "result", "result": result})
        except Exception as exc:
            self.emit({"type": "error", "message": str(exc)})

    def emit_phase(self, phase: str, detail: str, progress: float | None = None) -> None:
        payload = {
            "type": "phase",
            "phase": phase,
            "label": PHASE_LABELS.get(phase, phase),
            "detail": detail,
        }
        if progress is not None:
            payload["progress"] = max(0.0, min(1.0, float(progress)))
        self.emit(payload)

    def emit(self, payload: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()



def main() -> None:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(MANIFEST_PATH)
    server = ThreadingHTTPServer((HOST, PORT), AssistantHandler)
    print(f"Forecast assistant listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
