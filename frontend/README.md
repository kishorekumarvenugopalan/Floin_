# FLOIN frontend

React (JavaScript) + Vite app for FLOIN, the Chennai flood simulation backend. It has two modules:

- **Simulation workspace** (`/simulation`, the default page). A left panel holds the location, the simulation inputs and the results. The rest of the screen is an interactive 3D terrain map of Chennai.
- **Simulation history** (`/history`). Runs stored by the backend: view their details or reopen them in the workspace.

Everything shown comes from the FastAPI backend, from OpenStreetMap tiles or from Nominatim place search. The frontend computes no simulation results of its own.

## Run

Requirements: Node.js 20+ and npm, plus the FLOIN backend running (default `http://127.0.0.1:8000`).

```bash
cd frontend
npm install
copy .env.example .env      # macOS/Linux: cp .env.example .env
npm run dev                 # http://localhost:5173
```

Backend, from `floin_backend` with its virtual environment active:

```bash
uvicorn app.main:app --port 8000
```

Build: `npm run build` (output in `dist/`). Lint: `npm run lint`.

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | FLOIN backend base URL (no trailing slash) |

The frontend uses no keys or credentials. Never put database passwords or Supabase service-role keys in a `VITE_` variable.
The backend allows CORS from `http://localhost:5173` and `http://127.0.0.1:5173`.

## Workspace

**Left panel**

1. **Location**
   - **Search**:
     - GCC zones and wards: real polygons from the backend layer `wards_gcc`.
     - OpenStreetMap places via Nominatim. A place that OSM stores only as a point uses its containing GCC ward, labelled as a stand-in.
   - **Area details**: area, zone and wards, elevation range, and counts of rivers, drains, roads and buildings from the database.
   - **Clicking the map** selects a point and shows:
     - its coordinates (lat/lon and UTM 44N);
     - the ground elevation (90 m block mean);
     - the containing GCC ward;
     - the database features within 40 m (roads, railways, rivers, drains, water bodies, buildings) with their stored attributes and distance.
2. **Simulation inputs** match the backend `SimulationRequest` exactly:
   - Rainfall in mm (or a registered rainfall grid), duration in h, antecedent moisture.
   - Under "Advanced": Ia ratio, minimum flood depth and depth class breaks.
   - Validation follows the backend limits.
   - There is no location or curve-number input, because the API has none. CN is derived from land cover and soil, and every run covers the whole 1,306 km² model area.
3. **Simulation results** for the current run:
   - Live progress (polled every 4 s).
   - Values at the selected location:
     - exact ward figures from the stored ward summary;
     - for a boundary, an estimate from 90 m blocks of the depth raster;
     - for a clicked point, the value of that block.
   - Inputs used, the SCS-CN runoff estimate, the flood-screening figures and the exposure counts.
   - The model's limitations.

**Map**
- **Terrain**: Copernicus GLO-30 DEM from `/terrain/grid` (90 m blocks), draped with OpenStreetMap tiles. It can also be coloured by elevation or shown as relief, with optional contours.
- **Navigation**: drag to pan, right-drag to rotate or tilt, scroll to zoom.
- **Buttons**: reset camera, all of Chennai, full screen, and a layers panel.
- **Database layers**: wards, rivers, canal and drains, rail, roads and buildings.
  - Roads, buildings and minor drains load after zooming to a location.
  - Buildings are flat footprints, because the database has no heights.
- **Simulated output** of the current run:
  - flood-depth blocks (`/terrain-overlay`);
  - flood-extent polygons (`/flood`, about 15 MB, loaded once per run and only when zoomed in).

## History

- **Source**: `GET /simulations?limit=200` (stored in PostgreSQL by the backend).
- **Summary column**: read from each run's `/results`.
- **Expand a row** to see the full stored result, inputs and outputs.
- **Open** loads the run into the workspace. It restores the inputs and shows the stored results and map layers, and never starts a new run.
- **Location column**: the backend stores no location for a run. The location selected when a run was started from this browser is kept in `localStorage` and labelled "saved in this browser". Other runs show "whole model area".

## Endpoints used

`GET /api/v1/health` · `GET /datasets` · `GET /layers/{name}/geojson` · `GET /terrain/grid` · `POST /simulations` ·
`GET /simulations` · `GET /simulations/{id}` · `GET /simulations/{id}/results` · `GET /simulations/{id}/wards` ·
`GET /simulations/{id}/terrain-overlay` · `GET /simulations/{id}/flood`.
External: OpenStreetMap tiles (`tile.openstreetmap.org`, attribution shown) and Nominatim search (only the typed text is sent).

## Structure

```
src/
  pages/SimulationWorkspace.jsx    sidebar + map layout, run tracking, reopen from history
  pages/SimulationHistory.jsx      stored runs, details, open
  components/workspace/            LocationPanel, SimulationForm, RunResults, TerrainMap
  components/threeD/               Three.js scene (React Three Fiber), grid crop/drape helpers, OSM basemap texture
  components/search/               locality search combobox
  components/layout/AppShell.jsx   compact header, two-item navigation, backend status
  context/                         simulation runs + selected run; selected location
  services/                        API client, endpoint functions, caches, point feature query, run-location store
  hooks/, utils/                   request hooks, area statistics, formatting, geometry, UTM projection
```

## Limitations

- The terrain resolution is 90 m blocks, because the backend's grid endpoint has a maximum size of 640. The DEM is a surface model, so it includes buildings and trees.
- Flood output is a screening estimate (SCS-CN runoff, D8 routing, depression fill-and-spill). It is not a hydraulic inundation forecast.
- The simulation API has no location parameter, so runs cannot be limited to an area.
- The OSM tile server and Nominatim are free public services. They need internet access and may be slow or rate-limited.
