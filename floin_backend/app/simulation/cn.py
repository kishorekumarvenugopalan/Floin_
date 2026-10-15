import numpy as np

HSG_A, HSG_B, HSG_C, HSG_D = 1, 2, 3, 4
HSG_NODATA = 0
HSG_LABELS = {HSG_A: "A", HSG_B: "B", HSG_C: "C", HSG_D: "D"}

WORLDCOVER_CLASSES = {
    10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up",
    60: "Bare / sparse vegetation", 70: "Snow and ice", 80: "Permanent water bodies",
    90: "Herbaceous wetland", 95: "Mangroves", 100: "Moss and lichen",
}

TR55_LOOKUP = {
    10: ((30, 55, 70, 77), "TR-55 2-2c Woods, good condition"),
    20: ((35, 56, 70, 77), "TR-55 2-2c Brush-weed-grass mixture, fair condition"),
    30: ((49, 69, 79, 84), "TR-55 2-2c Pasture/grassland/range, fair condition"),
    40: ((67, 78, 85, 89), "TR-55 2-2b Row crops, straight row, good condition"),
    50: ((98, 98, 98, 98), "TR-55 2-2a Impervious areas: paved parking lots, roofs, driveways"),
    60: ((77, 86, 91, 94), "TR-55 2-2b Fallow, bare soil"),
    80: ((100, 100, 100, 100), "Open water: all rainfall becomes direct runoff (S = 0)"),
    90: ((98, 98, 98, 98), "Assumption: saturated wetland surface treated like impervious (no TR-55 class)"),
    95: ((98, 98, 98, 98), "Assumption: tidal mangrove surface treated like impervious (no TR-55 class)"),
}

SOIL_INDEPENDENT = {50, 80, 90, 95}

TEXTURE_HSG = {
    "sand": HSG_A,
    "loamy sand": HSG_B, "sandy loam": HSG_B,
    "loam": HSG_C, "silt loam": HSG_C, "silt": HSG_C,
    "sandy clay loam": HSG_C, "clay loam": HSG_C, "silty clay loam": HSG_C,
    "sandy clay": HSG_D, "silty clay": HSG_D, "clay": HSG_D,
}
TEXTURE_CODES = {name: i + 1 for i, name in enumerate(TEXTURE_HSG)}


def usda_texture_class(sand: np.ndarray, clay: np.ndarray) -> np.ndarray:
    """USDA texture triangle. Inputs in percent; silt = 100 - sand - clay.
    Returns integer codes (TEXTURE_CODES), 0 where input is missing."""
    sand = np.asarray(sand, dtype="float64")
    clay = np.asarray(clay, dtype="float64")
    silt = 100.0 - sand - clay
    out = np.zeros(sand.shape, dtype="uint8")
    valid = np.isfinite(sand) & np.isfinite(clay)
    rules = [
        ("sand", silt + 1.5 * clay < 15),
        ("loamy sand", (silt + 1.5 * clay >= 15) & (silt + 2 * clay < 30)),
        ("sandy loam", ((clay >= 7) & (clay < 20) & (sand > 52) & (silt + 2 * clay >= 30))
         | ((clay < 7) & (silt < 50) & (silt + 2 * clay >= 30))),
        ("loam", (clay >= 7) & (clay < 27) & (silt >= 28) & (silt < 50) & (sand <= 52)),
        ("silt loam", ((silt >= 50) & (clay >= 12) & (clay < 27)) | ((silt >= 50) & (silt < 80) & (clay < 12))),
        ("silt", (silt >= 80) & (clay < 12)),
        ("sandy clay loam", (clay >= 20) & (clay < 35) & (silt < 28) & (sand > 45)),
        ("clay loam", (clay >= 27) & (clay < 40) & (sand > 20) & (sand <= 45)),
        ("silty clay loam", (clay >= 27) & (clay < 40) & (sand <= 20)),
        ("sandy clay", (clay >= 35) & (sand > 45)),
        ("silty clay", (clay >= 40) & (silt >= 40)),
        ("clay", (clay >= 40) & (sand <= 45) & (silt < 40)),
    ]
    for name, condition in rules:
        out[valid & condition & (out == 0)] = TEXTURE_CODES[name]
    return out


def hsg_from_texture(texture_codes: np.ndarray) -> np.ndarray:
    lookup = np.zeros(max(TEXTURE_CODES.values()) + 1, dtype="uint8")
    for name, code in TEXTURE_CODES.items():
        lookup[code] = TEXTURE_HSG[name]
    return lookup[texture_codes]


def most_restrictive_hsg(*layers: np.ndarray) -> np.ndarray:
    stacked = np.stack(layers)
    out = stacked.max(axis=0)
    out[(stacked == HSG_NODATA).any(axis=0)] = HSG_NODATA
    return out


def curve_number(landcover: np.ndarray, hsg: np.ndarray) -> tuple[np.ndarray, dict]:
    cn = np.full(landcover.shape, np.nan, dtype="float32")
    report = {"classes": {}, "soil_missing_pixels": 0, "unmapped_pixels": 0}
    for cls, (values, source) in TR55_LOOKUP.items():
        mask = landcover == cls
        if not mask.any():
            continue
        if cls in SOIL_INDEPENDENT:
            cn[mask] = values[0]
        else:
            for group in (HSG_A, HSG_B, HSG_C, HSG_D):
                cn[mask & (hsg == group)] = values[group - 1]
            report["soil_missing_pixels"] += int((mask & (hsg == HSG_NODATA)).sum())
        report["classes"][str(cls)] = {"name": WORLDCOVER_CLASSES[cls], "pixels": int(mask.sum()), "source": source}
    known = np.isin(landcover, list(TR55_LOOKUP)) | (landcover == 0)
    report["unmapped_pixels"] = int((~known).sum())
    return cn, report


def adjust_amc(cn_ii: np.ndarray, condition: str) -> np.ndarray:
    cn_ii = np.asarray(cn_ii, dtype="float64")
    if condition == "II":
        return cn_ii.copy()
    if condition == "I":
        return 4.2 * cn_ii / (10.0 - 0.058 * cn_ii)
    if condition == "III":
        return np.minimum(23.0 * cn_ii / (10.0 + 0.13 * cn_ii), 100.0)
    raise ValueError(f"antecedent moisture condition must be I, II or III, not {condition!r}")
