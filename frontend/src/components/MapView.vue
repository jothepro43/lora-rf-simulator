<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import { useStore } from '../store'
import { api } from '../utils/api'

const store = useStore()
const mapContainer = ref<HTMLDivElement>()
const searchContainer = ref<HTMLDivElement>()
let map: L.Map
let markersLayer: L.LayerGroup
let coverageLayer: L.ImageOverlay | null = null
let losMarkersLayer: L.LayerGroup
let losLine: L.Polyline | null = null
let losSegmentsLayer: L.LayerGroup | null = null
let losCursorMarker: L.CircleMarker | null = null
let losInspectMarker: L.Marker | null = null
let legendControl: L.Control | null = null
let linksLayer: L.LayerGroup
let pathLayer: L.LayerGroup

// Search state
const searchQuery = ref('')
const searchResults = ref<any[]>([])
let searchTimeout: ReturnType<typeof setTimeout> | null = null
let tempMarker: L.Marker | null = null

// Fix default marker icons
delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
})

const towerIcon = L.divIcon({
  className: 'tower-marker',
  html: `<div style="background:#3fb950;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px rgba(63,185,80,0.6);"></div>`,
  iconSize: [14, 14],
  iconAnchor: [7, 7],
})

const rxIcon = L.divIcon({
  className: 'rx-marker',
  html: `<div style="background:#58a6ff;width:12px;height:12px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px rgba(88,166,255,0.6);"></div>`,
  iconSize: [12, 12],
  iconAnchor: [6, 6],
})

// Colormap CSS gradients for legend
const COLORMAP_GRADIENTS: Record<string, string> = {
  plasma: 'linear-gradient(to right, rgb(13,8,135), rgb(126,3,168), rgb(204,71,120), rgb(248,149,64), rgb(240,249,33))',
  viridis: 'linear-gradient(to right, rgb(68,1,84), rgb(59,82,139), rgb(33,145,140), rgb(94,201,98), rgb(253,231,37))',
  inferno: 'linear-gradient(to right, rgb(0,0,4), rgb(87,16,110), rgb(188,55,84), rgb(249,142,9), rgb(252,255,164))',
  turbo: 'linear-gradient(to right, rgb(48,18,59), rgb(30,150,242), rgb(115,224,76), rgb(249,168,37), rgb(122,4,3))',
}

function updateLegend() {
  if (!map) return
  if (legendControl) {
    map.removeControl(legendControl)
    legendControl = null
  }
  if (!store.coverageResult) return

  const result = store.coverageResult
  const colormap = result.colormap || store.displayParams.colormap
  const gradient = COLORMAP_GRADIENTS[colormap] || COLORMAP_GRADIENTS.plasma

  legendControl = new L.Control({ position: 'bottomright' })
  legendControl.onAdd = () => {
    const div = L.DomUtil.create('div', 'rf-legend')
    div.innerHTML = `
      <div style="background:rgba(22,27,34,0.92);padding:10px 14px;border-radius:6px;border:1px solid #30363d;color:#e6edf3;font-size:12px;min-width:180px;">
        <div style="font-weight:600;margin-bottom:6px;">Signal Strength (dBm)</div>
        <div style="height:14px;border-radius:3px;background:${gradient};margin-bottom:4px;"></div>
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#8b949e;">
          <span>${result.min_dbm}</span>
          <span>${Math.round((result.min_dbm + result.max_dbm) / 2)}</span>
          <span>${result.max_dbm}</span>
        </div>
        ${result.stats && result.stats.cells_computed ? `
        <div style="margin-top:6px;font-size:11px;color:#6e7681;">
          ${result.stats.cells_computed} cells | ${result.stats.elapsed_seconds}s
        </div>` : ''}
      </div>
    `
    return div
  }
  legendControl.addTo(map)
}

onMounted(() => {
  if (!mapContainer.value) return

  map = L.map(mapContainer.value, {
    center: [34.237, -83.869],
    zoom: 10,
    zoomControl: false,
  })

  // Dark CartoDB tiles
  const darkTiles = L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
      maxZoom: 19,
    }
  )

  const satellite = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {
      attribution: '&copy; Esri',
      maxZoom: 19,
    }
  )

  const topo = L.tileLayer(
    'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    {
      attribution: '&copy; OpenTopoMap',
      maxZoom: 17,
    }
  )

  const topoRelief = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
    {
      attribution: '&copy; Esri',
      maxZoom: 19,
    }
  )

  const terrainShading = L.tileLayer(
    'https://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}{r}.jpg',
    {
      attribution: '&copy; Stamen Design, &copy; OpenMapTiles',
      maxZoom: 18,
    }
  )

  darkTiles.addTo(map)

  L.control.layers(
    {
      'Dark': darkTiles,
      'Satellite': satellite,
      'Topographic': topo,
      'Terrain Relief': topoRelief,
      'Terrain Shading': terrainShading,
    },
    {},
    { position: 'topright' }
  ).addTo(map)

  L.control.zoom({ position: 'topright' }).addTo(map)

  markersLayer = L.layerGroup().addTo(map)
  losMarkersLayer = L.layerGroup().addTo(map)
  linksLayer = L.layerGroup().addTo(map)
  pathLayer = L.layerGroup().addTo(map)
  losSegmentsLayer = L.layerGroup().addTo(map)

  // Prevent map interaction on search box
  if (searchContainer.value) {
    L.DomEvent.disableClickPropagation(searchContainer.value)
    L.DomEvent.disableScrollPropagation(searchContainer.value)
  }

  // Close search dropdown on map click
  map.on('mousedown', () => {
    searchResults.value = []
  })

  // Map click handler
  map.on('click', async (e: L.LeafletMouseEvent) => {
    const { lat, lng: lon } = e.latlng

    if (store.activeMode === 'place') {
      // Create a new node at the clicked location (spread to avoid mutation)
      const newNode = {
        ...store.currentNode,
        id: undefined,
        lat: parseFloat(lat.toFixed(6)),
        lon: parseFloat(lon.toFixed(6)),
        name: `Site ${store.nodes.length + 1}`,
      }

      await store.saveNode(newNode)
      // Stay in place mode so user can keep adding nodes
      refreshMarkers()
    } else if (store.activeMode === 'los') {
      store.losPoints.push({ lat, lon })
      if (store.losPoints.length === 1) {
        // Add temp TX marker
        L.marker([lat, lon], { icon: towerIcon }).addTo(losMarkersLayer)
      }
      if (store.losPoints.length === 2) {
        await runLoS()
      }
    }
  })

  refreshMarkers()
})

function refreshMarkers() {
  if (!markersLayer) return
  markersLayer.clearLayers()

  for (const node of store.nodes) {
    const marker = L.marker([node.lat, node.lon], { icon: towerIcon, draggable: true })
    marker.bindPopup(`
      <div style="color:#000;font-size:13px;">
        <strong>${node.name}</strong><br/>
        ${node.lat.toFixed(5)}, ${node.lon.toFixed(5)}<br/>
        ${node.device_preset} | ${node.tx_power_dbm} dBm<br/>
        Height: ${node.height_agl}m AGL
      </div>
    `)
    marker.on('click', () => {
      // Link mode: click two nodes to create a link
      if (store.activeMode === 'link' && node.id) {
        if (!store.linkStartNodeId) {
          store.linkStartNodeId = node.id
        } else if (node.id !== store.linkStartNodeId) {
          store.createLink(store.linkStartNodeId, node.id)
          store.linkStartNodeId = null
          store.activeMode = 'none'
          drawNetworkLinks()
        }
        return
      }
      store.selectedNodeId = node.id ?? null
      Object.assign(store.currentNode, node)
    })
    marker.on('dragend', async (e: any) => {
      const pos = e.target.getLatLng()
      if (node.id) {
        await api.updateNode(node.id, { lat: pos.lat, lon: pos.lng })
        node.lat = pos.lat
        node.lon = pos.lng
        // Update sidebar if this is the selected node
        if (store.selectedNodeId === node.id) {
          store.currentNode.lat = pos.lat
          store.currentNode.lon = pos.lng
        }
      }
    })
    marker.addTo(markersLayer)
  }
}

function drawNetworkLinks() {
  if (!linksLayer) return
  linksLayer.clearLayers()
  const statusColors: Record<string, string> = {
    excellent: '#3fb950', good: '#88ff00', viable: '#d29922',
    marginal: '#f0883e', blocked: '#f85149', unknown: '#8b949e',
  }
  const pathLinkIds: Set<number> = new Set(
    (store.pathResult?.found && Array.isArray(store.pathResult.link_ids))
      ? store.pathResult.link_ids
      : []
  )
  for (const link of store.networkLinks) {
    if (!link.node1_lat || !link.node2_lat) continue
    const color = statusColors[link.status] || statusColors.unknown
    const dash = (link.status === 'blocked' || link.status === 'unknown') ? '8, 6' : ''
    // Dim non-path links when a path is highlighted.
    const dim = pathLinkIds.size > 0 && !pathLinkIds.has(link.id)
    const line = L.polyline(
      [[link.node1_lat, link.node1_lon], [link.node2_lat, link.node2_lon]],
      { color, weight: dim ? 1.5 : 2.5, opacity: dim ? 0.25 : 0.8, dashArray: dash }
    ).addTo(linksLayer)
    line.bindPopup(`<div style="color:#000;min-width:180px;">
      <b>${link.node1_name} \u2194 ${link.node2_name}</b><br/>
      <span style="color:${color};font-weight:600;">${(link.status || 'unknown').toUpperCase()}</span><br/>
      Distance: ${link.distance_km || '?'} km<br/>
      Path Loss: ${link.path_loss_db || '?'} dB<br/>
      Margin: ${link.link_margin_db || '?'} dB<br/>
      LoS: ${link.is_los ? 'Clear' : 'Obstructed'}
    </div>`)
    // Midpoint label
    const midLat = (link.node1_lat + link.node2_lat) / 2
    const midLon = (link.node1_lon + link.node2_lon) / 2
    const label = link.status === 'unknown' ? '?' : `${link.distance_km || '?'}km ${link.link_margin_db > 0 ? link.link_margin_db + 'dB' : '\u274c'}`
    L.tooltip({ permanent: true, direction: 'center', className: 'link-label' })
      .setLatLng([midLat, midLon])
      .setContent(`<span style="background:${color}22;color:${color};padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;border:1px solid ${color}44;opacity:${dim ? 0.4 : 1};">${label}</span>`)
      .addTo(linksLayer)
  }
}

function drawPathHighlight() {
  if (!pathLayer) return
  pathLayer.clearLayers()
  const result = store.pathResult
  if (!result || !result.found || !Array.isArray(result.link_ids)) return

  const bottleneck = result.bottleneck_link_id
  const linksById: Record<number, any> = {}
  for (const link of store.networkLinks) linksById[link.id] = link

  for (const linkId of result.link_ids) {
    const link = linksById[linkId]
    if (!link || !link.node1_lat || !link.node2_lat) continue
    const isBottleneck = linkId === bottleneck
    L.polyline(
      [[link.node1_lat, link.node1_lon], [link.node2_lat, link.node2_lon]],
      {
        color: isBottleneck ? '#ff8c1a' : '#00d4ff',
        weight: 6,
        opacity: 0.85,
      },
    ).addTo(pathLayer)
  }
}

async function runLoS() {
  if (store.losPoints.length < 2) return
  store.loading = true
  try {
    const [p1, p2] = store.losPoints
    const result = await api.simulateLos({
      tx_lat: p1.lat,
      tx_lon: p1.lon,
      tx_height_m: store.currentNode.height_agl,
      rx_lat: p2.lat,
      rx_lon: p2.lon,
      rx_height_m: store.simParams.rx_height_m,
      frequency_mhz: store.currentNode.frequency_mhz,
      num_points: 200,
      k_factor: store.simParams.k_factor,
    })
    store.losResult = result
    store.terrainProfileOpen = true

    // Draw segmented LoS line (green=clear, red=blocked)
    if (losLine) { map.removeLayer(losLine); losLine = null }
    losSegmentsLayer?.clearLayers()
    drawLosSegments(result)

    // Add RX marker
    L.marker([p2.lat, p2.lon], { icon: rxIcon }).addTo(losMarkersLayer)
  } catch (err) {
    console.error('LoS simulation failed:', err)
  } finally {
    store.loading = false
    store.losPoints = []
    store.activeMode = 'none'
  }
}

function drawLosSegments(result: any) {
  if (!result?.lats || !losSegmentsLayer) return
  const latlngs: [number, number][] = result.lats.map((lat: number, i: number) => [lat, result.lons[i]])
  for (let i = 0; i < latlngs.length - 1; i++) {
    const elev = result.elevations[i]
    const losH = result.los_heights[i]
    const isBlocked = elev > losH
    L.polyline([latlngs[i], latlngs[i + 1]], {
      color: isBlocked ? '#f85149' : '#3fb950',
      weight: 3,
      opacity: 0.8,
    }).addTo(losSegmentsLayer!)
  }
}

function exportPng() {
  if (!store.coverageResult?.image_base64) return
  const binary = atob(store.coverageResult.image_base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  const blob = new Blob([bytes], { type: 'image/png' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'coverage.png'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function cancelCoverage() {
  if (store.coverageAbort) {
    store.coverageAbort.abort()
    store.coverageAbort = null
    store.loading = false
  }
}

// --- Search functions ---

function onSearchInput() {
  if (searchTimeout) clearTimeout(searchTimeout)
  if (searchQuery.value.length < 3) {
    searchResults.value = []
    return
  }
  searchTimeout = setTimeout(async () => {
    try {
      searchResults.value = await api.geocode(searchQuery.value)
    } catch {
      searchResults.value = []
    }
  }, 300)
}

async function searchLocation() {
  if (searchQuery.value.length < 3) return
  if (searchTimeout) clearTimeout(searchTimeout)
  try {
    searchResults.value = await api.geocode(searchQuery.value)
    if (searchResults.value.length === 1) {
      selectSearchResult(searchResults.value[0])
    }
  } catch {
    searchResults.value = []
  }
}

function clearSearch() {
  searchQuery.value = ''
  searchResults.value = []
  if (tempMarker) {
    map.removeLayer(tempMarker)
    tempMarker = null
  }
}

function selectSearchResult(result: any) {
  searchResults.value = []
  searchQuery.value = result.display_name

  // Remove previous temp marker
  if (tempMarker) {
    map.removeLayer(tempMarker)
    tempMarker = null
  }

  map.setView([result.lat, result.lon], 15)

  // Update sidebar lat/lon
  store.currentNode.lat = parseFloat(result.lat.toFixed(6))
  store.currentNode.lon = parseFloat(result.lon.toFixed(6))

  if (store.activeMode === 'place') {
    // Immediately place a node
    const newNode = {
      ...store.currentNode,
      id: undefined,
      lat: parseFloat(result.lat.toFixed(6)),
      lon: parseFloat(result.lon.toFixed(6)),
      name: result.display_name.split(',')[0],
    }
    store.saveNode(newNode).then(() => refreshMarkers())
  } else {
    // Drop a temporary marker with "Place Node Here" popup
    const escapedName = result.display_name.split(',')[0].replace(/'/g, '')
    tempMarker = L.marker([result.lat, result.lon], {
      icon: L.divIcon({
        html: '<div style="background:#d29922;width:16px;height:16px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 12px rgba(210,153,34,0.8);"></div>',
        className: '',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      }),
    }).addTo(map)

    tempMarker.bindPopup(`
      <div style="color:#000;text-align:center;">
        <b>${escapedName}</b><br/>
        <small>${result.lat.toFixed(5)}, ${result.lon.toFixed(5)}</small><br/>
        <button onclick="window.__placeNodeAtSearch(${result.lat},${result.lon},'${escapedName}')"
                style="margin-top:8px;padding:6px 16px;background:#3fb950;color:#000;border:none;border-radius:4px;cursor:pointer;font-weight:600;">
          Place Node Here
        </button>
      </div>
    `).openPopup()

    tempMarker.on('popupclose', () => {
      if (tempMarker) {
        map.removeLayer(tempMarker)
        tempMarker = null
      }
    })
  }
}

// Global callback for popup button
;(window as any).__placeNodeAtSearch = async (lat: number, lon: number, name: string) => {
  const newNode = {
    ...store.currentNode,
    id: undefined,
    lat: parseFloat(lat.toFixed(6)),
    lon: parseFloat(lon.toFixed(6)),
    name,
  }
  await store.saveNode(newNode)
  refreshMarkers()
  map.closePopup()
  if (tempMarker) {
    map.removeLayer(tempMarker)
    tempMarker = null
  }
}

// Watch for coverage results – render as image overlay
watch(() => store.coverageResult, (result) => {
  if (coverageLayer) {
    map.removeLayer(coverageLayer)
    coverageLayer = null
  }
  if (!result || !result.image_base64) {
    updateLegend()
    return
  }

  const imgUrl = `data:image/png;base64,${result.image_base64}`
  const bounds = result.bounds as [[number, number], [number, number]]
  coverageLayer = L.imageOverlay(imgUrl, bounds, {
    opacity: 1 - store.displayParams.transparency / 100,
    interactive: false,
  }).addTo(map)

  updateLegend()
})

// Watch transparency changes
watch(() => store.displayParams.transparency, (val) => {
  if (coverageLayer) {
    coverageLayer.setOpacity(1 - val / 100)
  }
})

// Clean up LoS visuals when terrain profile is closed
watch(() => store.terrainProfileOpen, (open) => {
  if (!open) {
    if (losLine) {
      map.removeLayer(losLine)
      losLine = null
    }
    losMarkersLayer?.clearLayers()
    losSegmentsLayer?.clearLayers()
    if (losCursorMarker) {
      map.removeLayer(losCursorMarker)
      losCursorMarker = null
    }
    if (losInspectMarker) {
      map.removeLayer(losInspectMarker)
      losInspectMarker = null
    }
  }
})

// Watch for LoS results triggered from node-to-node (store-driven)
watch(() => store.losResult, (result) => {
  if (!result || !map) return
  // Only draw if losPoints are set (node-to-node triggers this)
  if (store.losPoints.length === 2) {
    const [p1, p2] = store.losPoints
    // Clear previous
    if (losLine) { map.removeLayer(losLine); losLine = null }
    losMarkersLayer?.clearLayers()
    losSegmentsLayer?.clearLayers()

    // Draw segmented colored line
    drawLosSegments(result)

    L.marker([p1.lat, p1.lon], { icon: towerIcon }).addTo(losMarkersLayer)
    L.marker([p2.lat, p2.lon], { icon: rxIcon }).addTo(losMarkersLayer)

    // Fit map to show both points
    map.fitBounds([[p1.lat, p1.lon], [p2.lat, p2.lon]], { padding: [50, 50] })

    // Clear losPoints so we don't re-trigger
    store.losPoints = []
  }
})

// Watch LoS hover point — move cursor marker on map
watch(() => store.losHoverPoint, (point) => {
  if (losCursorMarker) {
    map.removeLayer(losCursorMarker)
    losCursorMarker = null
  }
  if (point) {
    losCursorMarker = L.circleMarker([point.lat, point.lon], {
      radius: 6,
      color: '#58a6ff',
      fillColor: '#58a6ff',
      fillOpacity: 0.9,
      weight: 2,
    }).addTo(map)

    losCursorMarker.bindTooltip(
      `${point.elevation_m.toFixed(0)}m ASL<br>${point.distance_km.toFixed(2)} km<br>${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`,
      { permanent: true, direction: 'top', offset: [0, -10], className: 'cursor-tooltip' }
    )
  }
})

// Watch LoS inspect point — persistent marker with popup on click
watch(() => store.losInspectPoint, (point) => {
  if (losInspectMarker) {
    map.removeLayer(losInspectMarker)
    losInspectMarker = null
  }
  if (!point) return

  const color = point.is_obstruction ? '#f85149' : '#3fb950'
  const icon = L.divIcon({
    html: `<div style="background:${color};width:12px;height:12px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px ${color}80;"></div>`,
    className: '',
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  })

  losInspectMarker = L.marker([point.lat, point.lon], { icon }).addTo(map)
  losInspectMarker.bindPopup(`
    <div style="color:#000;">
      <b>${point.is_obstruction ? 'Obstruction' : 'Clear'}</b><br/>
      <b>Coords:</b> ${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}<br/>
      <b>Elevation:</b> ${point.elevation_m.toFixed(0)}m ASL<br/>
      <b>LoS height:</b> ${point.los_height_m.toFixed(0)}m ASL<br/>
      ${point.is_obstruction ? `<b>Intrusion:</b> ${point.intrusion_m.toFixed(1)}m above LoS<br/>` : ''}
      <b>Distance from TX:</b> ${point.distance_km.toFixed(2)} km
    </div>
  `).openPopup()

  map.panTo([point.lat, point.lon])
})

// Watch nodes changes
watch(() => store.nodes, () => refreshMarkers(), { deep: true })
watch(() => store.networkLinks, () => {
  drawNetworkLinks()
  drawPathHighlight()
}, { deep: true })
watch(() => store.pathResult, () => {
  drawNetworkLinks()
  drawPathHighlight()
}, { deep: true })

// Watch for pan requests from sidebar
watch(() => store.panRequest, (req) => {
  if (req && map) {
    map.setView([req.lat, req.lon], Math.max(map.getZoom(), 14))
    store.panRequest = null
  }
})
</script>

<template>
  <div class="map-wrapper">
    <div ref="mapContainer" class="map-container"></div>

    <!-- Sidebar reopen button (shown when sidebar is collapsed) -->
    <button
      v-if="!store.sidebarOpen"
      class="sidebar-reopen-btn"
      @click="store.sidebarOpen = true"
      title="Open sidebar"
    >&#9654;</button>

    <div class="map-toolbar">
      <button
        :class="{ active: store.activeMode === 'place' }"
        @click="store.activeMode = store.activeMode === 'place' ? 'none' : 'place'"
        title="Click map to place a node"
      >
        + Node
      </button>
      <button
        :class="{ active: store.activeMode === 'los' }"
        @click="() => { store.activeMode = store.activeMode === 'los' ? 'none' : 'los'; store.losPoints = []; losMarkersLayer?.clearLayers(); if (losLine) { map.removeLayer(losLine); losLine = null; } store.terrainProfileOpen = false; store.losResult = null }"
        title="Click two points for LoS profile"
      >
        LoS Profile
      </button>
      <button
        :class="{ active: store.activeMode === 'link' }"
        @click="() => { store.activeMode = store.activeMode === 'link' ? 'none' : 'link'; store.linkStartNodeId = null }"
        title="Click two nodes to create a network link"
      >
        🔗 Link
      </button>
      <button
        v-if="store.coverageResult?.image_base64"
        @click="exportPng"
        title="Download coverage as PNG"
      >
        Export PNG
      </button>
    </div>

    <!-- Map search box -->
    <div ref="searchContainer" class="map-search-container">
      <div class="map-search-box">
        <span class="search-icon">&#128269;</span>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search location (e.g., Nesbitt Building, Dahlonega GA, Yonah Mountain)"
          @keyup.enter="searchLocation"
          @input="onSearchInput"
          class="search-input"
        />
        <button v-if="searchQuery" @click="clearSearch" class="clear-btn">&#10005;</button>
      </div>
      <div v-if="searchResults.length" class="search-results-dropdown">
        <div
          v-for="(result, idx) in searchResults"
          :key="idx"
          @click="selectSearchResult(result)"
          class="search-result-item"
        >
          <span class="result-name">{{ result.display_name }}</span>
          <span class="result-coords">{{ result.lat.toFixed(4) }}, {{ result.lon.toFixed(4) }}</span>
        </div>
      </div>
    </div>

    <div v-if="store.activeMode === 'place'" class="map-hint">
      Click map to place node
    </div>
    <div v-if="store.activeMode === 'los' && store.losPoints.length === 0" class="map-hint">
      Click TX point
    </div>
    <div v-if="store.activeMode === 'los' && store.losPoints.length === 1" class="map-hint">
      Click RX point
    </div>
    <div v-if="store.activeMode === 'link' && !store.linkStartNodeId" class="map-hint">
      Click first node to link
    </div>
    <div v-if="store.activeMode === 'link' && store.linkStartNodeId" class="map-hint">
      Click second node to complete link
    </div>

    <!-- Loading overlay with cancel -->
    <div v-if="store.loading" class="map-loading">
      <div class="loading-content">
        <div class="spinner"></div>
        <span>Computing coverage...</span>
        <button class="cancel-btn" @click="cancelCoverage">Cancel</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.map-wrapper {
  flex: 1;
  position: relative;
}

.map-container {
  width: 100%;
  height: 100%;
  background: var(--bg-primary);
}

.sidebar-reopen-btn {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 1001;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  padding: 8px 10px;
  font-size: 14px;
  cursor: pointer;
  border-radius: 4px;
}

.sidebar-reopen-btn:hover {
  background: var(--accent-green);
  color: #000;
  border-color: var(--accent-green);
}

.map-toolbar {
  position: absolute;
  top: 12px;
  left: 60px;
  z-index: 1000;
  display: flex;
  gap: 8px;
}

.map-toolbar button {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
}

.map-toolbar button.active {
  background: var(--accent-green);
  color: #000;
  border-color: var(--accent-green);
}

.map-hint {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  padding: 10px 20px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  font-size: 14px;
  pointer-events: none;
}

.map-loading {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.loading-content {
  background: rgba(22, 27, 34, 0.92);
  color: var(--text-primary);
  padding: 20px 30px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  pointer-events: auto;
}

.cancel-btn {
  background: var(--accent-red);
  color: #fff;
  border: none;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 4px;
  cursor: pointer;
  margin-left: 8px;
}

.cancel-btn:hover {
  opacity: 0.85;
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border-color);
  border-top: 2px solid var(--accent-green);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Map search box */
.map-search-container {
  position: absolute;
  top: 55px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  width: 450px;
  max-width: 90vw;
}

.map-search-box {
  display: flex;
  align-items: center;
  background: rgba(22, 27, 34, 0.95);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 4px 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(8px);
}

.search-icon {
  font-size: 16px;
  margin-right: 8px;
  opacity: 0.6;
}

.search-input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-size: 14px;
  padding: 8px 0;
  outline: none;
}

.search-input::placeholder {
  color: var(--text-muted);
}

.clear-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  padding: 4px;
}

.search-results-dropdown {
  background: rgba(22, 27, 34, 0.97);
  border: 1px solid var(--border-color);
  border-radius: 0 0 8px 8px;
  border-top: none;
  max-height: 250px;
  overflow-y: auto;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.search-result-item {
  padding: 10px 16px;
  cursor: pointer;
  border-bottom: 1px solid rgba(48, 54, 61, 0.5);
  display: flex;
  flex-direction: column;
}

.search-result-item:hover {
  background: rgba(88, 166, 255, 0.1);
}

.result-name {
  font-size: 13px;
  color: var(--text-primary);
}

.result-coords {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
</style>

<style>
/* Unscoped so it applies to Leaflet tooltip DOM */
.cursor-tooltip {
  background: rgba(22, 27, 34, 0.92) !important;
  color: #e6edf3 !important;
  border: 1px solid #30363d !important;
  border-radius: 4px !important;
  font-size: 11px !important;
  padding: 4px 8px !important;
}
</style>
