from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.prediction import PredictionRequest, PredictionResponse
from app.services.prediction_service import predict

router = APIRouter(tags=["predictions"])


@router.post("/predicciones", response_model=PredictionResponse)
def create_prediction(payload: PredictionRequest, db: Session = Depends(get_db)):
    return predict(db, payload.lat, payload.lon)
