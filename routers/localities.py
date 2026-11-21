from fastapi import APIRouter, HTTPException, Response
from schemas import LocalitiesResponse
from services.rag_service import get_localities_cached
from config import SUPPORTED_CITIES

router = APIRouter(prefix="/localities", tags=["Localities"])


@router.get("/{city}", response_model=LocalitiesResponse)
def localities(city: str, response: Response):
    city = city.lower().strip()
    if city not in SUPPORTED_CITIES:
        raise HTTPException(
            status_code=404,
            detail=f"City '{city}' not supported. Options: {SUPPORTED_CITIES}"
        )
    items, cache_hit = get_localities_cached(city)
    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    return LocalitiesResponse(city=city, localities=items)