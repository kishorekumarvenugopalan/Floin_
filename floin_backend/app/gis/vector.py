import gzip
import json
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box
from shapely.ops import linemerge, polygonize, unary_union

from app.core.errors import DataValidationError

POLYGONAL = "MultiPolygon"
LINEAR = "MultiLineString"


def read_vector(path: Path) -> gpd.GeoDataFrame:
    """Read a vector file. GeoJSON without a crs member is WGS 84 by definition (RFC 7946)."""
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        if Path(path).suffix.lower() not in (".geojson", ".json"):
            raise DataValidationError(f"{Path(path).name} has no CRS and is not GeoJSON; refusing to guess")
        gdf = gdf.set_crs(4326)
    return gdf


def coerce_geometry(geom, target: str):
    """Repair a geometry and keep only the parts matching the target type.

    target: "MultiPolygon", "MultiLineString" or None (keep any single type as-is, but
    pull polygons out of GeometryCollections produced by KML conversion).
    Returns None when nothing usable remains.
    """
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
    parts = shapely.get_parts(geom)
    if target is None:
        if geom.geom_type != "GeometryCollection":
            return geom
        polys = [p for p in _flatten(parts) if p.geom_type == "Polygon"]
        return MultiPolygon(polys) if polys else None
    if target == POLYGONAL:
        polys = [p for p in _flatten(parts) if p.geom_type == "Polygon" and p.area > 0]
        return MultiPolygon(polys) if polys else None
    if target == LINEAR:
        lines = [p for p in _flatten(parts) if p.geom_type == "LineString" and p.length > 0]
        return MultiLineString(lines) if lines else None
    raise ValueError(target)


def _flatten(parts):
    for part in parts:
        if part.geom_type.startswith("Multi") or part.geom_type == "GeometryCollection":
            yield from _flatten(shapely.get_parts(part))
        else:
            yield part


def model_area_box(bounds_wgs84, crs: str) -> Polygon:
    return gpd.GeoSeries([box(*bounds_wgs84)], crs=4326).to_crs(crs).iloc[0]


# ------------------------------------------------------------------ OpenStreetMap

def read_osm_extract(path: Path, kind: str) -> gpd.GeoDataFrame:
    """Convert an Overpass `out geom` extract to a GeoDataFrame (EPSG:4326).

    kind "line": ways -> LineString.  kind "polygon": closed ways and multipolygon
    relations -> Polygon/MultiPolygon. Elements that cannot form valid geometry are dropped.
    """
    with gzip.open(path, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    records, geoms = [], []
    for el in payload["elements"]:
        geom = _osm_geometry(el, kind)
        if geom is None:
            continue
        records.append({"source_id": f"{el['type']}/{el['id']}", "tags": el.get("tags", {})})
        geoms.append(geom)
    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs=4326)
    gdf.attrs["osm_base"] = payload.get("osm_base")
    return gdf


def _coords(way_geometry):
    return [(p["lon"], p["lat"]) for p in way_geometry if p is not None]


def _osm_geometry(el, kind):
    if el["type"] == "way":
        coords = _coords(el.get("geometry", []))
        if kind == "line":
            return LineString(coords) if len(coords) >= 2 else None
        if len(coords) >= 4 and coords[0] == coords[-1]:
            poly = Polygon(coords)
            return poly if poly.is_valid else shapely.make_valid(poly)
        return None
    if el["type"] == "relation" and kind == "polygon":
        outer = [LineString(_coords(m["geometry"])) for m in el.get("members", [])
                 if m.get("role") == "outer" and len(m.get("geometry") or []) >= 2]
        inner = [LineString(_coords(m["geometry"])) for m in el.get("members", [])
                 if m.get("role") == "inner" and len(m.get("geometry") or []) >= 2]
        if not outer:
            return None
        shell = unary_union(list(polygonize(linemerge(outer))))
        if shell.is_empty:
            return None
        if inner:
            holes = unary_union(list(polygonize(linemerge(inner))))
            shell = shell.difference(holes)
        return shell if not shell.is_empty else None
    return None
