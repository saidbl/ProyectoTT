from __future__ import annotations

from conftest import (
    api_get,
)


def test_backend_openapi_available():
    """
    Comprueba que FastAPI esté levantado.
    """

    status_code, data = (
        api_get(
            "/openapi.json"
        )
    )

    assert status_code == 200

    assert isinstance(
        data,
        dict,
    )

    assert "openapi" in data

    assert "paths" in data


def test_prediction_endpoint_registered():
    """
    Comprueba que la ruta principal de predicción
    esté registrada en FastAPI.
    """

    status_code, data = (
        api_get(
            "/openapi.json"
        )
    )

    assert status_code == 200

    paths = data[
        "paths"
    ]

    assert (
        "/api/predicciones"
        in
        paths
    )

    assert (
        "post"
        in
        paths[
            "/api/predicciones"
        ]
    )