-- FLOIN 006: spatial (GIST) and lookup (btree) indexes.

-- Catalog
CREATE INDEX datasets_category_idx ON floin.datasets (category);
CREATE INDEX datasets_status_idx ON floin.datasets (status);
CREATE INDEX datasets_footprint_gix ON floin.datasets USING GIST (footprint);

-- Reference layers: spatial index plus dataset foreign key
CREATE INDEX admin_boundaries_geom_gix ON floin.admin_boundaries USING GIST (geom);
CREATE INDEX admin_boundaries_dataset_idx ON floin.admin_boundaries (dataset_id);
CREATE INDEX buildings_geom_gix ON floin.buildings USING GIST (geom);
CREATE INDEX buildings_dataset_idx ON floin.buildings (dataset_id);
CREATE INDEX roads_geom_gix ON floin.roads USING GIST (geom);
CREATE INDEX roads_dataset_idx ON floin.roads (dataset_id);
CREATE INDEX roads_highway_idx ON floin.roads (highway);
CREATE INDEX railways_geom_gix ON floin.railways USING GIST (geom);
CREATE INDEX railways_dataset_idx ON floin.railways (dataset_id);
CREATE INDEX rivers_geom_gix ON floin.rivers USING GIST (geom);
CREATE INDEX rivers_dataset_idx ON floin.rivers (dataset_id);
CREATE INDEX drainage_geom_gix ON floin.drainage USING GIST (geom);
CREATE INDEX drainage_dataset_idx ON floin.drainage (dataset_id);
CREATE INDEX water_bodies_geom_gix ON floin.water_bodies USING GIST (geom);
CREATE INDEX water_bodies_dataset_idx ON floin.water_bodies (dataset_id);
CREATE INDEX flood_references_geom_gix ON floin.flood_references USING GIST (geom);
CREATE INDEX flood_references_dataset_idx ON floin.flood_references (dataset_id);
CREATE INDEX flood_references_event_idx ON floin.flood_references (event_name);

-- Simulations
CREATE INDEX simulation_runs_created_idx ON floin.simulation_runs (created_at DESC);
CREATE INDEX simulation_runs_status_idx ON floin.simulation_runs (status);
CREATE INDEX simulation_inputs_dataset_idx ON floin.simulation_inputs (dataset_id);
CREATE INDEX simulation_outputs_sim_idx ON floin.simulation_outputs (simulation_id);
CREATE INDEX simulation_flood_polygons_sim_idx ON floin.simulation_flood_polygons (simulation_id);
CREATE INDEX simulation_flood_polygons_geom_gix ON floin.simulation_flood_polygons USING GIST (geom);
CREATE INDEX simulation_ward_summary_boundary_idx ON floin.simulation_ward_summary (boundary_id);

-- Validation
CREATE INDEX validation_runs_sim_idx ON floin.validation_runs (simulation_id);
CREATE INDEX validation_metrics_run_idx ON floin.validation_metrics (validation_run_id);
CREATE INDEX validation_metrics_dataset_idx ON floin.validation_metrics (reference_dataset_id);
