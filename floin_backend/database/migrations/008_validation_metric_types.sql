-- FLOIN 008: allow line and point detection metrics in validation results.
ALTER TABLE floin.validation_metrics DROP CONSTRAINT validation_metrics_metric_type_check;
ALTER TABLE floin.validation_metrics ADD CONSTRAINT validation_metrics_metric_type_check
    CHECK (metric_type IN ('extent', 'line_detection', 'point_detection', 'point_depth_class'));
