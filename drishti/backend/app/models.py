import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float, JSON
from geoalchemy2 import Geometry

from .database import Base


def gen_uuid():
    return str(uuid.uuid4())


class Job(Base):
    """One uploaded orthophoto + its processing status."""

    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    status = Column(String, default="uploaded")  # uploaded -> processing -> done -> failed
    bounds = Column(JSON, nullable=True)  # [minx, miny, maxx, maxy] in EPSG:4326
    crs = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Feature(Base):
    """A single extracted GIS feature (building, road, tree, etc.)."""

    __tablename__ = "features"

    id = Column(String, primary_key=True, default=gen_uuid)
    job_id = Column(String, nullable=False, index=True)
    feature_type = Column(String, nullable=False)  # building | road | tree | water | farm | lulc
    confidence = Column(Float, nullable=False)
    geom = Column(Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=False)
    properties = Column(JSON, nullable=True)
