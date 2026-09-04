from __future__ import annotations

import json

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.core.config import get_settings

from app.ml.macro_max_lib import (
    SpatialContext,
    context_from_serializable,
)


@dataclass
class RuntimeArtifacts:

    bundle: dict[str, Any]

    context_artifact: dict[str, Any]

    ambiguity_policy: dict[str, Any]

    spatial_context: SpatialContext

    cell_lookup: dict[
        tuple[int, int],
        int,
    ]

    cell_keys: np.ndarray

    center_matrix: np.ndarray

    structural_matrix: np.ndarray

    spatial_feature_names: list[str]

    center_feature_names: list[str]

    structural_feature_names: list[str]


def _validate_artifacts(
    bundle: dict[str, Any],
    context: dict[str, Any],
    ambiguity_policy: dict[str, Any],
) -> None:

    if int(
        bundle.get(
            "feature_count",
            -1,
        )
    ) != 422:

        raise RuntimeError(
            "El bundle cargado no contiene "
            "las 422 features esperadas."
        )

    if int(
        bundle.get(
            "base_feature_count",
            -1,
        )
    ) != 364:

        raise RuntimeError(
            "El bundle no contiene "
            "364 features base."
        )

    if int(
        bundle.get(
            "structural_feature_count",
            -1,
        )
    ) != 53:

        raise RuntimeError(
            "El bundle no contiene "
            "53 features estructurales."
        )

    bundle_version = str(
        bundle.get(
            "bundle_version",
            "",
        )
    )

    context_bundle_version = str(
        context.get(
            "bundle_version",
            "",
        )
    )

    if (
        context_bundle_version
        and
        context_bundle_version
        != bundle_version
    ):

        raise RuntimeError(
            "El contexto espacial no corresponde "
            "al bundle del modelo."
        )

    if int(
        context.get(
            "n_spatial_features",
            -1,
        )
    ) != 332:

        raise RuntimeError(
            "El contexto no contiene "
            "332 features espaciales."
        )

    if int(
        context.get(
            "n_center_features",
            -1,
        )
    ) != 32:

        raise RuntimeError(
            "El contexto no contiene "
            "32 features center-safe."
        )

    if int(
        context.get(
            "n_structural_features",
            -1,
        )
    ) != 53:

        raise RuntimeError(
            "El contexto no contiene "
            "53 features estructurales."
        )

    if (
        ambiguity_policy.get(
            "decision"
        )
        !=
        "ENABLE_AMBIGUITY_POLICY"
    ):

        raise RuntimeError(
            "La política de ambigüedad cargada "
            "no está aprobada para producción."
        )

    final_policy = (
        ambiguity_policy.get(
            "final_policy"
        )
    )

    if not isinstance(
        final_policy,
        dict,
    ):

        raise RuntimeError(
            "AMBIGUITY_POLICY.json no contiene "
            "final_policy."
        )

    required_thresholds = {
        "p_threshold",
        "margin_threshold",
        "entropy_threshold",
    }

    missing = (
        required_thresholds
        -
        set(
            final_policy
        )
    )

    if missing:

        raise RuntimeError(
            "Faltan umbrales en la política "
            f"de ambigüedad: {sorted(missing)}"
        )


@lru_cache(maxsize=1)
def get_runtime_artifacts() -> RuntimeArtifacts:

    settings = get_settings()

    bundle_path = Path(
        settings.model_bundle_path
    )

    context_path = Path(
        settings.model_context_path
    )

    ambiguity_path = Path(
        settings.model_ambiguity_path
    )

    if not bundle_path.exists():

        raise FileNotFoundError(
            "No se encontró el bundle del modelo: "
            f"{bundle_path}"
        )

    if not context_path.exists():

        raise FileNotFoundError(
            "No se encontró el contexto "
            f"de inferencia: {context_path}"
        )

    if not ambiguity_path.exists():

        raise FileNotFoundError(
            "No se encontró la política "
            f"de ambigüedad: {ambiguity_path}"
        )

    bundle = joblib.load(
        bundle_path
    )

    context_artifact = joblib.load(
        context_path
    )

    ambiguity_policy = json.loads(
        ambiguity_path.read_text(
            encoding="utf-8"
        )
    )

    _validate_artifacts(
        bundle,
        context_artifact,
        ambiguity_policy,
    )

    spatial_context = (
        context_from_serializable(
            context_artifact[
                "spatial_context"
            ]
        )
    )

    cell_keys = np.asarray(
        context_artifact[
            "cell_keys"
        ],
        dtype=np.int32,
    )

    center_matrix = np.asarray(
        context_artifact[
            "center_matrix"
        ],
        dtype=np.float32,
    )

    structural_matrix = np.asarray(
        context_artifact[
            "structural_matrix"
        ],
        dtype=np.float32,
    )

    if len(
        cell_keys
    ) != len(
        center_matrix
    ):

        raise RuntimeError(
            "cell_keys y center_matrix "
            "no tienen la misma longitud."
        )

    if len(
        cell_keys
    ) != len(
        structural_matrix
    ):

        raise RuntimeError(
            "cell_keys y structural_matrix "
            "no tienen la misma longitud."
        )

    cell_lookup = {

        (
            int(
                cell[0]
            ),
            int(
                cell[1]
            ),
        ):
        index

        for index, cell
        in enumerate(
            cell_keys
        )
    }

    return RuntimeArtifacts(

        bundle=bundle,

        context_artifact=(
            context_artifact
        ),

        ambiguity_policy=(
            ambiguity_policy
        ),

        spatial_context=(
            spatial_context
        ),

        cell_lookup=(
            cell_lookup
        ),

        cell_keys=(
            cell_keys
        ),

        center_matrix=(
            center_matrix
        ),

        structural_matrix=(
            structural_matrix
        ),

        spatial_feature_names=list(
            context_artifact[
                "spatial_feature_names"
            ]
        ),

        center_feature_names=list(
            context_artifact[
                "center_feature_names"
            ]
        ),

        structural_feature_names=list(
            context_artifact[
                "structural_feature_names"
            ]
        ),
    )