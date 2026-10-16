import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { Line, MapControls } from '@react-three/drei'
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { blockLonLat, KM, lineParts, polygonParts } from './sceneData'
import { polygonsOf } from '../../utils/geo'

// Scene palette. Elevation ramp low → high; depth ramp matches the backend depth legend.
export const ELEVATION_STOPS = ['#1F6F68', '#4E9A7A', '#9CC48A', '#E3DB9B', '#D1A46C', '#A0704A', '#6B4A35']
export const DEPTH_STOPS = ['#BAE6FD', '#38BDF8', '#2563EB', '#1E3A8A', '#172554']
export const DEPTH_MAX_M = 2
export const SEA_COLOUR = '#16324F'
export const PLAIN_COLOUR = '#CBD5E1'
export const EXTENT_COLOUR = '#E879F9'
export const BUILDING_COLOUR = '#64748B'
export const AREA_COLOUR = '#22D3EE'
export const PIN_COLOUR = '#F8FAFC'
const CLEAR_COLOUR = '#0B1220'

function ramp(t, stops, target) {
  const pos = Math.min(Math.max(t, 0), 1) * (stops.length - 1)
  const i = Math.min(Math.floor(pos), stops.length - 2)
  return target.set(stops[i]).lerp(new THREE.Color(stops[i + 1]), pos - i)
}

/**
 * Polling ResizeObserver stand-in for the canvas container. The native observer is used
 * as well; polling only covers embedded/hidden views where it never fires.
 */
class PollingResizeObserver {
  constructor(callback) {
    this.callback = callback
    this.targets = new Map()
    this.native = typeof window !== 'undefined' && window.ResizeObserver ? new window.ResizeObserver(callback) : null
    this.timer = setInterval(() => this.poll(), 400)
  }
  observe(el) {
    this.targets.set(el, '')
    this.native?.observe(el)
    this.poll()
  }
  unobserve(el) {
    this.targets.delete(el)
    this.native?.unobserve(el)
  }
  disconnect() {
    clearInterval(this.timer)
    this.targets.clear()
    this.native?.disconnect()
  }
  poll() {
    for (const [el, last] of this.targets) {
      const r = el.getBoundingClientRect()
      const key = `${r.width}x${r.height}@${r.left},${r.top}`
      if (key !== last) {
        this.targets.set(el, key)
        this.callback([{ target: el, contentRect: r }], this)
      }
    }
  }
}

// ---------------------------------------------------------------- terrain with contours

function useTerrainMaterial({ interval, contours, colourMode, basemap }) {
  const uniforms = useMemo(() => ({
    uInterval: { value: 5 },
    uContourOn: { value: 1 },
    uContourColour: { value: new THREE.Color('#1E293B') },
  }), [])
  const material = useMemo(() => {
    const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, metalness: 0, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 })
    m.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, uniforms)
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nattribute float elev;\nattribute float land;\nvarying float vElev;\nvarying float vLand;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvElev = elev;\nvLand = land;')
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', '#include <common>\nvarying float vElev;\nvarying float vLand;\nuniform float uInterval;\nuniform float uContourOn;\nuniform vec3 uContourColour;')
        .replace('#include <color_fragment>', `#include <color_fragment>
          if (uContourOn > 0.5 && vLand > 0.99) {
            float cv = vElev / uInterval;
            float dist = abs(fract(cv - 0.5) - 0.5);
            float w = max(fwidth(cv), 1e-4);
            float line = 1.0 - smoothstep(0.5 * w, 1.5 * w, dist);
            float major = step(abs(mod(floor(cv + 0.5), 5.0)), 0.5);
            diffuseColor.rgb = mix(diffuseColor.rgb, uContourColour, line * (0.35 + 0.35 * major));
          }`)
    }
    m.customProgramCacheKey = () => 'floin-terrain'
    return m
  }, [uniforms])
  const invalidate = useThree((s) => s.invalidate)
  useEffect(() => {
    uniforms.uInterval.value = interval
    uniforms.uContourOn.value = contours ? 1 : 0
    const map = colourMode === 'map' ? basemap?.texture || null : null
    if (material.map !== map) {
      material.map = map
      material.needsUpdate = true
    }
    invalidate()
  }, [uniforms, material, interval, contours, colourMode, basemap, invalidate])
  useEffect(() => () => material.dispose(), [material])
  return material
}

function Terrain({ grid, frame, exaggeration, colourMode, contours, interval, basemap, onPick }) {
  const useMap = colourMode === 'map' && !!basemap
  const geometry = useMemo(() => {
    const { width, height, values } = grid
    const n = width * height
    const positions = new Float32Array(n * 3)
    const colours = new Float32Array(n * 3)
    const uvs = useMap ? new Float32Array(n * 2) : null
    const elev = new Float32Array(n)
    const land = new Float32Array(n)
    const colour = new THREE.Color()
    const lonLat = useMap ? blockLonLat(grid) : null
    for (let r = 0; r < height; r++) {
      for (let c = 0; c < width; c++) {
        const i = r * width + c
        const v = values[r][c]
        positions[i * 3] = frame.toX(c)
        positions[i * 3 + 1] = ((v ?? 0) * exaggeration) / KM
        positions[i * 3 + 2] = frame.toZ(r)
        if (useMap) colour.set('#ffffff')
        else if (v === null) colour.set(SEA_COLOUR)
        else if (colourMode === 'elevation') ramp((v - frame.lo) / (frame.hi - frame.lo || 1), ELEVATION_STOPS, colour)
        else colour.set(PLAIN_COLOUR)
        colours.set([colour.r, colour.g, colour.b], i * 3)
        if (uvs) {
          const [lon, lat] = lonLat(r, c)
          uvs.set(basemap.uvOf(lon, lat), i * 2)
        }
        elev[i] = v ?? 0
        land[i] = v === null ? 0 : 1
      }
    }
    const index = []
    for (let r = 0; r < height - 1; r++) {
      for (let c = 0; c < width - 1; c++) {
        const a = r * width + c
        index.push(a, a + width, a + 1, a + 1, a + width, a + width + 1)
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    g.setAttribute('color', new THREE.BufferAttribute(colours, 3))
    if (uvs) g.setAttribute('uv', new THREE.BufferAttribute(uvs, 2))
    g.setAttribute('elev', new THREE.BufferAttribute(elev, 1))
    g.setAttribute('land', new THREE.BufferAttribute(land, 1))
    g.setIndex(index)
    g.computeVertexNormals()
    return g
  }, [grid, frame, exaggeration, colourMode, useMap, basemap])
  useEffect(() => () => geometry.dispose(), [geometry])
  const material = useTerrainMaterial({ interval, contours, colourMode, basemap: useMap ? basemap : null })

  const pick = (event) => {
    // A drag (pan/rotate) also ends with a click event; only a still click selects.
    if (event.delta > 4) return
    event.stopPropagation()
    const { x, z } = event.point
    const easting = x * KM + frame.cx
    const northing = -z * KM + frame.cy
    const [row, col] = frame.cellAt(easting, northing)
    onPick?.({ row, col, easting, northing, elevation: grid.values[row]?.[col] ?? null })
  }
  return <mesh geometry={geometry} material={material} onClick={pick} />
}

// ---------------------------------------------------------------- flood depth (block tiles)

/** One flat tile per block whose 30 m cells are at least half flooded, coloured by its deepest cell. */
function FloodDepth({ grid, overlay, frame, exaggeration, minShare = 0.5 }) {
  const geometry = useMemo(() => {
    const half = grid.cell_size_m / 2 / KM
    const positions = []
    const colours = []
    const colour = new THREE.Color()
    for (let r = 0; r < grid.height; r++) {
      for (let c = 0; c < grid.width; c++) {
        const share = overlay.flooded_share[r]?.[c]
        const ground = grid.values[r][c]
        if (share == null || share < minShare || ground === null) continue
        const dmean = overlay.depth_mean[r][c] ?? 0
        const dmax = overlay.depth_max[r][c] ?? 0
        const y = ((ground + dmean) * exaggeration) / KM + 0.002
        const x = frame.toX(c), z = frame.toZ(r)
        positions.push(x - half, y, z - half, x - half, y, z + half, x + half, y, z - half,
          x + half, y, z - half, x - half, y, z + half, x + half, y, z + half)
        ramp(dmax / DEPTH_MAX_M, DEPTH_STOPS, colour)
        for (let k = 0; k < 6; k++) colours.push(colour.r, colour.g, colour.b)
      }
    }
    if (!positions.length) return null
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(colours, 3))
    g.computeVertexNormals()
    return g
  }, [grid, overlay, frame, exaggeration, minShare])
  useEffect(() => () => geometry?.dispose(), [geometry])
  if (!geometry) return null
  return (
    <mesh geometry={geometry} renderOrder={2}>
      <meshStandardMaterial vertexColors transparent opacity={0.85} roughness={0.25} metalness={0.05} depthWrite={false} side={THREE.DoubleSide} />
    </mesh>
  )
}

// ---------------------------------------------------------------- draped vectors

const lift = (frame, exaggeration, metres) => (e, n) => ((frame.ground(e, n) + metres) * exaggeration) / KM + 0.003

/** All line parts of a layer merged into one LineSegments draw call, clipped to the crop. */
function DrapedLines({ features, frame, exaggeration, colour, lift: liftM = 1.5, opacity = 1 }) {
  const geometry = useMemo(() => {
    const y = lift(frame, exaggeration, liftM)
    const pos = []
    for (const f of features) {
      for (const part of lineParts(f.geometry)) {
        let prev = null
        for (const [lon, lat] of part) {
          const [e, n] = frame.project(lon, lat)
          // Segments leaving the terrain crop are dropped rather than drawn in mid-air.
          const p = frame.inside(e, n) ? [(e - frame.cx) / KM, y(e, n), -(n - frame.cy) / KM] : null
          if (prev && p) pos.push(...prev, ...p)
          prev = p
        }
      }
    }
    if (!pos.length) return null
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    return g
  }, [features, frame, exaggeration, liftM])
  useEffect(() => () => geometry?.dispose(), [geometry])
  if (!geometry) return null
  return (
    <lineSegments geometry={geometry} renderOrder={3}>
      <lineBasicMaterial color={colour} transparent={opacity < 1} opacity={opacity} />
    </lineSegments>
  )
}

/** Polygons triangulated flat in plan view, each vertex lifted onto the terrain. */
function DrapedPolygons({ features, frame, exaggeration, colour, opacity = 0.55, lift: liftM = 1 }) {
  const geometry = useMemo(() => {
    const y = lift(frame, exaggeration, liftM)
    const toXY = ([lon, lat]) => {
      const [e, n] = frame.project(lon, lat)
      return new THREE.Vector2((e - frame.cx) / KM, (n - frame.cy) / KM)
    }
    const parts = []
    for (const f of features) {
      for (const rings of polygonParts(f.geometry)) {
        if (!rings[0] || rings[0].length < 4) continue
        const shape = new THREE.Shape(rings[0].map(toXY))
        shape.holes = rings.slice(1).filter((h) => h.length >= 4).map((h) => new THREE.Path(h.map(toXY)))
        const g = new THREE.ShapeGeometry(shape)
        const p = g.getAttribute('position')
        for (let i = 0; i < p.count; i++) {
          const sx = p.getX(i), sy = p.getY(i)
          p.setXYZ(i, sx, y(sx * KM + frame.cx, sy * KM + frame.cy), -sy)
        }
        g.deleteAttribute('normal')
        g.deleteAttribute('uv')
        parts.push(g)
      }
    }
    if (!parts.length) return null
    const merged = mergeGeometries(parts, false)
    parts.forEach((g) => g.dispose())
    return merged
  }, [features, frame, exaggeration, liftM])
  useEffect(() => () => geometry?.dispose(), [geometry])
  if (!geometry) return null
  return (
    <mesh geometry={geometry} renderOrder={2}>
      <meshBasicMaterial color={colour} transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  )
}

function AreaBoundary({ area, frame, exaggeration }) {
  const lines = useMemo(() => {
    if (!area?.geometry) return []
    const y = lift(frame, exaggeration, 4)
    return polygonsOf(area.geometry).flat().map((ring) => ring.map(([lon, lat]) => {
      const [e, n] = frame.project(lon, lat)
      return [(e - frame.cx) / KM, y(e, n), -(n - frame.cy) / KM]
    }))
  }, [area, frame, exaggeration])
  return lines.map((pts, i) => (
    <Line key={i} points={pts} color={AREA_COLOUR} lineWidth={2.5} dashed={area.kind === 'osm-point'} dashSize={0.15} gapSize={0.1} renderOrder={4} />
  ))
}

/** Vertical pin at the selected point. */
function Pin({ point, frame, exaggeration }) {
  const [e, n] = frame.project(point[0], point[1])
  if (!frame.inside(e, n)) return null
  const x = (e - frame.cx) / KM
  const z = -(n - frame.cy) / KM
  const y = (frame.ground(e, n) * exaggeration) / KM
  const h = Math.max(0.12, frame.spanKm / 40)
  return (
    <group position={[x, y, z]} renderOrder={5}>
      <mesh position={[0, h / 2, 0]}>
        <cylinderGeometry args={[h / 40, h / 40, h, 8]} />
        <meshBasicMaterial color={PIN_COLOUR} />
      </mesh>
      <mesh position={[0, h, 0]}>
        <sphereGeometry args={[h / 8, 16, 12]} />
        <meshBasicMaterial color={AREA_COLOUR} />
      </mesh>
    </group>
  )
}

// ---------------------------------------------------------------- scene

/** Pulls the camera back on portrait screens so the whole crop stays in view horizontally. */
function fitToAspect([x, y, z], baseY, aspect) {
  const k = aspect && aspect < 1 ? Math.min(2.5, 0.85 / aspect) : 1
  return [x, baseY + (y - baseY) * Math.max(1, k), z * Math.max(1, k)]
}

/** Re-frames the camera (and its clipping planes) whenever the cropped area changes. */
function CameraRig({ frame, home, baseY, span, controls }) {
  const camera = useThree((s) => s.camera)
  const invalidate = useThree((s) => s.invalidate)
  useEffect(() => {
    camera.near = span / 2000
    camera.far = span * 20
    camera.position.set(...fitToAspect(home, baseY, camera.aspect))
    camera.updateProjectionMatrix()
    if (controls.current) {
      controls.current.target.set(0, baseY, 0)
      controls.current.update()
    }
    invalidate()
    // Only a new crop re-frames; exaggeration changes keep the user's view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, frame])
  return null
}

const TerrainScene = forwardRef(function TerrainScene({
  grid, frame, overlay, area, pin, basemap, exaggeration, colourMode, contours, interval,
  showDepth, extentFeatures, lineLayers, buildingFeatures, onPick,
}, ref) {
  const controls = useRef()
  const span = frame.spanKm
  const baseY = ((frame.lo + frame.hi) / 2) * exaggeration / KM
  const home = useMemo(() => [0, baseY + span * 0.7, span * 0.6], [span, baseY])

  useImperativeHandle(ref, () => ({
    reset() {
      const c = controls.current
      if (!c) return
      c.object.position.set(...fitToAspect(home, baseY, c.object.aspect))
      c.target.set(0, baseY, 0)
      c.update()
    },
  }), [home, baseY])

  return (
    <Canvas
      camera={{ position: home, fov: 42, near: span / 2000, far: span * 20 }}
      dpr={[1, 2]}
      frameloop="demand"
      resize={{ polyfill: PollingResizeObserver }}
      gl={{ antialias: true }}
      onCreated={({ gl }) => gl.setClearColor(CLEAR_COLOUR)}
      aria-label="3D terrain map of Chennai"
    >
      <hemisphereLight args={['#F8FAFC', '#475569', 0.9]} />
      <directionalLight position={[-span, span * 0.9, span * 0.6]} intensity={1.4} />
      <Terrain grid={grid} frame={frame} exaggeration={exaggeration} colourMode={colourMode} contours={contours}
               interval={interval} basemap={basemap} onPick={onPick} />
      {showDepth && overlay && <FloodDepth grid={grid} overlay={overlay} frame={frame} exaggeration={exaggeration} />}
      {extentFeatures && <>
        <DrapedPolygons features={extentFeatures} frame={frame} exaggeration={exaggeration} colour={EXTENT_COLOUR} opacity={0.25} />
        <DrapedLines features={extentFeatures} frame={frame} exaggeration={exaggeration} colour={EXTENT_COLOUR} lift={1.2} />
      </>}
      {buildingFeatures && <DrapedPolygons features={buildingFeatures} frame={frame} exaggeration={exaggeration} colour={BUILDING_COLOUR} opacity={0.8} lift={0.8} />}
      {lineLayers.map((l) => (
        <DrapedLines key={l.name} features={l.features} frame={frame} exaggeration={exaggeration} colour={l.colour} lift={l.lift ?? 2} />
      ))}
      <AreaBoundary area={area} frame={frame} exaggeration={exaggeration} />
      {pin && <Pin point={pin} frame={frame} exaggeration={exaggeration} />}
      <CameraRig frame={frame} home={home} baseY={baseY} span={span} controls={controls} />
      <MapControls ref={controls} makeDefault target={[0, baseY, 0]} enableDamping={false} screenSpacePanning={false}
                   maxPolarAngle={Math.PI / 2.1} minDistance={span / 60} maxDistance={span * 3} />
    </Canvas>
  )
})

export default TerrainScene
