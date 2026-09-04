from __future__ import annotations

import math
from typing import Any

import numpy as np
from pyproj import Transformer

from app.ml.macro_max_lib import (
    build_feature_for_cell,
)

from app.ml.model_loader import (
    get_runtime_artifacts,
)

_TRANSFORMER = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:32614",
    always_xy=True,
)


# ============================================================
# HELPERS DE PROBABILIDADES
# ============================================================

def normalize_proba(
    proba,
):

    p = np.asarray(
        proba,
        dtype=float,
    )

    p = np.clip(
        p,
        1e-12,
        None,
    )

    row_sum = p.sum(
        axis=1,
        keepdims=True,
    )

    if np.any(
        ~np.isfinite(
            row_sum
        )
    ):

        raise RuntimeError(
            "Probabilidades no finitas."
        )

    if np.any(
        row_sum <= 0
    ):

        raise RuntimeError(
            "Probabilidades con suma <= 0."
        )

    return (
        p
        /
        row_sum
    )


def temperature_scale(
    proba,
    temperature: float,
):

    p = normalize_proba(
        proba
    )

    logits = np.log(
        np.clip(
            p,
            1e-12,
            1.0,
        )
    )

    logits /= max(
        float(
            temperature
        ),
        1e-6,
    )

    logits -= logits.max(
        axis=1,
        keepdims=True,
    )

    result = np.exp(
        logits
    )

    result /= result.sum(
        axis=1,
        keepdims=True,
    )

    return result


def normalize_ovr(
    scores,
):

    p = np.asarray(
        scores,
        dtype=float,
    )

    p = np.clip(
        p,
        1e-9,
        1.0,
    )

    row_sum = p.sum(
        axis=1,
        keepdims=True,
    )

    bad = (
        ~np.isfinite(
            row_sum[
                :,
                0
            ]
        )
        |
        (
            row_sum[
                :,
                0
            ]
            <= 0
        )
    )

    if np.any(
        bad
    ):

        p[
            bad
        ] = 0.25

        row_sum = p.sum(
            axis=1,
            keepdims=True,
        )

    return (
        p
        /
        row_sum
    )

def build_runtime_features(
    lat: float,
    lon: float,
):

    runtime = (
        get_runtime_artifacts()
    )

    bundle = runtime.bundle

    cell_size = int(
        bundle[
            "cell_size"
        ]
    )

    utm_x, utm_y = (
        _TRANSFORMER.transform(
            lon,
            lat,
        )
    )

    cell_x = math.floor(
        utm_x
        /
        cell_size
    )

    cell_y = math.floor(
        utm_y
        /
        cell_size
    )

    (
        spatial_features,
        spatial_names,
    ) = build_feature_for_cell(
        runtime.spatial_context,
        int(
            cell_x
        ),
        int(
            cell_y
        ),
        str(
            bundle[
                "profile"
            ]
        ),
    )

    if list(
        spatial_names
    ) != runtime.spatial_feature_names:

        raise RuntimeError(
            "El orden de las features espaciales "
            "cambió respecto al entrenamiento."
        )

    if len(
        spatial_features
    ) != 332:

        raise RuntimeError(
            "Se esperaban 332 features "
            f"espaciales y se obtuvieron "
            f"{len(spatial_features)}."
        )

    lookup_key = (
        int(
            cell_x
        ),
        int(
            cell_y
        ),
    )

    row_index = (
        runtime
        .cell_lookup
        .get(
            lookup_key
        )
    )

    occupied = (
        row_index
        is not None
    )

    if occupied:

        center_features = np.asarray(
            runtime.center_matrix[
                row_index
            ],
            dtype=np.float32,
        )

        structural_features = np.asarray(
            runtime.structural_matrix[
                row_index
            ],
            dtype=np.float32,
        )

    else:

        center_features = np.zeros(
            32,
            dtype=np.float32,
        )

        structural_features = np.zeros(
            53,
            dtype=np.float32,
        )

    X364 = np.concatenate(
        [
            spatial_features,
            center_features,
        ]
    ).astype(
        np.float32
    )

    if X364.shape != (
        364,
    ):

        raise RuntimeError(
            "La matriz base no contiene "
            f"364 features: {X364.shape}"
        )

    if structural_features.shape != (
        53,
    ):

        raise RuntimeError(
            "La matriz structural no contiene "
            f"53 features: "
            f"{structural_features.shape}"
        )

    return {

        "utm_x":
            float(
                utm_x
            ),

        "utm_y":
            float(
                utm_y
            ),

        "cell_x":
            int(
                cell_x
            ),

        "cell_y":
            int(
                cell_y
            ),

        "cell_size":
            cell_size,

        "occupied":
            occupied,

        "X364":
            X364.reshape(
                1,
                -1,
            ),

        "Xstructural":
            structural_features.reshape(
                1,
                -1,
            ),
    }

def predict_macro_probabilities(
    bundle: dict[str, Any],
    X364: np.ndarray,
):

    models = bundle[
        "macro_models"
    ]

    raw = np.column_stack(
        [

            models[
                macro_id
            ]
            .predict_proba(
                X364
            )[
                :,
                1
            ]

            for macro_id
            in range(
                1,
                5,
            )
        ]
    )

    return normalize_ovr(
        raw
    ).astype(
        np.float32
    )

def predict_a7_probability(
    bundle: dict[str, Any],
    X364: np.ndarray,
):

    model = bundle[
        "a7_model"
    ]

    raw_positive = (
        model
        .predict_proba(
            X364
        )[
            :,
            1
        ]
    )

    raw = np.column_stack(
        [
            1.0
            -
            raw_positive,

            raw_positive,
        ]
    )

    calibrated = (
        temperature_scale(
            raw,
            float(
                bundle[
                    "a7_temperature"
                ]
            ),
        )
    )

    return (
        calibrated[
            :,
            1
        ]
        .reshape(
            -1,
            1,
        )
        .astype(
            np.float32
        )
    )
def evaluate_ambiguity(
    probabilities: np.ndarray,
    predicted_class: int,
    ambiguity_policy: dict[str, Any],
):

    p = normalize_proba(
        probabilities
    )[0]

    n_classes = len(
        p
    )

    p_selected = float(
        p[
            predicted_class
        ]
    )

    order = np.argsort(
        -p
    )

    probability_top1_class = int(
        order[0]
    )

    probability_top2_class = int(
        order[1]
    )

    p1 = float(
        p[
            probability_top1_class
        ]
    )

    p2 = float(
        p[
            probability_top2_class
        ]
    )

    margin_top12 = float(
        p1
        -
        p2
    )

    entropy = -float(
        np.sum(
            p
            *
            np.log(
                np.clip(
                    p,
                    1e-15,
                    1.0,
                )
            )
        )
    )

    entropy_norm = float(
        entropy
        /
        np.log(
            n_classes
        )
    )

    agreement = bool(
        predicted_class
        ==
        probability_top1_class
    )

    policy = ambiguity_policy[
        "final_policy"
    ]

    p_threshold = float(
        policy[
            "p_threshold"
        ]
    )

    margin_threshold = float(
        policy[
            "margin_threshold"
        ]
    )

    entropy_threshold = float(
        policy[
            "entropy_threshold"
        ]
    )

    accepted = bool(
        p_selected
        >=
        p_threshold

        and

        margin_top12
        >=
        margin_threshold

        and

        entropy_norm
        <=
        entropy_threshold
    )

    return {

        "accepted":
            accepted,

        "ambiguous":
            not accepted,

        "policy_version":
            str(
                ambiguity_policy[
                    "policy_version"
                ]
            ),

        "p_selected":
            p_selected,

        "p1":
            p1,

        "p2":
            p2,

        "margin_top12":
            margin_top12,

        "entropy_norm":
            entropy_norm,

        "probability_top1_class":
            probability_top1_class,

        "probability_top2_class":
            probability_top2_class,

        "decision_agrees_with_probability_top1":
            agreement,

        "thresholds":
            {
                "p_selected_min":
                    p_threshold,

                "margin_min":
                    margin_threshold,

                "entropy_max":
                    entropy_threshold,
            },
    }


def predict_activity(
    lat: float,
    lon: float,
) -> dict[str, Any]:

    runtime = (
        get_runtime_artifacts()
    )

    bundle = runtime.bundle

    feature_data = (
        build_runtime_features(
            lat,
            lon,
        )
    )

    X364 = feature_data[
        "X364"
    ]

    Xstructural = (
        feature_data[
            "Xstructural"
        ]
    )

    p_macro = (
        predict_macro_probabilities(
            bundle,
            X364,
        )
    )

    p_a7 = (
        predict_a7_probability(
            bundle,
            X364,
        )
    )

    X422 = np.hstack(
        [
            X364,
            Xstructural,
            p_macro,
            p_a7,
        ]
    ).astype(
        np.float32
    )

    if X422.shape[
        1
    ] != 422:

        raise RuntimeError(
            "La matriz final no contiene "
            f"422 features: "
            f"{X422.shape}"
        )

    member_probabilities = []

    for model in bundle[
        "detail_models"
    ]:

        proba = normalize_proba(
            model.predict_proba(
                X422
            )
        )

        member_probabilities.append(
            proba
        )

    mean_raw = normalize_proba(
        np.mean(
            np.stack(
                member_probabilities,
                axis=0,
            ),
            axis=0,
        )
    )

    calibrated = (
        temperature_scale(
            mean_raw,
            float(
                bundle[
                    "detail_temperature"
                ]
            ),
        )
    )

    multipliers = np.asarray(
        bundle[
            "decision_multipliers"
        ],
        dtype=float,
    )

    decision_scores = (
        calibrated
        *
        multipliers[
            None,
            :
        ]
    )

    predicted_class = int(
        np.argmax(
            decision_scores[
                0
            ]
        )
    )

    decision_scores_normalized = (
        decision_scores
        /
        decision_scores.sum(
            axis=1,
            keepdims=True,
        )
    )

    output_labels = [

        int(
            value
        )

        for value
        in bundle[
            "output_labels"
        ]
    ]

    predicted_activity_id = (
        output_labels[
            predicted_class
        ]
    )

    ambiguity = evaluate_ambiguity(
        calibrated,
        predicted_class,
        runtime.ambiguity_policy,
    )

    top3_indices = np.argsort(
        -calibrated[
            0
        ]
    )[
        :3
    ]

    top3 = []

    for class_index in top3_indices:

        class_index = int(
            class_index
        )

        top3.append(
            {
                "operational_class":
                    class_index,

                "activity_id":
                    int(
                        output_labels[
                            class_index
                        ]
                    ),

                "probability":
                    float(
                        calibrated[
                            0,
                            class_index
                        ]
                    ),

                "decision_score":
                    float(
                        decision_scores_normalized[
                            0,
                            class_index
                        ]
                    ),
            }
        )

    return {

        "model_version":
            str(
                bundle[
                    "bundle_version"
                ]
            ),

        "cell_x":
            feature_data[
                "cell_x"
            ],

        "cell_y":
            feature_data[
                "cell_y"
            ],

        "cell_size":
            feature_data[
                "cell_size"
            ],

        "occupied":
            feature_data[
                "occupied"
            ],

        "utm_x":
            feature_data[
                "utm_x"
            ],

        "utm_y":
            feature_data[
                "utm_y"
            ],

        "operational_class":
            predicted_class,

        "activity_id":
            predicted_activity_id,

        "probability":
            float(
                calibrated[
                    0,
                    predicted_class
                ]
            ),

        "decision_score":
            float(
                decision_scores_normalized[
                    0,
                    predicted_class
                ]
            ),
        "ambiguity":
            ambiguity,
        "top3":
            top3,

        "p_macro":
            [
                float(
                    value
                )
                for value
                in p_macro[
                    0
                ]
            ],

        "p_a7":
            float(
                p_a7[
                    0,
                    0
                ]
            ),

        "rare_activity_ids":
            [
                int(
                    value
                )
                for value
                in bundle[
                    "rare_non_commerce"
                ]
            ],
    }