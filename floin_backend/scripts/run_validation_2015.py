"""Run the December 2015 validation through the HTTP API and write docs/VALIDATION_2015.md.

Every number in the report comes from floin.validation_metrics rows written by the run.

Usage:  python scripts/run_validation_2015.py [--port 8766]
"""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: F401
import httpx

from app.core.config import BACKEND_ROOT
from scripts.run_e2e import start_server


def fmt(v, digits=3):
    return "" if v is None else f"{v:.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}/api/v1"
    server = start_server(args.port)
    try:
        accepted = httpx.post(f"{base}/validation/2015", json={"antecedent_conditions": ["II", "III"]}, timeout=30)
        accepted.raise_for_status()
        ids = accepted.json()["validation_ids"]
        print("validation runs:", ids)
        runs = {}
        started = time.time()
        while len(runs) < len(ids):
            for vid in ids:
                if vid in runs:
                    continue
                run = httpx.get(f"{base}/validation/{vid}", timeout=30).json()
                if run["status"] in ("completed", "failed"):
                    runs[vid] = run
                    print(vid, run["status"], run.get("error") or "")
            if time.time() - started > 3600:
                raise RuntimeError("validation did not finish within an hour")
            time.sleep(5)
    finally:
        server.terminate()
        server.wait(timeout=30)

    lines = [
        "# FLOIN validation: Chennai floods, December 2015", "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `scripts/run_validation_2015.py` "
        "through `POST /api/v1/validation/2015`. Rainfall: CHIRPS v2.0, 30 Nov - 2 Dec 2015 (194-300 mm on land).", "",
        "Comparison on the 30 m model grid, excluding open sea, permanent water bodies and mapped channels. "
        "Model accuracy (FLOIN vs observations) is reported separately from reference-map agreement "
        "(an independent map vs the same observations), which only describes observational uncertainty.", "",
    ]
    ok = True
    for vid, run in runs.items():
        amc = run["parameters"]["antecedent_moisture"]
        lines += [f"## AMC {amc}: `{vid}` (simulation `{run['simulation_id']}`), status {run['status']}", ""]
        if run["status"] != "completed":
            ok = False
            lines += [f"Error: {run.get('error')}", ""]
            continue
        lines += ["### Model accuracy: flood extent", "",
                  "| Reference | Domain | IoU | Precision | Recall | F1 | Predicted km2 | Observed km2 | Difference km2 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        extent = [m for m in run["metrics"] if m["metric_type"] == "extent"]
        for m in extent:
            lines.append(f"| {m['reference_name']} | {m['comparison_domain']} | {fmt(m['iou'])} | {fmt(m['precision'])} | "
                         f"{fmt(m['recall'])} | {fmt(m['f1'])} | {fmt(m['predicted_area_km2'], 1)} | "
                         f"{fmt(m['observed_area_km2'], 1)} | {fmt(m['area_difference_km2'], 1)} |")
        lines += ["", "Chance level (random map flooding the same area):", "",
                  "| Domain | Comparison km2 | Observed prevalence | Chance precision | Chance recall | Chance IoU |",
                  "|---|---|---|---|---|---|"]
        for m in extent:
            ch = m["details"].get("chance") or {}
            if ch:
                lines.append(f"| {m['comparison_domain']} | {fmt(ch['comparison_area_km2'], 1)} | {fmt(ch['observed_prevalence'])} | "
                             f"{fmt(ch['chance_precision'])} | {fmt(ch['chance_recall'])} | {fmt(ch['chance_iou'])} |")
        lines += ["", "### Context (not model accuracy)", "",
                  "| Comparison vs observed extent | Domain | IoU | Precision | Recall | F1 | Area km2 |", "|---|---|---|---|---|---|---|"]
        for m in extent:
            for key, label in (("baseline_ground_below_5m", "Naive baseline: ground < 5 m"),
                               ("benchmark_gcc_design_flood_100y", "Reference agreement: GCC 100-year map")):
                b = m["details"].get(key)
                if b:
                    lines.append(f"| {label} | {m['comparison_domain']} | {fmt(b['iou'])} | {fmt(b['precision'])} | "
                                 f"{fmt(b['recall'])} | {fmt(b['f1'])} | {fmt(b['predicted_area_km2'], 1)} |")
        lines += ["", "### Street and point evidence", "",
                  "Chance level for point detection = share of all evaluable GCC-ward cells that are wet within the same "
                  "3x3-cell window; a detection rate close to it shows no skill.", "",
                  "| Reference | Type | Detection rate | Chance level | Details |", "|---|---|---|---|---|"]
        for m in run["metrics"]:
            if m["metric_type"] == "extent":
                continue
            d = m["details"]
            if m["metric_type"] == "line_detection":
                detail = f"{d['inside_predicted_flood_km']:.1f} of {d['observed_length_km']:.1f} km of flooded streets inside predicted flood"
            elif m["metric_type"] == "point_depth_class":
                detail = (f"{d['detected_within_1_cell']} of {d['points_evaluated']} hotspots wet (3x3 cells); "
                          f"depth-class agreement {d['depth_class_agreement']:.3f}; by class: "
                          + ", ".join(f"{k}: {v['predicted_wet']}/{v['n']} wet, {v['depth_in_class']} in class"
                                      for k, v in d["by_observed_class"].items()))
            else:
                detail = f"{d['detected_within_1_cell']} of {d['points_evaluated']} points wet (3x3 cells)"
            lines.append(f"| {m['reference_name']} | {m['metric_type']} | {fmt(m['recall'])} | "
                         f"{fmt(d.get('chance_detection_rate_gcc_wards'))} | {detail} |")
        lines.append("")
    out = BACKEND_ROOT / "docs" / "VALIDATION_2015.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
