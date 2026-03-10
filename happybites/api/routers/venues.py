from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from happybites.api.deps import get_db
from happybites.db.models import Deal, Venue
from happybites.schemas.api import CityResponse, VenueDetailResponse

router = APIRouter()


@router.get("/{venue_id}", response_model=VenueDetailResponse)
def get_venue(venue_id: int, db: Annotated[Session, Depends(get_db)]):
    venue = (
        db.query(Venue)
        .options(joinedload(Venue.city))
        .filter(Venue.id == venue_id, Venue.is_active == True)  # noqa: E712
        .first()
    )
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    deal_count = (
        db.query(func.count(Deal.id))
        .filter(Deal.venue_id == venue_id, Deal.is_active == True)  # noqa: E712
        .scalar()
    ) or 0

    city = CityResponse.model_validate(venue.city) if venue.city else None

    return VenueDetailResponse(
        id=venue.id,
        name=venue.name,
        slug=venue.slug,
        city_id=venue.city_id,
        address=venue.address,
        lat=venue.lat,
        lon=venue.lon,
        category=venue.category,
        phone=venue.phone,
        website=venue.website,
        image_url=venue.image_url,
        confidence=venue.confidence,
        is_active=venue.is_active,
        city=city,
        deal_count=deal_count,
    )
