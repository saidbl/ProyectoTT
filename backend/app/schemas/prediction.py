from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PredictionResponse(BaseModel):
    status: str
    message: str
    lat: float
    lon: float
    nearby_units: int
    dominant_activity: str | None = None
    confidence: float | None = None
