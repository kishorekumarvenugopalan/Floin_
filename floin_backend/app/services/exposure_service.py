"""Exposure: PostGIS overlays of a simulation's flood polygons with reference layers.

All layers are in EPSG:32644, so ST_Length/ST_Area return metres / square metres.
A building is exposed when its footprint intersects a flood polygon; its exposure class
is the deepest class it touches. Road and rail exposure is the length inside flood polygons.
"""
import shapely
from sqlalchemy import text
from sqlalchemy.engine import Connection

SRID = 32644

# Elevated (bridge, viaduct, flyover) and underground (tunnel) segments are not reached by
# surface flooding; OSM tags them with bridge=* / tunnel=*. They are excluded from flooded
# length and reported separately.
AT_GRADE = ("coalesce({t}.attributes->>'bridge', 'no') = 'no' "
            "AND coalesce({t}.attributes->>'tunnel', 'no') = 'no'")


def store_flood_polygons(conn: Connection, sid: str, polygons) -> int:
    conn.execute(text("DELETE FROM floin.simulation_flood_polygons WHERE simulation_id = :sid"), {"sid": sid})
    cursor = conn.connection.dbapi_connection.cursor()
    with cursor.copy("COPY floin.simulation_flood_polygons (simulation_id, depth_class, geom) FROM STDIN") as copy:
        for geom, depth_class in polygons:
            copy.write_row([sid, depth_class, shapely.to_wkb(shapely.set_srid(geom, SRID), hex=True, include_srid=True)])
    invalid = conn.execute(text("""
        SELECT count(*) FROM floin.simulation_flood_polygons WHERE simulation_id = :sid AND NOT ST_IsValid(geom)
    """), {"sid": sid}).scalar_one()
    if invalid:
        conn.execute(text("""
            UPDATE floin.simulation_flood_polygons SET geom = ST_CollectionExtract(ST_MakeValid(geom), 3)
            WHERE simulation_id = :sid AND NOT ST_IsValid(geom) AND GeometryType(ST_CollectionExtract(ST_MakeValid(geom), 3)) = 'POLYGON'
        """), {"sid": sid})
    return len(polygons)


def compute_exposure(conn: Connection, sid: str, class_names: list[str]) -> dict:
    p = {"sid": sid}
    buildings = conn.execute(text("""
        WITH hit AS (
            SELECT b.id, max(f.depth_class) AS cls
            FROM floin.buildings b
            JOIN floin.simulation_flood_polygons f ON f.simulation_id = :sid AND ST_Intersects(b.geom, f.geom)
            GROUP BY b.id)
        SELECT cls, count(*) FROM hit GROUP BY cls ORDER BY cls
    """), p).all()
    total_buildings = conn.execute(text("SELECT count(*) FROM floin.buildings")).scalar_one()

    roads = conn.execute(text(f"""
        SELECT r.highway, sum(ST_Length(ST_Intersection(r.geom, f.geom))) AS m
        FROM floin.roads r
        JOIN floin.simulation_flood_polygons f ON f.simulation_id = :sid AND ST_Intersects(r.geom, f.geom)
        WHERE {AT_GRADE.format(t="r")}
        GROUP BY r.highway ORDER BY m DESC
    """), p).all()
    grade_separated_road_m = conn.execute(text(f"""
        SELECT coalesce(sum(ST_Length(ST_Intersection(r.geom, f.geom))), 0)
        FROM floin.roads r
        JOIN floin.simulation_flood_polygons f ON f.simulation_id = :sid AND ST_Intersects(r.geom, f.geom)
        WHERE NOT ({AT_GRADE.format(t="r")})
    """), p).scalar_one()
    total_road_m = conn.execute(text("SELECT coalesce(sum(ST_Length(geom)), 0) FROM floin.roads")).scalar_one()

    rail = conn.execute(text(f"""
        SELECT r.is_metro, ({AT_GRADE.format(t="r")}) AS at_grade, sum(ST_Length(ST_Intersection(r.geom, f.geom))) AS m
        FROM floin.railways r
        JOIN floin.simulation_flood_polygons f ON f.simulation_id = :sid AND ST_Intersects(r.geom, f.geom)
        GROUP BY 1, 2
    """), p).all()

    # Ward summary (GCC wards): flooded area, exposed buildings (by footprint point) and road length.
    conn.execute(text("DELETE FROM floin.simulation_ward_summary WHERE simulation_id = :sid"), p)
    conn.execute(text(f"""
        INSERT INTO floin.simulation_ward_summary (simulation_id, boundary_id, flooded_area_m2, buildings_affected, road_length_m)
        WITH area AS (
            SELECT w.id, sum(ST_Area(ST_Intersection(w.geom, f.geom))) AS m2
            FROM floin.admin_boundaries w
            JOIN floin.simulation_flood_polygons f ON f.simulation_id = :sid AND ST_Intersects(w.geom, f.geom)
            WHERE w.boundary_type = 'gcc_ward' GROUP BY w.id),
        bld AS (
            SELECT w.id, count(DISTINCT b.id) AS n
            FROM floin.buildings b
            JOIN floin.simulation_flood_polygons f ON f.simulation_id = :sid AND ST_Intersects(b.geom, f.geom)
            JOIN floin.admin_boundaries w ON w.boundary_type = 'gcc_ward' AND ST_Within(ST_PointOnSurface(b.geom), w.geom)
            GROUP BY w.id),
        rd AS (
            SELECT w.id, sum(ST_Length(ST_Intersection(ST_Intersection(r.geom, f.geom), w.geom))) AS m
            FROM floin.roads r
            JOIN floin.simulation_flood_polygons f ON f.simulation_id = :sid AND ST_Intersects(r.geom, f.geom)
            JOIN floin.admin_boundaries w ON w.boundary_type = 'gcc_ward' AND ST_Intersects(r.geom, w.geom)
            WHERE {AT_GRADE.format(t="r")}
            GROUP BY w.id)
        SELECT :sid, area.id, area.m2, coalesce(bld.n, 0), coalesce(rd.m, 0)
        FROM area LEFT JOIN bld USING (id) LEFT JOIN rd USING (id)
    """), p)
    wards = conn.execute(text("""
        SELECT w.code, w.zone, s.flooded_area_m2, s.buildings_affected, s.road_length_m,
               s.flooded_area_m2 / ST_Area(w.geom) AS flooded_share
        FROM floin.simulation_ward_summary s JOIN floin.admin_boundaries w ON w.id = s.boundary_id
        WHERE s.simulation_id = :sid ORDER BY s.flooded_area_m2 DESC
    """), p).mappings().all()

    by_class = {class_names[c - 1]: n for c, n in buildings}
    affected_buildings = sum(n for _, n in buildings)
    road_m = sum(m for _, m in roads)
    return {
        "buildings": {
            "affected": affected_buildings,
            "total_in_layer": total_buildings,
            "by_depth_class": by_class,
            "source": "OpenStreetMap building footprints",
        },
        "roads": {
            "affected_km": road_m / 1000.0,
            "total_km": float(total_road_m) / 1000.0,
            "by_highway_km": {h: m / 1000.0 for h, m in roads},
            "excluded_bridge_or_tunnel_km": float(grade_separated_road_m) / 1000.0,
            "note": "length of at-grade roads inside flood polygons; bridges/flyovers and tunnels excluded",
        },
        "railways": {
            "affected_rail_km": sum(m for metro, at, m in rail if not metro and at) / 1000.0,
            "affected_metro_km": sum(m for metro, at, m in rail if metro and at) / 1000.0,
            "excluded_bridge_or_tunnel_rail_km": sum(m for metro, at, m in rail if not metro and not at) / 1000.0,
            "excluded_bridge_or_tunnel_metro_km": sum(m for metro, at, m in rail if metro and not at) / 1000.0,
            "note": "track length (parallel tracks counted separately) at grade inside flood polygons",
        },
        "wards": {
            "wards_with_flooding": len(wards),
            "top_wards": [
                {"ward": w["code"], "zone": w["zone"], "flooded_area_km2": w["flooded_area_m2"] / 1e6,
                 "flooded_share": float(w["flooded_share"]), "buildings_affected": w["buildings_affected"],
                 "road_km": w["road_length_m"] / 1000.0}
                for w in wards[:15]
            ],
        },
        "critical_infrastructure": "not assessed: no verified hospital/school/emergency facility layer is loaded",
        "population": "not assessed: no usable population layer is loaded",
    }
