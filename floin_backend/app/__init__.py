"""FLOIN backend package.

Importing ``app`` first isolates the GDAL/PROJ environment. On machines where a
PostgreSQL/PostGIS install sets PROJ_LIB or GDAL_DATA system-wide, rasterio and
pyproj would otherwise load an incompatible proj.db and fail every CRS lookup.
"""
from app.gis.env import isolate_gdal_environment

isolate_gdal_environment()
