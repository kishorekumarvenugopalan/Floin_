"""Historical event definitions used only by the validation workflow.

Kept apart from normal simulation inputs: a user simulation never reads these.
"""

CHENNAI_2015 = {
    "event_name": "chennai_2015_dec",
    "title": "Chennai floods, 30 Nov - 2 Dec 2015",
    # CHIRPS calendar days summed into the event rainfall raster. 1 Dec 2015 is the
    # extreme day; 30 Nov and 2 Dec are included because the observed inundation
    # reflects the multi-day event.
    "rainfall_days": ["20151130", "20151201", "20151202"],
    "rainfall_dataset": "rainfall_chirps_2015_event_30m",
    # Antecedent moisture: November 2015 was exceptionally wet in Chennai, so the
    # validation is run for both AMC II (average) and AMC III (wet) and both are reported.
    "antecedent_conditions": ["II", "III"],
    "extent_references": ["flood_2015_inundation"],
    # Independent map compared with the same observations, to show how well an external
    # reference product agrees with them (context for FLOIN's scores, not a target).
    "benchmark_reference": "gcc_design_flood_100y",
    "street_reference": "flood_2015_flooded_streets",
    "depth_point_reference": "flood_2015_gcc_hotspots",
    "point_reference": "flood_2015_gcc_stagnation",
}

EVENTS = {CHENNAI_2015["event_name"]: CHENNAI_2015}
