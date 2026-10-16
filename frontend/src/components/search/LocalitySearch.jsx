import { useEffect, useId, useRef, useState } from 'react'
import { Loader2, MapPin, Search, X } from 'lucide-react'
import { useArea } from '../../context/AreaContext'
import { searchGcc, searchOsm } from '../../services/localitySearch'
import { isAbort } from '../../services/api'

/** Accessible combobox searching GCC zones/wards (FLOIN database) and OSM places (Nominatim). */
export default function LocalitySearch({ onSelected, autoFocus = false, size = 'md' }) {
  const { wards, selectResult } = useArea()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [gcc, setGcc] = useState([])
  const [osm, setOsm] = useState({ loading: false, results: [], error: null })
  const [active, setActive] = useState(-1)
  const listId = useId()
  const box = useRef(null)

  useEffect(() => {
    setGcc(searchGcc(query, wards))
    if (query.trim().length < 3) {
      setOsm({ loading: false, results: [], error: null })
      return undefined
    }
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      setOsm((s) => ({ ...s, loading: true, error: null }))
      searchOsm(query.trim(), ctrl.signal)
        .then((results) => setOsm({ loading: false, results, error: null }))
        .catch((error) => !isAbort(error) && setOsm({ loading: false, results: [], error }))
    }, 450)
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [query, wards])

  useEffect(() => {
    const onDoc = (e) => !box.current?.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const all = [...gcc, ...osm.results]
  const choose = (r) => {
    selectResult(r)
    setQuery('')
    setOpen(false)
    setActive(-1)
    onSelected?.(r)
  }
  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(all.length - 1, a + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
    else if (e.key === 'Enter' && active >= 0 && all[active]) { e.preventDefault(); choose(all[active]) }
    else if (e.key === 'Escape') setOpen(false)
  }

  const big = size === 'lg'
  const showList = open && query.trim().length > 0
  return (
    <div ref={box} className="relative w-full">
      <div className={`flex items-center gap-2 rounded-md border border-line-strong bg-paper px-3 focus-within:border-mangrove ${big ? 'py-3' : 'py-1.5'}`}>
        <Search size={big ? 18 : 15} className="shrink-0 text-muted" aria-hidden="true" />
        <input
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          aria-label="Search a Chennai locality, GCC zone or ward"
          autoFocus={autoFocus}
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(-1) }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search Velachery, Adyar zone, Ward 179…"
          className={`min-w-0 flex-1 bg-transparent text-ink placeholder:text-faint focus:outline-none ${big ? 'text-base' : 'text-sm'}`}
        />
        {osm.loading && <Loader2 size={14} className="animate-spin text-muted" aria-label="Searching" />}
        {query && <button type="button" aria-label="Clear search" onClick={() => setQuery('')} className="text-faint hover:text-ink"><X size={14} /></button>}
      </div>

      {showList && (
        <div id={listId} role="listbox" className="scroll-thin absolute left-0 right-0 top-full z-[1600] mt-1 max-h-96 overflow-y-auto rounded-md border border-line-strong bg-paper shadow-xl">
          <Group label="GCC zones & wards · FLOIN database">
            {gcc.length === 0 && <Empty>{wards ? 'No zone or ward matches. Try a zone name (Adyar) or ward number.' : 'Ward boundaries are loading…'}</Empty>}
            {gcc.map((r, i) => <Option key={r.id} r={r} index={i} active={active} listId={listId} onChoose={choose} />)}
          </Group>
          <Group label="OpenStreetMap places · Nominatim">
            {query.trim().length < 3 && <Empty>Type at least 3 characters.</Empty>}
            {osm.error && <Empty error>{osm.error.message}</Empty>}
            {!osm.loading && !osm.error && query.trim().length >= 3 && osm.results.length === 0 && <Empty>No OpenStreetMap place found inside the model area.</Empty>}
            {osm.results.map((r, i) => <Option key={r.id} r={r} index={gcc.length + i} active={active} listId={listId} onChoose={choose} />)}
          </Group>
          <p className="border-t border-line px-3 py-1.5 text-[10px] text-faint">Place search © OpenStreetMap contributors (Nominatim). Only your search text is sent.</p>
        </div>
      )}
    </div>
  )
}

function Group({ label, children }) {
  return (
    <div className="py-1">
      <div className="px-3 pb-1 pt-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">{label}</div>
      {children}
    </div>
  )
}

function Empty({ children, error }) {
  return <p className={`px-3 py-1.5 text-xs ${error ? 'text-terracotta-ink' : 'text-muted'}`}>{children}</p>
}

function Option({ r, index, active, listId, onChoose }) {
  const tag = r.kind === 'osm' ? (r.hasBoundary ? 'boundary' : 'point only') : r.kind
  return (
    <div id={`${listId}-${index}`} role="option" aria-selected={active === index} tabIndex={-1}
         onMouseDown={(e) => { e.preventDefault(); onChoose(r) }}
         className={`flex cursor-pointer items-start gap-2 px-3 py-2 ${active === index ? 'bg-mangrove/15' : 'hover:bg-paper-2'}`}>
      <MapPin size={14} className="mt-0.5 shrink-0 text-mangrove" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-ink">{r.label}</div>
        <div className="truncate text-[11px] text-muted">{r.sublabel}</div>
      </div>
      <span className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[9px] uppercase ${tag === 'point only' ? 'bg-paper-2 text-muted' : 'bg-teal/15 text-teal-ink'}`}>{tag}</span>
    </div>
  )
}
