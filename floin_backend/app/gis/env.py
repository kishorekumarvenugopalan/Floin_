import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_GDAL_VARIABLES = ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA")


def isolate_gdal_environment() -> None:
    """Drop GDAL/PROJ data paths that point outside this Python environment.

    rasterio and pyproj wheels ship their own PROJ and GDAL data. A system-wide
    PROJ_LIB from another product (e.g. PostGIS) overrides that and breaks CRS
    handling, so such values are removed from this process only, with a warning.
    """
    prefix = Path(sys.prefix).resolve()
    for name in _GDAL_VARIABLES:
        value = os.environ.get(name)
        if not value:
            continue
        try:
            inside = prefix in Path(value).resolve().parents
        except OSError:
            inside = False
        if not inside:
            os.environ.pop(name)
            log.warning("Ignoring %s=%s (outside this Python environment); using bundled data", name, value)
