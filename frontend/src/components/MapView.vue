<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import { useStore } from '../store'
import { api } from '../utils/api'

const store = useStore()
const mapContainer = ref<HTMLDivElement>()
let map: L.Map
let markersLayer: L.LayerGroup
let coverageLayer: L.LayerGroup
let losLine: L.Polyline | null = null

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

  darkTiles.addTo(map)

  L.control.layers(
    { 'Dark': darkTiles, 'Satellite': satellite, 'Topographic': topo },
    {},
    { position: 'topright' }
  ).addTo(map)

  L.control.zoom({ position: 'topright' }).addTo(map)

  markersLayer = L.layerGroup().addTo(map)
  coverageLayer = L.layerGroup().addTo(map)

  // Map click handler
  map.on('click', async (e: L.LeafletMouseEvent) => {
    const { lat, lng: lon } = e.latlng

    if (store.activeMode === 'place') {
      store.currentNode.lat = parseFloat(lat.toFixed(6))
      store.currentNode.lon = parseFloat(lon.toFixed(6))

      // Save node
      await store.saveNode({ ...store.currentNode })
      store.activeMode = 'none'
      refreshMarkers()
    } else if (store.activeMode === 'los') {
      store.losPoints.push({ lat, lon })
      if (store.losPoints.length === 1) {
        // Add temp marker
        L.marker([lat, lon], { icon: towerIcon }).addTo(markersLayer)
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
      store.selectedNodeId = node.id ?? null
      // Load into editor
      Object.assign(store.currentNode, node)
    })
    marker.on('dragend', async (e: any) => {
      const pos = e.target.getLatLng()
      if (node.id) {
        await api.updateNode(node.id, { lat: pos.lat, lon: pos.lng })
        node.lat = pos.lat
        node.lon = pos.lng
      }
    })
    marker.addTo(markersLayer)
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

    // Draw LoS line
    if (losLine) map.removeLayer(losLine)
    losLine = L.polyline(
      [[p1.lat, p1.lon], [p2.lat, p2.lon]],
      { color: result.is_los ? '#3fb950' : '#f85149', weight: 2, dashArray: '8, 4' }
    ).addTo(map)

    // Add RX marker
    L.marker([p2.lat, p2.lon], { icon: rxIcon }).addTo(markersLayer)
  } catch (err) {
    console.error('LoS simulation failed:', err)
  } finally {
    store.loading = false
    store.losPoints = []
    store.activeMode = 'none'
  }
}

// Watch for coverage results
watch(() => store.coverageResult, (result) => {
  coverageLayer.clearLayers()
  if (!result) return

  const colorMap: Record<string, string> = {
    excellent: '#3fb950',
    good: '#58a6ff',
    marginal: '#d29922',
    weak: '#f85149',
    none: 'transparent',
  }

  for (const p of result.points) {
    if (p.level === 'none') continue
    const color = colorMap[p.level] || '#888'
    L.circleMarker([p.lat, p.lon], {
      radius: Math.max(3, result.resolution_m / 50),
      fillColor: color,
      fillOpacity: 0.5,
      stroke: false,
    }).addTo(coverageLayer)
  }
})

// Watch nodes changes
watch(() => store.nodes, () => refreshMarkers(), { deep: true })
</script>

<template>
  <div class="map-wrapper">
    <div ref="mapContainer" class="map-container"></div>
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
        @click="() => { store.activeMode = store.activeMode === 'los' ? 'none' : 'los'; store.losPoints = [] }"
        title="Click two points for LoS profile"
      >
        LoS Profile
      </button>
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
    <div v-if="store.loading" class="map-loading">
      <div class="spinner"></div>
      Computing...
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

.map-toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
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
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 1000;
  background: rgba(22, 27, 34, 0.9);
  color: var(--text-primary);
  padding: 20px 30px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
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
</style>
