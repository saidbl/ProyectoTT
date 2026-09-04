from __future__ import annotations

import os
from pathlib import Path

import joblib
import numpy as np
import pytest

from pyproj import Transformer

from app.ml.inference import (
    build_runtime_features,
    predict_a7_probability,
    predict_activity,
    predict_macro_probabilities,
)

from conftest import (
    CLEAR_POINT,
    AMBIGUOUS_POINT,
    KNOWN_OTRAS_CELL,
    VALID_ACTIVITY_IDS,
    VALID_OPERATIONAL_CLASSES,
)

MODEL_BUNDLE_PATH = Path(
    os.getenv(
        "MODEL_BUNDLE_PATH",
        (
            "/app/models/final_422/"
            "sae_cdmx_activity_422.joblib"
        ),
    )
)


@pytest.fixture(
    scope="module"
)
def bundle():
    assert (
        MODEL_BUNDLE_PATH.exists()
    ), (
        "No se encontró el bundle del modelo en "
        f"{MODEL_BUNDLE_PATH}"
    )

    return joblib.load(
        MODEL_BUNDLE_PATH
    )


@pytest.fixture(
    scope="module"
)
def clear_features():
    return build_runtime_features(
        CLEAR_POINT["lat"],
        CLEAR_POINT["lon"],
    )

def test_model_bundle_contract_422(
    bundle,
):
    """
    Verifica que estamos cargando exactamente
    el modelo de 422 variables.
    """

    assert (
        int(
            bundle[
                "feature_count"
            ]
        )
        ==
        422
    )

    output_labels = [
        int(x)
        for x
        in bundle[
            "output_labels"
        ]
    ]

    assert output_labels == [
        7,
        5,
        6,
        12,
        15,
        16,
        18,
        19,
        -1,
    ]

    assert (
        len(
            bundle[
                "detail_models"
            ]
        )
        ==
        3
    )

def test_runtime_base_feature_dimensions(
    clear_features,
):
    """
    332 spatial
    + 32 center-safe
    = 364
    """

    X364 = np.asarray(
        clear_features[
            "X364"
        ]
    )

    assert X364.shape == (
        1,
        364,
    )


def test_runtime_structural_feature_dimensions(
    clear_features,
):
    """
    53 variables estructurales.
    """

    Xstructural = np.asarray(
        clear_features[
            "Xstructural"
        ]
    )

    assert Xstructural.shape == (
        1,
        53,
    )


def test_final_runtime_feature_count_is_422(
    bundle,
    clear_features,
):
    """
    Reconstruye la composición final:

    364 base
    + 53 structural
    + 4 macro
    + 1 P(A7)
    = 422
    """

    X364 = np.asarray(
        clear_features[
            "X364"
        ],
        dtype=np.float32,
    )

    Xstructural = np.asarray(
        clear_features[
            "Xstructural"
        ],
        dtype=np.float32,
    )

    macro_probabilities = (
        predict_macro_probabilities(
            bundle,
            X364,
        )
    )

    a7_probability = (
        predict_a7_probability(
            bundle,
            X364,
        )
    )

    assert (
        macro_probabilities.shape
        ==
        (
            1,
            4,
        )
    )

    assert (
        a7_probability.shape
        ==
        (
            1,
            1,
        )
    )

    X422 = np.hstack(
        [
            X364,
            Xstructural,
            macro_probabilities,
            a7_probability,
        ]
    )

    assert X422.shape == (
        1,
        422,
    )

    assert (
        np.isfinite(
            X422
        )
        .all()
    )

def test_known_coordinate_maps_to_expected_cell(
    clear_features,
):
    """
    El Zócalo/centro utilizado durante las
    pruebas debe conservar la misma celda.
    """

    assert (
        int(
            clear_features[
                "cell_x"
            ]
        )
        ==
        1620
    )

    assert (
        int(
            clear_features[
                "cell_y"
            ]
        )
        ==
        7162
    )

    assert (
        int(
            clear_features[
                "cell_size"
            ]
        )
        ==
        300
    )


def test_cell_polygon_has_four_vertices(
    clear_features,
):
    polygon = (
        clear_features[
            "cell_polygon"
        ]
    )

    assert isinstance(
        polygon,
        list,
    )

    assert len(
        polygon
    ) == 4

    for point in polygon:
        assert "lat" in point
        assert "lon" in point

        assert np.isfinite(
            float(
                point[
                    "lat"
                ]
            )
        )

        assert np.isfinite(
            float(
                point[
                    "lon"
                ]
            )
        )


def test_cell_polygon_is_really_300_by_300_meters(
    clear_features,
):
    """
    Convierte nuevamente el polígono mostrado
    por Leaflet a UTM y verifica que sus cuatro
    lados sean de aproximadamente 300 metros.
    """

    polygon = (
        clear_features[
            "cell_polygon"
        ]
    )

    transformer = (
        Transformer.from_crs(
            "EPSG:4326",
            "EPSG:32614",
            always_xy=True,
        )
    )

    points_utm = []

    for point in polygon:
        x, y = (
            transformer.transform(
                float(
                    point[
                        "lon"
                    ]
                ),
                float(
                    point[
                        "lat"
                    ]
                ),
            )
        )

        points_utm.append(
            (
                float(x),
                float(y),
            )
        )

    sides = []

    for index in range(4):
        x1, y1 = (
            points_utm[
                index
            ]
        )

        x2, y2 = (
            points_utm[
                (
                    index
                    +
                    1
                )
                %
                4
            ]
        )

        distance = float(
            np.hypot(
                x2 - x1,
                y2 - y1,
            )
        )

        sides.append(
            distance
        )

    for side in sides:
        assert side == pytest.approx(
            300.0,
            abs=0.10,
        )

def test_prediction_returns_valid_class():
    result = predict_activity(
        CLEAR_POINT["lat"],
        CLEAR_POINT["lon"],
    )

    assert (
        int(
            result[
                "operational_class"
            ]
        )
        in
        VALID_OPERATIONAL_CLASSES
    )

    assert (
        int(
            result[
                "activity_id"
            ]
        )
        in
        VALID_ACTIVITY_IDS
    )


def test_prediction_probability_is_valid():
    result = predict_activity(
        CLEAR_POINT["lat"],
        CLEAR_POINT["lon"],
    )

    probability = float(
        result[
            "probability"
        ]
    )

    assert (
        0.0
        <=
        probability
        <=
        1.0
    )


def test_prediction_has_exactly_three_probability_alternatives():
    result = predict_activity(
        CLEAR_POINT["lat"],
        CLEAR_POINT["lon"],
    )

    top3 = result[
        "top3"
    ]

    assert len(
        top3
    ) == 3

    probabilities = [
        float(
            item[
                "probability"
            ]
        )
        for item
        in top3
    ]

    assert all(
        0.0
        <=
        probability
        <=
        1.0
        for probability
        in probabilities
    )

    assert (
        probabilities
        ==
        sorted(
            probabilities,
            reverse=True,
        )
    )

def test_same_coordinate_produces_same_result():
    """
    Como el bundle está congelado, ejecutar dos
    veces la misma coordenada debe dar la misma
    predicción.
    """

    first = predict_activity(
        CLEAR_POINT["lat"],
        CLEAR_POINT["lon"],
    )

    second = predict_activity(
        CLEAR_POINT["lat"],
        CLEAR_POINT["lon"],
    )

    assert (
        first[
            "operational_class"
        ]
        ==
        second[
            "operational_class"
        ]
    )

    assert (
        first[
            "activity_id"
        ]
        ==
        second[
            "activity_id"
        ]
    )

    assert float(
        first[
            "probability"
        ]
    ) == pytest.approx(
        float(
            second[
                "probability"
            ]
        ),
        abs=1e-12,
    )

    assert (
        first[
            "top3"
        ]
        ==
        second[
            "top3"
        ]
    )

    assert (
        first[
            "ambiguity"
        ][
            "ambiguous"
        ]
        ==
        second[
            "ambiguity"
        ][
            "ambiguous"
        ]
    )
def test_known_clear_case_is_accepted():
    result = predict_activity(
        CLEAR_POINT["lat"],
        CLEAR_POINT["lon"],
    )

    ambiguity = result[
        "ambiguity"
    ]

    assert (
        ambiguity[
            "accepted"
        ]
        is True
    )

    assert (
        ambiguity[
            "ambiguous"
        ]
        is False
    )


def test_known_ambiguous_case_is_rejected_by_policy():
    result = predict_activity(
        AMBIGUOUS_POINT["lat"],
        AMBIGUOUS_POINT["lon"],
    )

    ambiguity = result[
        "ambiguity"
    ]

    assert (
        ambiguity[
            "accepted"
        ]
        is False
    )

    assert (
        ambiguity[
            "ambiguous"
        ]
        is True
    )
def test_otras_is_valid_class_not_ambiguity():
    """
    Durante la auditoría de integración esta celda
    produjo operational_class = 8 y actividad_id = -1
    con predicción aceptada.

    OTRAS es una clase agrupada legítima.
    No debe confundirse con una abstención.
    """

    cell_x = int(
        KNOWN_OTRAS_CELL[
            "x"
        ]
    )

    cell_y = int(
        KNOWN_OTRAS_CELL[
            "y"
        ]
    )

    cell_size = 300

    center_x = (
        cell_x
        *
        cell_size
        +
        cell_size
        /
        2
    )

    center_y = (
        cell_y
        *
        cell_size
        +
        cell_size
        /
        2
    )

    inverse = (
        Transformer.from_crs(
            "EPSG:32614",
            "EPSG:4326",
            always_xy=True,
        )
    )

    lon, lat = (
        inverse.transform(
            center_x,
            center_y,
        )
    )

    result = predict_activity(
        lat,
        lon,
    )

    assert (
        int(
            result[
                "operational_class"
            ]
        )
        ==
        8
    )

    assert (
        int(
            result[
                "activity_id"
            ]
        )
        ==
        -1
    )

    assert (
        result[
            "ambiguity"
        ][
            "ambiguous"
        ]
        is False
    )

    assert (
        result[
            "ambiguity"
        ][
            "accepted"
        ]
        is True
    )