"""Error types that map to clear API responses instead of stack traces."""


class FloinError(Exception):
    status_code = 500
    code = "floin_error"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details


class ConfigurationError(FloinError):
    status_code = 503
    code = "configuration_error"


class DatabaseUnavailableError(FloinError):
    status_code = 503
    code = "database_unavailable"


class DatasetMissingError(FloinError):
    """A dataset the model requires is not registered, not usable, or not retrievable."""
    status_code = 409
    code = "dataset_missing"


class DataValidationError(FloinError):
    """A dataset exists but fails a check (CRS, grid alignment, NoData, value range)."""
    status_code = 422
    code = "data_validation_error"


class StorageError(FloinError):
    status_code = 502
    code = "storage_error"


class SimulationError(FloinError):
    status_code = 500
    code = "simulation_error"


class NotFoundError(FloinError):
    status_code = 404
    code = "not_found"
