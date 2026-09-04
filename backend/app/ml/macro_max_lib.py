from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.optimize import minimize_scalar
from scipy.spatial import cKDTree
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.utils.class_weight import compute_sample_weight

try:
    from xgboost import XGBClassifier
except Exception:  # pragma: no cover
    XGBClassifier = None

try:
    from lightgbm import LGBMClassifier
except Exception:  # pragma: no cover
    LGBMClassifier = None

RANDOM_STATE = 42
EPS = 1e-12
MACRO_NAMES = {
    1: "Producción, infraestructura y comercio mayorista",
    2: "Comercio minorista",
    3: "Servicios especializados, empresariales y sociales",
    4: "Servicios al consumidor, recreativos y públicos",
}

# Actividad_id del proyecto -> macroclase.
def actividad_to_macro(a: int) -> int:
    a = int(a)
    if 1 <= a <= 6:
        return 1
    if a == 7:
        return 2
    if 8 <= a <= 16:
        return 3
    if 17 <= a <= 20:
        return 4
    raise ValueError(f"actividad_id fuera del catálogo esperado 1..20: {a}")


def seed_everything(seed: int = RANDOM_STATE) -> None:
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def parse_personal_ocupado(value: Any) -> float:
    """Convierte estratos DENUE de personal ocupado a un punto representativo.

    La variable se usa SOLO como feature de contexto, nunca para construir el target.
    Si no se reconoce el valor, devuelve NaN y luego se imputa con 0.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, np.integer, float, np.floating)):
        return float(value)
    s = str(value).strip().lower()
    if not s or s in {"nan", "none", "\\n"}:
        return np.nan
    # Formatos típicos DENUE: "0 a 5 personas", "6 a 10 personas", "251 y más personas".
    import re

    nums = [int(x) for x in re.findall(r"\d+", s)]
    if "más" in s or "mas" in s:
        if nums:
            # Tope abierto: se usa un valor conservador ligeramente mayor al umbral.
            return float(nums[0] * 1.25)
    if len(nums) >= 2:
        return float((nums[0] + nums[1]) / 2.0)
    if len(nums) == 1:
        return float(nums[0])
    return np.nan


def load_dataset(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"lat", "lon", "actividad_id"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {sorted(missing)}")

    out = df.copy()
    for col in ["lat", "lon", "actividad_id"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["lat", "lon", "actividad_id"]).copy()
    out["actividad_id"] = out["actividad_id"].astype(int)
    out = out[out["actividad_id"].between(1, 20)].copy()
    out = out[out["lat"].between(18.5, 20.5) & out["lon"].between(-100.5, -98.0)].copy()
    out["macro_id"] = out["actividad_id"].map(actividad_to_macro).astype(int)

    if "per_ocu" in out.columns:
        out["empleo_aprox"] = out["per_ocu"].map(parse_personal_ocupado)
    elif "empleo_aprox" in out.columns:
        out["empleo_aprox"] = pd.to_numeric(out["empleo_aprox"], errors="coerce")
    else:
        out["empleo_aprox"] = np.nan
    out["empleo_aprox"] = out["empleo_aprox"].fillna(0.0).clip(lower=0.0)

    return out.reset_index(drop=True)


def to_utm(df: pd.DataFrame) -> pd.DataFrame:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32614", always_xy=True)
    x, y = transformer.transform(df["lon"].to_numpy(), df["lat"].to_numpy())
    out = df.copy()
    out["utm_x"] = x
    out["utm_y"] = y
    return out


@dataclass
class SpatialContext:
    cell_size: int
    radii: tuple[int, ...]
    max_radius: int
    min_cx: int
    max_cx: int
    min_cy: int
    max_cy: int
    counts_grid: np.ndarray  # [H,W,4]
    emp_grid: np.ndarray  # [H,W,4]
    target_cells: np.ndarray  # [N,2] cx,cy; solo dominancia única
    y_macro: np.ndarray  # [N]
    groups: np.ndarray  # [N]
    coords_m: np.ndarray  # [N,2]
    coord_center: np.ndarray  # [2]
    coord_scale: np.ndarray  # [2]
    active_coords_by_macro: dict[int, np.ndarray]
    active_trees_by_macro: dict[int, Any] | None
    has_employment: bool


def build_spatial_context(
    df: pd.DataFrame,
    cell_size: int = 300,
    radii: Iterable[int] = (1, 2, 3, 4, 5),
    block_size_meters: int = 2000,
) -> SpatialContext:
    tmp = to_utm(df)
    tmp["cell_x"] = np.floor(tmp["utm_x"] / cell_size).astype(int)
    tmp["cell_y"] = np.floor(tmp["utm_y"] / cell_size).astype(int)

    counts = (
        tmp.groupby(["cell_x", "cell_y", "macro_id"])
        .size()
        .unstack(fill_value=0)
    )
    for m in range(1, 5):
        if m not in counts.columns:
            counts[m] = 0
    counts = counts[[1, 2, 3, 4]].astype(float)

    emp = (
        tmp.groupby(["cell_x", "cell_y", "macro_id"])["empleo_aprox"]
        .sum()
        .unstack(fill_value=0.0)
    )
    for m in range(1, 5):
        if m not in emp.columns:
            emp[m] = 0.0
    emp = emp[[1, 2, 3, 4]].astype(float)

    vals = counts.to_numpy(dtype=float)
    maxv = vals.max(axis=1)
    unique = (vals == maxv[:, None]).sum(axis=1) == 1
    target_counts = counts.loc[unique]
    y_macro = target_counts.to_numpy().argmax(axis=1).astype(int) + 1
    target_cells = np.asarray(target_counts.index.tolist(), dtype=int)

    min_cx = int(counts.index.get_level_values(0).min())
    max_cx = int(counts.index.get_level_values(0).max())
    min_cy = int(counts.index.get_level_values(1).min())
    max_cy = int(counts.index.get_level_values(1).max())
    W = max_cx - min_cx + 1
    H = max_cy - min_cy + 1

    counts_grid = np.zeros((H, W, 4), dtype=np.float32)
    emp_grid = np.zeros((H, W, 4), dtype=np.float32)
    for idx, row in counts.iterrows():
        cx, cy = idx
        gx, gy = int(cx - min_cx), int(cy - min_cy)
        counts_grid[gy, gx, :] = row.to_numpy(dtype=np.float32)
        emp_grid[gy, gx, :] = emp.loc[idx].to_numpy(dtype=np.float32)

    coords_m = np.column_stack([
        (target_cells[:, 0] + 0.5) * cell_size,
        (target_cells[:, 1] + 0.5) * cell_size,
    ]).astype(float)
    groups_xy = np.floor(coords_m / float(block_size_meters)).astype(int)
    # Factorización estable de pares (bx,by) sin depender de rangos arbitrarios.
    _, groups = np.unique(groups_xy, axis=0, return_inverse=True)

    coord_center = coords_m.mean(axis=0)
    coord_scale = coords_m.std(axis=0)
    coord_scale[coord_scale == 0] = 1.0

    active_coords_by_macro: dict[int, np.ndarray] = {}
    active_trees_by_macro: dict[int, Any] = {}
    for m in range(1, 5):
        active_idx = counts.index[counts[m] > 0]
        arr = np.asarray([
            ((cx + 0.5) * cell_size, (cy + 0.5) * cell_size)
            for cx, cy in active_idx
        ], dtype=float)
        active_coords_by_macro[m] = arr
        active_trees_by_macro[m] = cKDTree(arr) if len(arr) else None

    return SpatialContext(
        cell_size=cell_size,
        radii=tuple(sorted(set(int(r) for r in radii))),
        max_radius=max(int(r) for r in radii),
        min_cx=min_cx,
        max_cx=max_cx,
        min_cy=min_cy,
        max_cy=max_cy,
        counts_grid=counts_grid,
        emp_grid=emp_grid,
        target_cells=target_cells,
        y_macro=y_macro,
        groups=groups.astype(np.int64),
        coords_m=coords_m,
        coord_center=coord_center,
        coord_scale=coord_scale,
        active_coords_by_macro=active_coords_by_macro,
        active_trees_by_macro=active_trees_by_macro,
        has_employment=bool(float(emp_grid.sum()) > 0.0),
    )


def _safe_cell(context: SpatialContext, cx: int, cy: int) -> tuple[np.ndarray, np.ndarray]:
    gx, gy = cx - context.min_cx, cy - context.min_cy
    if 0 <= gx < context.counts_grid.shape[1] and 0 <= gy < context.counts_grid.shape[0]:
        return context.counts_grid[gy, gx], context.emp_grid[gy, gx]
    return np.zeros(4, dtype=float), np.zeros(4, dtype=float)


def _entropy_simpson(props: np.ndarray) -> tuple[float, float, float, float]:
    props = np.asarray(props, dtype=float)
    nz = props > 0
    entropy = float(-(props[nz] * np.log(props[nz])).sum()) if np.any(nz) else 0.0
    simpson = float(1.0 - np.sum(props ** 2)) if props.sum() > 0 else 0.0
    ordered = np.sort(props)
    max_prop = float(ordered[-1]) if ordered.size else 0.0
    margin = float(ordered[-1] - ordered[-2]) if ordered.size >= 2 else max_prop
    return entropy, simpson, max_prop, margin


def _summary_features(vec: np.ndarray, prefix: str) -> tuple[list[float], list[str]]:
    vec = np.asarray(vec, dtype=float)
    total = float(vec.sum())
    props = vec / total if total > 0 else np.zeros_like(vec)
    ent, simp, max_prop, margin = _entropy_simpson(props)
    values = list(vec) + list(props) + [total, math.log1p(total), ent, simp, max_prop, margin]
    names = (
        [f"{prefix}_count_m{m}" for m in range(1, 5)]
        + [f"{prefix}_prop_m{m}" for m in range(1, 5)]
        + [f"{prefix}_total", f"{prefix}_log_total", f"{prefix}_entropy", f"{prefix}_simpson", f"{prefix}_max_prop", f"{prefix}_margin"]
    )
    return values, names


def _employment_features(emp: np.ndarray, counts: np.ndarray, prefix: str) -> tuple[list[float], list[str]]:
    emp = np.asarray(emp, dtype=float)
    counts = np.asarray(counts, dtype=float)
    total_emp = float(emp.sum())
    emp_props = emp / total_emp if total_emp > 0 else np.zeros_like(emp)
    mean_emp = np.divide(emp, counts, out=np.zeros_like(emp), where=counts > 0)
    values = list(emp) + list(emp_props) + list(mean_emp) + [total_emp, math.log1p(total_emp)]
    names = (
        [f"{prefix}_emp_m{m}" for m in range(1, 5)]
        + [f"{prefix}_emp_prop_m{m}" for m in range(1, 5)]
        + [f"{prefix}_mean_emp_per_est_m{m}" for m in range(1, 5)]
        + [f"{prefix}_emp_total", f"{prefix}_log_emp_total"]
    )
    return values, names


def _neighbor_accumulations(context: SpatialContext, cx: int, cy: int) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray], dict[int, np.ndarray], dict[int, np.ndarray]]:
    cumulative_counts: dict[int, np.ndarray] = {}
    ring_counts: dict[int, np.ndarray] = {}
    cumulative_emp: dict[int, np.ndarray] = {}
    ring_emp: dict[int, np.ndarray] = {}

    prev_c = np.zeros(4, dtype=float)
    prev_e = np.zeros(4, dtype=float)
    for r in context.radii:
        csum = np.zeros(4, dtype=float)
        esum = np.zeros(4, dtype=float)
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx == 0 and dy == 0:
                    continue  # PRINCIPIO INNEGOCIABLE: centro oculto.
                c, e = _safe_cell(context, cx + dx, cy + dy)
                csum += c
                esum += e
        cumulative_counts[r] = csum
        cumulative_emp[r] = esum
        ring_counts[r] = csum - prev_c
        ring_emp[r] = esum - prev_e
        prev_c = csum
        prev_e = esum
    return cumulative_counts, ring_counts, cumulative_emp, ring_emp


def _kernel_features(context: SpatialContext, cx: int, cy: int, bandwidth_cells: float) -> np.ndarray:
    out = np.zeros(4, dtype=float)
    rmax = context.max_radius
    for dx in range(-rmax, rmax + 1):
        for dy in range(-rmax, rmax + 1):
            if dx == 0 and dy == 0:
                continue
            d = math.sqrt(dx * dx + dy * dy)
            if d == 0:
                continue
            # Kernel gaussiano no normalizado; suficiente como feature de intensidad relativa.
            w = math.exp(-0.5 * (d / max(bandwidth_cells, 0.25)) ** 2)
            c, _ = _safe_cell(context, cx + dx, cy + dy)
            out += w * c
    return out


def _knn_distance_features(context: SpatialContext, x_m: float, y_m: float, ks=(1, 3, 5)) -> tuple[list[float], list[str]]:
    vals: list[float] = []
    names: list[str] = []
    point = np.asarray([[x_m, y_m]], dtype=float)
    for m in range(1, 5):
        coords = context.active_coords_by_macro[m]
        if len(coords) == 0:
            for k in ks:
                vals.append(float(context.cell_size * (context.max_radius + 10)))
                names.append(f"knn_m{m}_d{k}")
            continue
        tree = context.active_trees_by_macro[m] if context.active_trees_by_macro is not None else cKDTree(coords)
        qk = min(len(coords), max(ks) + 2)
        dists, _ = tree.query(point, k=qk)
        dists = np.atleast_1d(dists).reshape(-1)
        # Si la celda objetivo contiene esa macroclase, habrá distancia 0. Se elimina para evitar fuga.
        dists = dists[dists > 1e-9]
        for k in ks:
            if len(dists) >= k:
                d = float(dists[k - 1])
            elif len(dists) > 0:
                d = float(dists[-1])
            else:
                d = float(context.cell_size * (context.max_radius + 10))
            vals.append(d)
            names.append(f"knn_m{m}_d{k}")
    return vals, names


def build_feature_for_cell(context: SpatialContext, cx: int, cy: int, profile: str) -> tuple[np.ndarray, list[str]]:
    cumulative_counts, ring_counts, cumulative_emp, ring_emp = _neighbor_accumulations(context, cx, cy)
    values: list[float] = []
    names: list[str] = []

    if profile == "core26":
        # Replica conceptual del cumulative_v2 de 4 macroclases, radios 1 y 2.
        for r in (1, 2):
            c = cumulative_counts[r]
            total = float(c.sum())
            props = c / total if total > 0 else np.zeros(4, dtype=float)
            ent, simp, max_prop, margin = _entropy_simpson(props)
            values.extend(list(c) + list(props) + [total, ent, simp, max_prop, margin])
            names.extend(
                [f"r{r}_count_m{m}" for m in range(1, 5)]
                + [f"r{r}_prop_m{m}" for m in range(1, 5)]
                + [f"r{r}_total", f"r{r}_entropy", f"r{r}_simpson", f"r{r}_max_prop", f"r{r}_margin"]
            )
        return np.asarray(values, dtype=np.float32), names

    if profile not in {"spatial_v4", "spatial_v4_coords"}:
        raise ValueError(f"Perfil de features desconocido: {profile}")

    # Multiescala: acumulados y anillos independientes hasta 1500 m.
    for r in context.radii:
        v, n = _summary_features(cumulative_counts[r], f"cum_r{r}")
        values.extend(v); names.extend(n)
        v, n = _summary_features(ring_counts[r], f"ring_r{r}")
        values.extend(v); names.extend(n)
        if context.has_employment:
            v, n = _employment_features(cumulative_emp[r], cumulative_counts[r], f"cum_r{r}")
            values.extend(v); names.extend(n)
            v, n = _employment_features(ring_emp[r], ring_counts[r], f"ring_r{r}")
            values.extend(v); names.extend(n)

    # Gradientes espaciales entre escalas; ayudan a detectar transición hacia corredores.
    rmin, rmax = min(context.radii), max(context.radii)
    for m in range(4):
        p_near = cumulative_counts[rmin][m] / max(cumulative_counts[rmin].sum(), 1.0)
        p_far = cumulative_counts[rmax][m] / max(cumulative_counts[rmax].sum(), 1.0)
        values.append(float(p_far - p_near))
        names.append(f"gradient_prop_m{m+1}_r{rmin}_r{rmax}")
        values.append(float(math.log1p(cumulative_counts[rmax][m]) - math.log1p(cumulative_counts[rmin][m])))
        names.append(f"gradient_logcount_m{m+1}_r{rmin}_r{rmax}")

    # Intensidad ponderada por distancia para varios bandwidths.
    for bw in (1.0, 2.0, 3.5, 5.0):
        kv = _kernel_features(context, cx, cy, bw)
        total = max(float(kv.sum()), EPS)
        for m in range(4):
            values.append(float(kv[m])); names.append(f"kernel_bw{bw:g}_m{m+1}")
        for m in range(4):
            values.append(float(kv[m] / total)); names.append(f"kernelprop_bw{bw:g}_m{m+1}")

    x_m = (cx + 0.5) * context.cell_size
    y_m = (cy + 0.5) * context.cell_size
    kv, kn = _knn_distance_features(context, x_m, y_m)
    values.extend(kv); names.extend(kn)

    if profile == "spatial_v4_coords":
        nx = (x_m - context.coord_center[0]) / context.coord_scale[0]
        ny = (y_m - context.coord_center[1]) / context.coord_scale[1]
        r = math.sqrt(nx * nx + ny * ny)
        angle = math.atan2(ny, nx)
        values.extend([nx, ny, nx * ny, nx * nx, ny * ny, r, math.sin(angle), math.cos(angle)])
        names.extend(["utm_x_norm", "utm_y_norm", "utm_xy", "utm_x2", "utm_y2", "utm_radius", "utm_angle_sin", "utm_angle_cos"])

    return np.asarray(values, dtype=np.float32), names


def build_feature_matrix(context: SpatialContext, profile: str) -> tuple[np.ndarray, list[str]]:
    X: list[np.ndarray] = []
    feature_names: list[str] | None = None
    for i, (cx, cy) in enumerate(context.target_cells):
        x, names = build_feature_for_cell(context, int(cx), int(cy), profile)
        if feature_names is None:
            feature_names = names
        elif len(names) != len(feature_names):
            raise RuntimeError("Número inconsistente de features.")
        X.append(x)
        if (i + 1) % 1000 == 0:
            print(f"  Features {profile}: {i+1}/{len(context.target_cells)}")
    return np.asarray(X, dtype=np.float32), feature_names or []


def context_to_serializable(context: SpatialContext) -> dict[str, Any]:
    return {
        "cell_size": context.cell_size,
        "radii": list(context.radii),
        "max_radius": context.max_radius,
        "min_cx": context.min_cx,
        "max_cx": context.max_cx,
        "min_cy": context.min_cy,
        "max_cy": context.max_cy,
        "counts_grid": context.counts_grid,
        "emp_grid": context.emp_grid,
        "coord_center": context.coord_center,
        "coord_scale": context.coord_scale,
        "active_coords_by_macro": context.active_coords_by_macro,
        "has_employment": context.has_employment,
    }


def context_from_serializable(data: dict[str, Any]) -> SpatialContext:
    # Campos de targets no son necesarios para inferencia individual.
    return SpatialContext(
        cell_size=int(data["cell_size"]),
        radii=tuple(int(x) for x in data["radii"]),
        max_radius=int(data["max_radius"]),
        min_cx=int(data["min_cx"]),
        max_cx=int(data["max_cx"]),
        min_cy=int(data["min_cy"]),
        max_cy=int(data["max_cy"]),
        counts_grid=np.asarray(data["counts_grid"]),
        emp_grid=np.asarray(data["emp_grid"]),
        target_cells=np.empty((0, 2), dtype=int),
        y_macro=np.empty(0, dtype=int),
        groups=np.empty(0, dtype=int),
        coords_m=np.empty((0, 2), dtype=float),
        coord_center=np.asarray(data["coord_center"], dtype=float),
        coord_scale=np.asarray(data["coord_scale"], dtype=float),
        active_coords_by_macro={int(k): np.asarray(v) for k, v in data["active_coords_by_macro"].items()},
        active_trees_by_macro={int(k): (cKDTree(np.asarray(v)) if len(v) else None) for k, v in data["active_coords_by_macro"].items()},
        has_employment=bool(data.get("has_employment", False)),
    )


def model_names(search_level: str = "full") -> list[str]:
    names = ["rf", "et", "hgb"]
    if search_level == "max":
        if XGBClassifier is not None:
            names.append("xgb")
        if LGBMClassifier is not None:
            names.append("lgbm")
    return names


def make_model(name: str, random_state: int = RANDOM_STATE):
    if name == "rf":
        return RandomForestClassifier(
            n_estimators=500,
            max_depth=24,
            min_samples_leaf=2,
            min_samples_split=4,
            max_features="sqrt",
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=random_state,
        )
    if name == "et":
        return ExtraTreesClassifier(
            n_estimators=500,
            max_depth=None,
            min_samples_leaf=2,
            min_samples_split=4,
            max_features="sqrt",
            class_weight="balanced",
            n_jobs=-1,
            random_state=random_state,
        )
    if name == "hgb":
        return HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=350,
            max_leaf_nodes=31,
            min_samples_leaf=15,
            l2_regularization=0.5,
            random_state=random_state,
        )
    if name == "xgb" and XGBClassifier is not None:
        return XGBClassifier(
            n_estimators=500,
            max_depth=6,
            learning_rate=0.04,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_weight=2,
            reg_lambda=2.0,
            reg_alpha=0.05,
            objective="binary:logistic",
            eval_metric="logloss",
            n_jobs=-1,
            random_state=random_state,
        )
    if name == "lgbm" and LGBMClassifier is not None:
        return LGBMClassifier(
            n_estimators=500,
            num_leaves=31,
            learning_rate=0.04,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=2.0,
            reg_alpha=0.05,
            n_jobs=-1,
            random_state=random_state,
            verbosity=-1,
        )
    raise ValueError(f"Modelo no disponible: {name}")


def fit_binary_model(model, X: np.ndarray, y: np.ndarray):
    sw = compute_sample_weight(class_weight="balanced", y=y)
    try:
        model.fit(X, y, sample_weight=sw)
    except TypeError:
        model.fit(X, y)
    return model


def positive_probability(model, X: np.ndarray) -> np.ndarray:
    p = model.predict_proba(X)
    classes = np.asarray(model.classes_)
    pos = np.where(classes == 1)[0]
    if len(pos) != 1:
        raise RuntimeError(f"El clasificador binario no contiene clase positiva 1: {classes}")
    return np.asarray(p[:, pos[0]], dtype=float)


def stage_labels(y_macro: np.ndarray, stage: int) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y_macro, dtype=int)
    if stage == 1:
        mask = np.ones(len(y), dtype=bool)
        yy = (y == 2).astype(int)  # comercio vs resto
    elif stage == 2:
        mask = y != 2
        yy = (y == 1).astype(int)  # producción vs servicios
    elif stage == 3:
        mask = np.isin(y, [3, 4])
        yy = (y == 3).astype(int)  # servicios especializados vs consumidor
    else:
        raise ValueError(stage)
    return mask, yy


def hierarchical_soft_probs(p_stage1: np.ndarray, p_stage2: np.ndarray, p_stage3: np.ndarray) -> np.ndarray:
    p2 = np.clip(np.asarray(p_stage1, dtype=float), EPS, 1 - EPS)
    p1c = np.clip(np.asarray(p_stage2, dtype=float), EPS, 1 - EPS)
    p3c = np.clip(np.asarray(p_stage3, dtype=float), EPS, 1 - EPS)
    p = np.column_stack([
        (1 - p2) * p1c,
        p2,
        (1 - p2) * (1 - p1c) * p3c,
        (1 - p2) * (1 - p1c) * (1 - p3c),
    ])
    p = np.clip(p, EPS, None)
    p /= p.sum(axis=1, keepdims=True)
    return p


def hierarchical_hard_predict(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, thresholds: tuple[float, float, float]) -> np.ndarray:
    t1, t2, t3 = thresholds
    out = np.empty(len(p1), dtype=int)
    commerce = p1 >= t1
    out[commerce] = 2
    rest = ~commerce
    prod = rest & (p2 >= t2)
    out[prod] = 1
    services = rest & ~prod
    spec = services & (p3 >= t3)
    out[spec] = 3
    out[services & ~spec] = 4
    return out


def tune_thresholds(y_true: np.ndarray, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, grid: np.ndarray | None = None) -> tuple[tuple[float, float, float], float]:
    if grid is None:
        grid = np.round(np.arange(0.35, 0.676, 0.025), 3)
    thresholds = [0.5, 0.5, 0.5]
    best_score = -1.0
    # Coordinate descent: suficiente y mucho más barato que grid 3D exhaustivo.
    for _ in range(4):
        improved = False
        for j in range(3):
            local_best = thresholds[j]
            local_score = -1.0
            for t in grid:
                trial = thresholds.copy()
                trial[j] = float(t)
                pred = hierarchical_hard_predict(p1, p2, p3, tuple(trial))
                score = f1_score(y_true, pred, average="macro", labels=[1, 2, 3, 4], zero_division=0)
                if score > local_score + 1e-12:
                    local_score = float(score)
                    local_best = float(t)
            if local_best != thresholds[j]:
                improved = True
            thresholds[j] = local_best
            best_score = max(best_score, local_score)
        if not improved:
            break
    pred = hierarchical_hard_predict(p1, p2, p3, tuple(thresholds))
    final = float(f1_score(y_true, pred, average="macro", labels=[1, 2, 3, 4], zero_division=0))
    return (float(thresholds[0]), float(thresholds[1]), float(thresholds[2])), final


def apply_temperature(proba: np.ndarray, temperature: float) -> np.ndarray:
    p = np.clip(np.asarray(proba, dtype=float), EPS, 1.0)
    logits = np.log(p) / max(float(temperature), 1e-4)
    logits -= logits.max(axis=1, keepdims=True)
    e = np.exp(logits)
    return e / e.sum(axis=1, keepdims=True)


def fit_temperature(y_true: np.ndarray, proba: np.ndarray) -> float:
    labels = [1, 2, 3, 4]

    def objective(log_t: float) -> float:
        t = math.exp(float(log_t))
        p = apply_temperature(proba, t)
        return float(log_loss(y_true, p, labels=labels))

    res = minimize_scalar(objective, bounds=(math.log(0.35), math.log(3.0)), method="bounded")
    return float(math.exp(res.x))


def ece_score(y_true: np.ndarray, proba: np.ndarray, n_bins: int = 10) -> float:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(proba, dtype=float)
    pred = np.argmax(p, axis=1) + 1
    conf = p.max(axis=1)
    correct = (pred == y).astype(float)
    edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        if i == n_bins - 1:
            mask = (conf >= edges[i]) & (conf <= edges[i + 1])
        else:
            mask = (conf >= edges[i]) & (conf < edges[i + 1])
        if not np.any(mask):
            continue
        ece += float(mask.mean()) * abs(float(correct[mask].mean()) - float(conf[mask].mean()))
    return float(ece)


def multiclass_brier(y_true: np.ndarray, proba: np.ndarray) -> float:
    onehot = np.zeros_like(proba, dtype=float)
    onehot[np.arange(len(y_true)), np.asarray(y_true, dtype=int) - 1] = 1.0
    return float(np.mean(np.sum((proba - onehot) ** 2, axis=1)))


def topk_accuracy(y_true: np.ndarray, proba: np.ndarray, k: int) -> float:
    top = np.argsort(proba, axis=1)[:, -k:] + 1
    return float(np.mean([int(y_true[i]) in top[i] for i in range(len(y_true))]))


def multiclass_metrics(y_true: np.ndarray, y_pred: np.ndarray, proba: np.ndarray) -> dict[str, float]:
    p = np.clip(np.asarray(proba, dtype=float), EPS, 1.0)
    p /= p.sum(axis=1, keepdims=True)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=[1, 2, 3, 4], zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "top2_soft": topk_accuracy(y_true, p, 2),
        "top3_soft": topk_accuracy(y_true, p, 3),
        "log_loss_soft": float(log_loss(y_true, p, labels=[1, 2, 3, 4])),
        "brier_multiclass_soft": multiclass_brier(y_true, p),
        "ece_10bins_soft": ece_score(y_true, p, 10),
    }


def save_json(path: str | Path, data: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stage_oof_predictions(
    X: np.ndarray,
    y_macro: np.ndarray,
    groups: np.ndarray,
    stage: int,
    model_name: str,
    n_splits: int,
    seed: int,
) -> np.ndarray:
    mask_stage, y_stage_all = stage_labels(y_macro, stage)
    # Split se hace con la multicategoría original para preservar geografía y composición.
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    oof = np.full(len(y_macro), np.nan, dtype=float)
    for fold, (tr, va) in enumerate(splitter.split(np.zeros(len(y_macro)), y_macro, groups), start=1):
        train_stage = tr[mask_stage[tr]]
        if len(np.unique(y_stage_all[train_stage])) < 2:
            raise RuntimeError(f"Stage {stage}: un fold interno quedó con una sola clase.")
        model = make_model(model_name, random_state=seed + fold * 37 + stage * 101)
        fit_binary_model(model, X[train_stage], y_stage_all[train_stage])
        oof[va] = positive_probability(model, X[va])
    if np.isnan(oof).any():
        raise RuntimeError("OOF incompleto.")
    return oof


def fit_stage_model(X: np.ndarray, y_macro: np.ndarray, stage: int, model_name: str, seed: int):
    mask, yy = stage_labels(y_macro, stage)
    model = make_model(model_name, random_state=seed + stage * 101)
    fit_binary_model(model, X[mask], yy[mask])
    return model


def select_inner_configuration(
    profiles: dict[str, np.ndarray],
    y: np.ndarray,
    groups: np.ndarray,
    candidates: list[str],
    n_splits: int,
    seed: int,
    keep_top_per_stage: int = 2,
) -> dict[str, Any]:
    """Selecciona perfil + modelo de cada etapa + thresholds usando SOLO el train externo."""
    best: dict[str, Any] | None = None
    for profile_name, X in profiles.items():
        print(f"    [inner] perfil {profile_name} ({X.shape[1]} features)")
        stage_probs: dict[int, dict[str, np.ndarray]] = {1: {}, 2: {}, 3: {}}
        stage_scores: dict[int, list[tuple[float, str]]] = {1: [], 2: [], 3: []}
        for stage in (1, 2, 3):
            mask, yy = stage_labels(y, stage)
            for model_name in candidates:
                try:
                    p = stage_oof_predictions(X, y, groups, stage, model_name, n_splits, seed + stage * 1000)
                except Exception as exc:
                    print(f"      {model_name} stage {stage}: omitido ({exc})")
                    continue
                stage_probs[stage][model_name] = p
                pred_bin = (p[mask] >= 0.5).astype(int)
                score = float(f1_score(yy[mask], pred_bin, average="macro", zero_division=0))
                stage_scores[stage].append((score, model_name))
                print(f"      stage {stage} {model_name}: binary MacroF1={score:.4f}")

        top_models: dict[int, list[str]] = {}
        for stage in (1, 2, 3):
            ranked = sorted(stage_scores[stage], reverse=True)
            if not ranked:
                raise RuntimeError(f"No quedó ningún modelo válido para stage {stage}.")
            top_models[stage] = [name for _, name in ranked[:keep_top_per_stage]]

        for m1, m2, m3 in product(top_models[1], top_models[2], top_models[3]):
            p1 = stage_probs[1][m1]
            p2 = stage_probs[2][m2]
            p3 = stage_probs[3][m3]
            thresholds, score = tune_thresholds(y, p1, p2, p3)
            soft = hierarchical_soft_probs(p1, p2, p3)
            temp = fit_temperature(y, soft)
            pred = hierarchical_hard_predict(p1, p2, p3, thresholds)
            bal = float(balanced_accuracy_score(y, pred))
            candidate = {
                "profile": profile_name,
                "models": {"stage1": m1, "stage2": m2, "stage3": m3},
                "thresholds": thresholds,
                "macro_f1": score,
                "balanced_accuracy": bal,
                "temperature": temp,
            }
            if best is None or (score, bal) > (best["macro_f1"], best["balanced_accuracy"]):
                best = candidate
        print(f"    Mejor {profile_name}: MacroF1={best['macro_f1']:.4f} perfil_global={best['profile']}")
    assert best is not None
    return best


def train_selected_configuration(
    X: np.ndarray,
    y: np.ndarray,
    config: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    models = {}
    for stage in (1, 2, 3):
        name = config["models"][f"stage{stage}"]
        models[f"stage{stage}"] = fit_stage_model(X, y, stage, name, seed + stage * 10000)
    return models


def predict_selected_configuration(models: dict[str, Any], X: np.ndarray, thresholds: tuple[float, float, float], temperature: float) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    p1 = positive_probability(models["stage1"], X)
    p2 = positive_probability(models["stage2"], X)
    p3 = positive_probability(models["stage3"], X)
    pred = hierarchical_hard_predict(p1, p2, p3, thresholds)
    soft = hierarchical_soft_probs(p1, p2, p3)
    soft_cal = apply_temperature(soft, temperature)
    return pred, soft_cal, (p1, p2, p3)


def transformer_to_utm(lon: float, lat: float) -> tuple[float, float]:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32614", always_xy=True)
    x, y = transformer.transform(float(lon), float(lat))
    return float(x), float(y)


def feature_for_coordinate(context: SpatialContext, lat: float, lon: float, profile: str) -> tuple[np.ndarray, list[str], tuple[int, int]]:
    x, y = transformer_to_utm(lon, lat)
    cx, cy = int(math.floor(x / context.cell_size)), int(math.floor(y / context.cell_size))
    feat, names = build_feature_for_cell(context, cx, cy, profile)
    return feat.reshape(1, -1), names, (cx, cy)
