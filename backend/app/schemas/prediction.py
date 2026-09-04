from pydantic import (
    BaseModel,
    Field,
)


class PredictionRequest(
    BaseModel
):

    lat: float = Field(
        ge=-90,
        le=90,
    )

    lon: float = Field(
        ge=-180,
        le=180,
    )

class PredictionCoordinate(
    BaseModel
):

    lat: float

    lon: float
class PredictionCell(
    BaseModel
):

    x: int

    y: int

    size_m: int

    occupied: bool

    polygon: list[
        PredictionCoordinate
    ] = Field(
        default_factory=list
    )


class PredictionAlternative(
    BaseModel
):

    operational_class: int

    activity_id: int | None = None

    scian: str | None = None

    activity: str

    probability: float = Field(
        ge=0,
        le=1,
    )

    decision_score: float = Field(
        ge=0,
        le=1,
    )

    grouped: bool = False

    included_activity_ids: list[int] = Field(
        default_factory=list
    )


class AmbiguityThresholds(
    BaseModel
):

    p_selected_min: float

    margin_min: float

    entropy_max: float


class PredictionAmbiguity(
    BaseModel
):

    accepted: bool

    ambiguous: bool

    policy_version: str

    p_selected: float

    p1: float

    p2: float

    margin_top12: float

    entropy_norm: float

    probability_top1_class: int

    probability_top2_class: int

    decision_agrees_with_probability_top1: bool

    thresholds: AmbiguityThresholds


class PredictionResponse(
    BaseModel
):

    status: str

    message: str

    lat: float

    lon: float

    nearby_units: int = 0

    dominant_activity: str | None = None
    confidence: float | None = None

    model_version: str | None = None

    cell: PredictionCell | None = None

    prediction: PredictionAlternative | None = None

    ambiguity: PredictionAmbiguity | None = None

    top3: list[
        PredictionAlternative
    ] = Field(
        default_factory=list
    )