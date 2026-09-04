from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

API_URL = os.getenv(
    "SAE_TEST_API_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

PREDICTION_URL = (
    f"{API_URL}/api/predicciones"
)

CLEAR_POINT = {
    "lat": 19.432600,
    "lon": -99.133200,
}

AMBIGUOUS_POINT = {
    "lat": 19.396969,
    "lon": -99.147064,
}

OUTSIDE_POINT = {
    "lat": 19.700000,
    "lon": -99.200000,
}


KNOWN_OTRAS_CELL = {
    "x": 1555,
    "y": 7097,
}


VALID_ACTIVITY_IDS = {
    7,
    5,
    6,
    12,
    15,
    16,
    18,
    19,
    -1,
}


VALID_OPERATIONAL_CLASSES = set(
    range(9)
)

def api_get(
    path: str,
    timeout: int = 30,
):
    url = (
        path
        if path.startswith("http")
        else f"{API_URL}{path}"
    )

    request = urllib.request.Request(
        url,
        method="GET",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            body = (
                response
                .read()
                .decode("utf-8")
            )

            return (
                response.status,
                json.loads(body),
            )

    except urllib.error.HTTPError as exc:
        body = (
            exc
            .read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        try:
            data = json.loads(body)
        except Exception:
            data = {
                "raw": body,
            }

        return (
            exc.code,
            data,
        )


def api_post_json(
    path: str,
    payload: dict,
    timeout: int = 60,
):
    url = (
        path
        if path.startswith("http")
        else f"{API_URL}{path}"
    )

    body = json.dumps(
        payload
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            content = (
                response
                .read()
                .decode("utf-8")
            )

            return (
                response.status,
                json.loads(content),
            )

    except urllib.error.HTTPError as exc:
        content = (
            exc
            .read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        try:
            data = json.loads(
                content
            )
        except Exception:
            data = {
                "raw": content,
            }

        return (
            exc.code,
            data,
        )


def request_prediction(
    point: dict,
):
    return api_post_json(
        "/api/predicciones",
        point,
    )


@pytest.fixture(
    scope="session"
)
def clear_point():
    return dict(
        CLEAR_POINT
    )


@pytest.fixture(
    scope="session"
)
def ambiguous_point():
    return dict(
        AMBIGUOUS_POINT
    )


@pytest.fixture(
    scope="session"
)
def outside_point():
    return dict(
        OUTSIDE_POINT
    )


@pytest.fixture(
    scope="session"
)
def clear_api_result(
    clear_point,
):
    status_code, data = (
        request_prediction(
            clear_point
        )
    )

    assert status_code == 200

    assert (
        data.get("status")
        ==
        "ok"
    )

    return data


@pytest.fixture(
    scope="session"
)
def ambiguous_api_result(
    ambiguous_point,
):
    status_code, data = (
        request_prediction(
            ambiguous_point
        )
    )

    assert status_code == 200

    assert (
        data.get("status")
        ==
        "ok"
    )

    return data