from __future__ import annotations

import math

from conftest import (
    VALID_ACTIVITY_IDS,
    VALID_OPERATIONAL_CLASSES,
)


def test_prediction_response_required_sections(
    clear_api_result,
):
    required = {
        "status",
        "message",
        "cell",
        "prediction",
        "top3",
        "ambiguity",
    }

    assert required.issubset(
        clear_api_result.keys()
    )


def test_prediction_cell_contract(
    clear_api_result,
):
    cell = clear_api_result[
        "cell"
    ]

    assert isinstance(
        cell[
            "x"
        ],
        int,
    )

    assert isinstance(
        cell[
            "y"
        ],
        int,
    )

    assert (
        cell[
            "size_m"
        ]
        ==
        300
    )

    assert isinstance(
        cell[
            "occupied"
        ],
        bool,
    )

    polygon = cell[
        "polygon"
    ]

    assert isinstance(
        polygon,
        list,
    )

    assert len(
        polygon
    ) == 4

    for point in polygon:
        assert {
            "lat",
            "lon",
        }.issubset(
            point.keys()
        )

        assert math.isfinite(
            float(
                point[
                    "lat"
                ]
            )
        )

        assert math.isfinite(
            float(
                point[
                    "lon"
                ]
            )
        )


def test_prediction_object_contract(
    clear_api_result,
):
    prediction = (
        clear_api_result[
            "prediction"
        ]
    )

    required = {
        "operational_class",
        "activity_id",
        "probability",
    }

    assert required.issubset(
        prediction.keys()
    )

    operational_class = int(
        prediction[
            "operational_class"
        ]
    )

    activity_id = int(
        prediction[
            "activity_id"
        ]
    )

    probability = float(
        prediction[
            "probability"
        ]
    )

    assert (
        operational_class
        in
        VALID_OPERATIONAL_CLASSES
    )

    assert (
        activity_id
        in
        VALID_ACTIVITY_IDS
    )

    assert (
        0.0
        <=
        probability
        <=
        1.0
    )


def test_top3_contract(
    clear_api_result,
):
    top3 = clear_api_result[
        "top3"
    ]

    assert isinstance(
        top3,
        list,
    )

    assert len(
        top3
    ) == 3

    probabilities = []

    for item in top3:
        required = {
            "operational_class",
            "activity_id",
            "probability",
        }

        assert required.issubset(
            item.keys()
        )

        assert (
            int(
                item[
                    "operational_class"
                ]
            )
            in
            VALID_OPERATIONAL_CLASSES
        )

        assert (
            int(
                item[
                    "activity_id"
                ]
            )
            in
            VALID_ACTIVITY_IDS
        )

        probability = float(
            item[
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

        probabilities.append(
            probability
        )

    assert (
        probabilities
        ==
        sorted(
            probabilities,
            reverse=True,
        )
    )

    assert (
        sum(
            probabilities
        )
        <=
        1.0000001
    )


def test_ambiguity_contract(
    clear_api_result,
):
    ambiguity = (
        clear_api_result[
            "ambiguity"
        ]
    )

    required = {
        "accepted",
        "ambiguous",
        "p_selected",
        "p1",
        "p2",
        "margin_top12",
        "entropy_norm",
    }

    assert required.issubset(
        ambiguity.keys()
    )

    assert isinstance(
        ambiguity[
            "accepted"
        ],
        bool,
    )

    assert isinstance(
        ambiguity[
            "ambiguous"
        ],
        bool,
    )

    assert (
        ambiguity[
            "accepted"
        ]
        is
        (
            not
            ambiguity[
                "ambiguous"
            ]
        )
    )

    for key in [
        "p_selected",
        "p1",
        "p2",
        "margin_top12",
        "entropy_norm",
    ]:
        value = float(
            ambiguity[
                key
            ]
        )

        assert math.isfinite(
            value
        )

        assert (
            0.0
            <=
            value
            <=
            1.0
        )


def test_top3_probabilities_are_not_decision_scores(
    clear_api_result,
):
    """
    Evita que en el futuro alguien cambie Top-3
    para ordenarlo por multiplicadores de decisión.

    Top-3 debe representar las probabilidades
    calibradas.
    """

    top3 = clear_api_result[
        "top3"
    ]

    probabilities = [
        float(
            item[
                "probability"
            ]
        )
        for item
        in top3
    ]

    assert probabilities == sorted(
        probabilities,
        reverse=True,
    )


def test_observed_context_and_prediction_are_separate(
    clear_api_result,
):
    """
    Verifica que el contexto DENUE observado
    se mantenga separado semánticamente de
    la predicción del modelo.

    En la API actual, nearby_units y
    dominant_activity están a nivel raíz.
    """


    assert (
        "nearby_units"
        in
        clear_api_result
    )

    assert (
        "dominant_activity"
        in
        clear_api_result
    )

    nearby_units = (
        clear_api_result[
            "nearby_units"
        ]
    )

    dominant_activity = (
        clear_api_result[
            "dominant_activity"
        ]
    )

    assert isinstance(
        nearby_units,
        int,
    )

    assert (
        nearby_units
        >=
        0
    )

    assert (
        dominant_activity
        is None
        or
        isinstance(
            dominant_activity,
            str,
        )
    )

    assert (
        "prediction"
        in
        clear_api_result
    )

    prediction = (
        clear_api_result[
            "prediction"
        ]
    )

    assert isinstance(
        prediction,
        dict,
    )

    assert (
        "activity_id"
        in
        prediction
    )

    assert (
        "probability"
        in
        prediction
    )
    assert (
        "dominant_activity_probability"
        not in
        clear_api_result
    )

    assert (
        "nearby_probability"
        not in
        clear_api_result
    )
    probability = float(
        prediction[
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