-- FLOIN 005: historical validation runs and their metrics.

CREATE TABLE floin.validation_runs (
    id            text PRIMARY KEY,
    simulation_id text REFERENCES floin.simulation_runs(id) ON DELETE SET NULL,
    event_name    text NOT NULL,
    status        text NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    parameters    jsonb NOT NULL DEFAULT '{}'::jsonb,
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    completed_at  timestamptz
);

CREATE TABLE floin.validation_metrics (
    id                   bigserial PRIMARY KEY,
    validation_run_id    text NOT NULL REFERENCES floin.validation_runs(id) ON DELETE CASCADE,
    reference_dataset_id uuid NOT NULL REFERENCES floin.datasets(id),
    reference_name       text NOT NULL,
    comparison_domain    text NOT NULL,
    metric_type          text NOT NULL CHECK (metric_type IN ('extent', 'point_depth_class')),
    iou                  double precision,
    precision            double precision,
    recall               double precision,
    f1                   double precision,
    predicted_area_km2   double precision,
    observed_area_km2    double precision,
    area_difference_km2  double precision,
    details              jsonb NOT NULL DEFAULT '{}'::jsonb
);
