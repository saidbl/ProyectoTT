from __future__ import annotations

import pytest

from conftest import (
    request_prediction,
)


def test_clear_point_returns_ok(
    clear_api_result,
):
    assert (
        clear_api_result[
            "status"
        ]
        ==
        "ok"
    )


def test_clear_point_is_expected_cell(
    clear_api_result,
):
    cell = clear_api_result[
        "cell"
    ]

    assert (
        int(
            cell[
                "x"
            ]
        )
        ==
        1620
    )

    assert (
        int(
            cell[
                "y"
            ]
        )
        ==
        7162
    )

    assert (
        int(
            cell[
                "size_m"
            ]
        )
        ==
        300
    )


def test_outside_cdmx_is_rejected(
    outside_point,
):
    status_code, data = (
        request_prediction(
            outside_point
        )
    )

    assert status_code == 200

    assert (
        data[
            "status"
        ]
        ==
        "outside_cdmx"
    )


def test_api_clear_case_is_not_ambiguous(
    clear_api_result,
):
    ambiguity = (
        clear_api_result[
            "ambiguity"
        ]
    )

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


def test_api_known_ambiguous_case(
    ambiguous_api_result,
):
    ambiguity = (
        ambiguous_api_result[
            "ambiguity"
        ]
    )

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


def test_api_same_coordinate_is_deterministic(
    clear_point,
    clear_api_result,
):
    status_code, second = (
        request_prediction(
            clear_point
        )
    )

    assert status_code == 200

    first_prediction = (
        clear_api_result[
            "prediction"
        ]
    )

    second_prediction = (
        second[
            "prediction"
        ]
    )

    assert (
        first_prediction[
            "operational_class"
        ]
        ==
        second_prediction[
            "operational_class"
        ]
    )

    assert (
        first_prediction[
            "activity_id"
        ]
        ==
        second_prediction[
            "activity_id"
        ]
    )

    assert float(
        first_prediction[
            "probability"
        ]
    ) == pytest.approx(
        float(
            second_prediction[
                "probability"
            ]
        ),
        abs=1e-12,
    )

    assert (
        clear_api_result[
            "top3"
        ]
        ==
        second[
            "top3"
        ]
    )

    assert (
        clear_api_result[
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