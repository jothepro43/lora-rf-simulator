<script setup lang="ts">
import { ref, computed } from 'vue'
import { useStore } from '../store'
import { api } from '../utils/api'

const store = useStore()

const sections = ref({
  site: true,
  feeder: true,
  antenna: true,
  receiver: false,
  model: false,
  environment: false,
  output: false,
  display: false,
  mqtt: false,
  nodes: true,
})

function toggleSection(key: keyof typeof sections.value) {
  sections.value[key] = !sections.value[key]
}

// Computed cable loss
const cableLoss = computed(() => {
  const cable = store.cables[store.currentNode.cable_type]
  if (!cable) return 0
  return cable.loss_db_per_meter * store.currentNode.cable_length_m +
    cable.connector_loss_db * store.currentNode.connectors
})

const eirp = computed(() => {
  return store.currentNode.tx_power_dbm + store.currentNode.antenna_gain_dbi - cableLoss.value
})

const erpDbm = computed(() => eirp.value - 2.15)

// Colormap CSS gradients for preview
const COLORMAP_GRADIENTS: Record<string, string> = {
  plasma: 'linear-gradient(to right, rgb(13,8,135), rgb(126,3,168), rgb(204,71,120), rgb(248,149,64), rgb(240,249,33))',
  viridis: 'linear-gradient(to right, rgb(68,1,84), rgb(59,82,139), rgb(33,145,140), rgb(94,201,98), rgb(253,231,37))',
  inferno: 'linear-gradient(to right, rgb(0,0,4), rgb(87,16,110), rgb(188,55,84), rgb(249,142,9), rgb(252,255,164))',
  turbo: 'linear-gradient(to right, rgb(48,18,59), rgb(30,150,242), rgb(115,224,76), rgb(249,168,37), rgb(122,4,3))',
}

const currentGradient = computed(() => {
  return COLORMAP_GRADIENTS[store.displayParams.colormap] || COLORMAP_GRADIENTS.plasma
})

// Antenna radiation pattern SVG path (polar plot)
const antennaPatternPath = computed(() => {
  const ant = store.antennas[store.currentNode.antenna_preset]
  if (!ant) return ''
  const cx = 100, cy = 100, maxR = 80
  const hBw = ant.h_beamwidth
  const ftb = ant.front_to_back_db || 0
  const isOmni = hBw >= 360

  const points: string[] = []
  for (let deg = 0; deg < 360; deg += 2) {
    let gain = 1.0
    if (!isOmni) {
      // Approximate directional pattern
      let offset = Math.abs(deg)
      if (offset > 180) offset = 360 - offset
      const halfBw = hBw / 2
      if (offset <= halfBw) {
        gain = Math.cos((offset / halfBw) * Math.PI / 4) ** 2
      } else if (offset <= 90) {
        const ratio = (offset - halfBw) / (90 - halfBw)
        gain = Math.pow(10, -((12 + ratio * (ftb - 12)) / 20))
      } else {
        gain = Math.pow(10, -(ftb / 20))
      }
    }
    const r = maxR * Math.max(0.05, gain)
    const rad = (deg - 90) * Math.PI / 180
    const x = cx + r * Math.cos(rad + Math.PI / 2)
    const y = cy - r * Math.sin(rad + Math.PI / 2)
    points.push(`${deg === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`)
  }
  points.push('Z')
  return points.join(' ')
})

// Multi-site coverage: collect all selected node IDs
const multiSiteNodeIds = ref<Set<number>>(new Set())

function toggleMultiSiteNode(id: number) {
  if (multiSiteNodeIds.value.has(id)) {
    multiSiteNodeIds.value.delete(id)
  } else {
    multiSiteNodeIds.value.add(id)
  }
  // Force reactivity
  multiSiteNodeIds.value = new Set(multiSiteNodeIds.value)
}

function buildCoverageParams(node: any) {
  const ant = store.antennas[node.antenna_preset]
  return {
    tx_lat: node.lat,
    tx_lon: node.lon,
    tx_height_m: node.height_agl,
    tx_power_dbm: node.tx_power_dbm,
    tx_gain_dbi: node.antenna_gain_dbi,
    cable_loss_db: cableLoss.value,
    rx_gain_dbi: store.simParams.rx_gain_dbi,
    rx_sensitivity_dbm: node.rx_sensitivity_dbm,
    frequency_mhz: node.frequency_mhz,
    radius_km: store.simParams.radius_km,
    resolution_m: store.simParams.resolution_m,
    rx_height_m: store.simParams.rx_height_m,
    k_factor: store.simParams.k_factor,
    rain_rate_mmh: store.simParams.rain_rate_mmh,
    min_dbm: store.displayParams.min_dbm,
    max_dbm: store.displayParams.max_dbm,
    colormap: store.displayParams.colormap,
    antenna_azimuth_deg: node.antenna_azimuth_deg ?? 0,
    antenna_tilt_deg: node.antenna_tilt_deg ?? 0,
    antenna_h_beamwidth: ant?.h_beamwidth ?? 360,
    antenna_v_beamwidth: ant?.v_beamwidth ?? 90,
    antenna_front_to_back_db: ant?.front_to_back_db ?? 0,
  }
}

async function runCoverage() {
  if (!store.nodes.length) return
  const node = store.selectedNode || store.nodes[0]
  store.loading = true

  const controller = new AbortController()
  store.coverageAbort = controller

  try {
    store.coverageResult = await api.simulateCoverage(
      buildCoverageParams(node), controller.signal
    )
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      console.error('Coverage simulation failed:', err)
    }
  } finally {
    store.loading = false
    store.coverageAbort = null
  }
}

async function runMultiSiteCoverage() {
  const nodeIds = Array.from(multiSiteNodeIds.value)
  if (!nodeIds.length) return
  store.loading = true
  const controller = new AbortController()
  store.coverageAbort = controller

  try {
    // Run coverage for each selected node and keep the last result
    // (combined overlay shows all results on the map)
    for (const id of nodeIds) {
      const node = store.nodes.find(n => n.id === id)
      if (!node) continue
      store.coverageResult = await api.simulateCoverage(
        buildCoverageParams(node), controller.signal
      )
    }
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      console.error('Multi-site coverage failed:', err)
    }
  } finally {
    store.loading = false
    store.coverageAbort = null
  }
}

function exportKMZ() {
  const node = store.selectedNode || store.nodes[0]
  if (!node) return
  const ant = store.antennas[node.antenna_preset]
  const params = new URLSearchParams({
    tx_lat: String(node.lat),
    tx_lon: String(node.lon),
    tx_height_m: String(node.height_agl),
    tx_power_dbm: String(node.tx_power_dbm),
    tx_gain_dbi: String(node.antenna_gain_dbi),
    cable_loss_db: String(cableLoss.value),
    rx_gain_dbi: String(store.simParams.rx_gain_dbi),
    rx_sensitivity_dbm: String(node.rx_sensitivity_dbm),
    frequency_mhz: String(node.frequency_mhz),
    radius_km: String(store.simParams.radius_km),
    resolution_m: String(store.simParams.resolution_m),
    rx_height_m: String(store.simParams.rx_height_m),
    k_factor: String(store.simParams.k_factor),
    rain_rate_mmh: String(store.simParams.rain_rate_mmh),
    min_dbm: String(store.displayParams.min_dbm),
    max_dbm: String(store.displayParams.max_dbm),
    colormap: store.displayParams.colormap,
    site_name: node.name,
    format: 'kmz',
    antenna_azimuth_deg: String(node.antenna_azimuth_deg ?? 0),
    antenna_tilt_deg: String(node.antenna_tilt_deg ?? 0),
    antenna_h_beamwidth: String(ant?.h_beamwidth ?? 360),
    antenna_v_beamwidth: String(ant?.v_beamwidth ?? 90),
    antenna_front_to_back_db: String(ant?.front_to_back_db ?? 0),
  })
  window.open(`/api/export/kml/coverage?${params}`, '_blank')
}

function exportNodesKML() {
  window.open('/api/export/kml/nodes', '_blank')
}

function exportPNG() {
  if (!store.coverageResult?.image_base64) return
  const a = document.createElement('a')
  a.href = `data:image/png;base64,${store.coverageResult.image_base64}`
  a.download = 'coverage.png'
  a.click()
}

async function deleteSelectedNode() {
  if (store.selectedNodeId != null) {
    await store.deleteNode(store.selectedNodeId)
  }
}

const roles = ['CLIENT', 'CLIENT_MUTE', 'ROUTER', 'ROUTER_LATE', 'REPEATER']
const weatherOptions = [
  { label: 'Clear', rain: 0 },
  { label: 'Light Rain', rain: 5 },
  { label: 'Heavy Rain', rain: 25 },
  { label: 'Storm', rain: 50 },
  { label: 'Ice Storm', rain: 0 },
]
</script>

<template>
  <div class="sidebar" :class="{ collapsed: !store.sidebarOpen }">
    <div class="sidebar-header">
      <h1 v-if="store.sidebarOpen" class="logo">LoRa RF Sim</h1>
      <button class="toggle-btn" @click="store.sidebarOpen = !store.sidebarOpen">
        {{ store.sidebarOpen ? '\u25C0' : '\u25B6' }}
      </button>
    </div>

    <div v-if="store.sidebarOpen" class="sidebar-content">
      <!-- Selected Node Indicator -->
      <div v-if="store.selectedNodeId != null" class="selected-indicator">
        <span>Editing: <strong>{{ store.currentNode.name }}</strong></span>
        <button class="btn-new-node" @click="() => { store.selectedNodeId = null; Object.assign(store.currentNode, { id: undefined, name: 'Site', lat: 0, lon: 0, height_agl: 10, device_preset: 'rak4631', antenna_preset: 'rak_pcb_patch', cable_type: 'ideal', cable_length_m: 0, connectors: 0, frequency_mhz: 915, tx_power_dbm: 22, rx_sensitivity_dbm: -148, antenna_gain_dbi: 2.0, antenna_azimuth_deg: 0, antenna_tilt_deg: 0, role: 'CLIENT', channel_preset: 'LONG_FAST', notes: '' }) }">
          + New
        </button>
      </div>

      <!-- Site / TX Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('site')">
          <span class="section-icon">&#128205;</span>
          <span>Site / TX</span>
          <span class="chevron">{{ sections.site ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.site" class="section-body">
          <div class="field-row">
            <label>Name</label>
            <input v-model="store.currentNode.name" type="text" />
          </div>
          <div class="field-row">
            <label>Latitude</label>
            <input v-model.number="store.currentNode.lat" type="number" step="0.00001" />
          </div>
          <div class="field-row">
            <label>Longitude</label>
            <input v-model.number="store.currentNode.lon" type="number" step="0.00001" />
          </div>
          <div class="field-row">
            <label>Height AGL</label>
            <div class="input-unit">
              <input v-model.number="store.currentNode.height_agl" type="number" min="0" max="500" />
              <span class="unit">m</span>
            </div>
          </div>
          <div class="field-row">
            <label>Device</label>
            <select
              :value="store.currentNode.device_preset"
              @change="(e) => store.applyDevicePreset((e.target as HTMLSelectElement).value)"
            >
              <option v-for="(dev, key) in store.devices" :key="key" :value="key">
                {{ dev.name }}
              </option>
            </select>
          </div>
          <div class="field-row">
            <label>Role</label>
            <select v-model="store.currentNode.role">
              <option v-for="r in roles" :key="r" :value="r">{{ r }}</option>
            </select>
          </div>
          <div class="field-row">
            <label>Frequency</label>
            <div class="input-unit">
              <input v-model.number="store.currentNode.frequency_mhz" type="number" />
              <span class="unit">MHz</span>
            </div>
          </div>
          <div class="field-row">
            <label>TX Power</label>
            <div class="input-unit">
              <input v-model.number="store.currentNode.tx_power_dbm" type="number" />
              <span class="unit">dBm</span>
            </div>
          </div>
          <div class="field-row">
            <label>Channel</label>
            <select
              :value="store.currentNode.channel_preset"
              @change="(e) => store.applyChannelPreset((e.target as HTMLSelectElement).value)"
            >
              <option v-for="(ch, key) in store.channels" :key="key" :value="key">
                {{ ch.name }} (SF{{ ch.spreading_factor }}/{{ ch.bandwidth_khz }}kHz)
              </option>
            </select>
          </div>
          <div class="field-row">
            <label>Sensitivity</label>
            <div class="input-unit">
              <input v-model.number="store.currentNode.rx_sensitivity_dbm" type="number" />
              <span class="unit">dBm</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Feeder / Cable Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('feeder')">
          <span class="section-icon">&#8693;</span>
          <span>Feeder</span>
          <span class="chevron">{{ sections.feeder ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.feeder" class="section-body">
          <div class="field-row">
            <label>Cable Type</label>
            <select v-model="store.currentNode.cable_type">
              <option v-for="(cable, key) in store.cables" :key="key" :value="key">
                {{ cable.name }}
              </option>
            </select>
          </div>
          <div class="field-row">
            <label>Length</label>
            <div class="input-unit">
              <input v-model.number="store.currentNode.cable_length_m" type="number" min="0" max="50" step="0.5" />
              <span class="unit">m</span>
            </div>
          </div>
          <div class="field-row">
            <label>Connectors</label>
            <input v-model.number="store.currentNode.connectors" type="number" min="0" max="6" />
          </div>
          <div class="field-row computed">
            <label>Loss</label>
            <span class="value">{{ cableLoss.toFixed(2) }} dB</span>
          </div>
          <div class="field-row computed">
            <label>ERP</label>
            <span class="value">{{ erpDbm.toFixed(1) }} dBm</span>
          </div>
          <div class="field-row computed">
            <label>EIRP</label>
            <span class="value">{{ eirp.toFixed(1) }} dBm</span>
          </div>
        </div>
      </div>

      <!-- Antenna Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('antenna')">
          <span class="section-icon">&#128225;</span>
          <span>Antenna</span>
          <span class="chevron">{{ sections.antenna ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.antenna" class="section-body">
          <div class="field-row">
            <label>Preset</label>
            <select
              :value="store.currentNode.antenna_preset"
              @change="(e) => store.applyAntennaPreset((e.target as HTMLSelectElement).value)"
            >
              <option v-for="(ant, key) in store.antennas" :key="key" :value="key">
                {{ ant.name }}
              </option>
            </select>
          </div>
          <div class="field-row">
            <label>Gain</label>
            <div class="input-unit">
              <input v-model.number="store.currentNode.antenna_gain_dbi" type="number" step="0.1" />
              <span class="unit">dBi</span>
            </div>
          </div>
          <div v-if="store.antennas[store.currentNode.antenna_preset]" class="antenna-info">
            <div class="info-row">
              <span class="info-label">Type</span>
              <span>{{ store.antennas[store.currentNode.antenna_preset]?.type }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">Connector</span>
              <span>{{ store.antennas[store.currentNode.antenna_preset]?.connector }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">H Beamwidth</span>
              <span>{{ store.antennas[store.currentNode.antenna_preset]?.h_beamwidth }}&#176;</span>
            </div>
            <div class="info-row">
              <span class="info-label">V Beamwidth</span>
              <span>{{ store.antennas[store.currentNode.antenna_preset]?.v_beamwidth }}&#176;</span>
            </div>
          </div>
          <!-- Directional antenna controls -->
          <template v-if="store.antennas[store.currentNode.antenna_preset]?.type === 'directional'">
            <div class="field-row" style="margin-top: 8px;">
              <label>Azimuth</label>
              <div class="input-unit">
                <input v-model.number="store.currentNode.antenna_azimuth_deg" type="number" min="0" max="360" step="1" />
                <span class="unit">&#176;</span>
              </div>
            </div>
            <div class="field-row">
              <label>Tilt</label>
              <div class="input-unit">
                <input v-model.number="store.currentNode.antenna_tilt_deg" type="number" min="-30" max="30" step="1" />
                <span class="unit">&#176;</span>
              </div>
            </div>
            <div class="directional-hint">
              0&#176; = North, 90&#176; = East. Tilt: + up, - down
            </div>
          </template>
          <!-- Antenna Radiation Pattern Polar Plot -->
          <div v-if="store.antennas[store.currentNode.antenna_preset]" class="pattern-plot">
            <div class="pattern-title">Radiation Pattern (H-plane)</div>
            <svg viewBox="0 0 200 200" class="polar-svg">
              <!-- Grid circles -->
              <circle cx="100" cy="100" r="80" fill="none" stroke="#30363d" stroke-width="0.5" />
              <circle cx="100" cy="100" r="60" fill="none" stroke="#30363d" stroke-width="0.5" />
              <circle cx="100" cy="100" r="40" fill="none" stroke="#30363d" stroke-width="0.5" />
              <circle cx="100" cy="100" r="20" fill="none" stroke="#30363d" stroke-width="0.5" />
              <!-- Axis lines -->
              <line x1="100" y1="20" x2="100" y2="180" stroke="#30363d" stroke-width="0.5" />
              <line x1="20" y1="100" x2="180" y2="100" stroke="#30363d" stroke-width="0.5" />
              <!-- Cardinal labels -->
              <text x="100" y="14" text-anchor="middle" fill="#8b949e" font-size="9">N</text>
              <text x="100" y="196" text-anchor="middle" fill="#8b949e" font-size="9">S</text>
              <text x="188" y="104" text-anchor="middle" fill="#8b949e" font-size="9">E</text>
              <text x="12" y="104" text-anchor="middle" fill="#8b949e" font-size="9">W</text>
              <!-- Pattern -->
              <path :d="antennaPatternPath" fill="rgba(63,185,80,0.2)" stroke="#3fb950" stroke-width="1.5" />
              <!-- Azimuth direction indicator (for directional) -->
              <line v-if="store.antennas[store.currentNode.antenna_preset]?.type === 'directional'"
                :x1="100"
                :y1="100"
                :x2="100 + 85 * Math.sin(store.currentNode.antenna_azimuth_deg * Math.PI / 180)"
                :y2="100 - 85 * Math.cos(store.currentNode.antenna_azimuth_deg * Math.PI / 180)"
                stroke="#f85149" stroke-width="1.5" stroke-dasharray="4,3" />
            </svg>
          </div>
        </div>
      </div>

      <!-- Receiver Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('receiver')">
          <span class="section-icon">&#128225;</span>
          <span>Mobile / RX</span>
          <span class="chevron">{{ sections.receiver ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.receiver" class="section-body">
          <div class="field-row">
            <label>RX Height</label>
            <div class="input-unit">
              <input v-model.number="store.simParams.rx_height_m" type="number" min="0" step="0.5" />
              <span class="unit">m</span>
            </div>
          </div>
          <div class="field-row">
            <label>RX Gain</label>
            <div class="input-unit">
              <input v-model.number="store.simParams.rx_gain_dbi" type="number" step="0.1" />
              <span class="unit">dBi</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Model Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('model')">
          <span class="section-icon">&#9881;</span>
          <span>Model</span>
          <span class="chevron">{{ sections.model ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.model" class="section-body">
          <div class="field-row">
            <label>Propagation</label>
            <select v-model="store.simParams.model">
              <option value="fspl_diffraction">FSPL + Knife-Edge</option>
              <option value="itm" disabled>ITM (coming soon)</option>
              <option value="los">Line of Sight Only</option>
            </select>
          </div>
          <div class="field-row">
            <label>K-Factor</label>
            <input v-model.number="store.simParams.k_factor" type="number" step="0.01" min="0.5" max="2" />
          </div>
        </div>
      </div>

      <!-- Environment Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('environment')">
          <span class="section-icon">&#127795;</span>
          <span>Environment</span>
          <span class="chevron">{{ sections.environment ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.environment" class="section-body">
          <div class="field-row">
            <label>Profile</label>
            <select v-model="store.simParams.environment">
              <option value="temperate">Temperate</option>
              <option value="tropical">Tropical</option>
              <option value="desert">Desert</option>
              <option value="maritime">Maritime</option>
            </select>
          </div>
          <div class="field-row">
            <label>Weather</label>
            <select @change="(e) => store.simParams.rain_rate_mmh = weatherOptions.find(w => w.label === (e.target as HTMLSelectElement).value)?.rain ?? 0">
              <option v-for="w in weatherOptions" :key="w.label" :value="w.label">{{ w.label }}</option>
            </select>
          </div>
          <div class="field-row">
            <label>Noise Floor</label>
            <div class="input-unit">
              <input v-model.number="store.simParams.noise_floor_dbm" type="number" />
              <span class="unit">dBm</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Output Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('output')">
          <span class="section-icon">&#127912;</span>
          <span>Output</span>
          <span class="chevron">{{ sections.output ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.output" class="section-body">
          <div class="field-row">
            <label>Resolution</label>
            <select v-model.number="store.simParams.resolution_m">
              <option :value="30">30m</option>
              <option :value="60">60m</option>
              <option :value="90">90m</option>
              <option :value="180">180m</option>
              <option :value="300">300m</option>
            </select>
          </div>
          <div class="field-row">
            <label>Radius</label>
            <div class="input-unit">
              <input v-model.number="store.simParams.radius_km" type="number" min="1" max="50" step="1" />
              <span class="unit">km</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Display Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('display')">
          <span class="section-icon">&#127912;</span>
          <span>Display</span>
          <span class="chevron">{{ sections.display ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.display" class="section-body">
          <div class="field-row">
            <label>Min dBm</label>
            <div class="input-unit">
              <input v-model.number="store.displayParams.min_dbm" type="number" min="-170" max="-50" step="5" />
              <span class="unit">dBm</span>
            </div>
          </div>
          <div class="field-row">
            <label>Max dBm</label>
            <div class="input-unit">
              <input v-model.number="store.displayParams.max_dbm" type="number" min="-150" max="0" step="5" />
              <span class="unit">dBm</span>
            </div>
          </div>
          <div class="field-row">
            <label>Color Scale</label>
            <select v-model="store.displayParams.colormap">
              <option value="plasma">Plasma</option>
              <option value="viridis">Viridis</option>
              <option value="inferno">Inferno</option>
              <option value="turbo">Turbo</option>
            </select>
          </div>
          <div class="field-row">
            <label>Transparency</label>
            <div class="slider-row">
              <input
                type="range"
                v-model.number="store.displayParams.transparency"
                min="0"
                max="100"
                step="5"
                class="slider"
              />
              <span class="slider-value">{{ store.displayParams.transparency }}%</span>
            </div>
          </div>
          <div class="gradient-preview">
            <div class="gradient-bar" :style="{ background: currentGradient }"></div>
            <div class="gradient-labels">
              <span>{{ store.displayParams.min_dbm }}</span>
              <span>{{ Math.round((store.displayParams.min_dbm + store.displayParams.max_dbm) / 2) }}</span>
              <span>{{ store.displayParams.max_dbm }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="actions">
        <button class="btn-save" @click="store.saveNode({ ...store.currentNode })" :disabled="store.currentNode.lat === 0">
          {{ store.currentNode.id ? 'Update Node' : 'Save Node' }}
        </button>
        <button class="btn-run" @click="runCoverage" :disabled="!store.nodes.length || store.loading">
          Run Coverage
        </button>
      </div>

      <!-- Multi-site Coverage -->
      <div v-if="store.nodes.length > 1" class="actions">
        <button class="btn-multi" @click="runMultiSiteCoverage" :disabled="multiSiteNodeIds.size < 1 || store.loading">
          Multi-Site ({{ multiSiteNodeIds.size }})
        </button>
      </div>

      <!-- Coverage Stats -->
      <div v-if="store.coverageResult?.stats" class="coverage-stats">
        <div class="stats-row">
          <span class="stats-label">Cells</span>
          <span class="stats-value">{{ store.coverageResult.stats.cells_computed }} / {{ store.coverageResult.stats.cells_total }}</span>
        </div>
        <div class="stats-row">
          <span class="stats-label">Signal Range</span>
          <span class="stats-value">{{ store.coverageResult.stats.min_power_dbm }} to {{ store.coverageResult.stats.max_power_dbm }} dBm</span>
        </div>
        <div class="stats-row">
          <span class="stats-label">Mean</span>
          <span class="stats-value">{{ store.coverageResult.stats.mean_power_dbm }} dBm</span>
        </div>
        <div class="stats-row">
          <span class="stats-label">Compute Time</span>
          <span class="stats-value">{{ store.coverageResult.stats.elapsed_seconds }}s</span>
        </div>
      </div>

      <!-- Export Buttons -->
      <div class="actions export-actions">
        <button class="btn-export" @click="exportKMZ" :disabled="!store.nodes.length" title="Export coverage as KMZ for Google Earth">
          Export KMZ
        </button>
        <button class="btn-export" @click="exportNodesKML" :disabled="!store.nodes.length" title="Export nodes as KML">
          Nodes KML
        </button>
        <button class="btn-export" @click="exportPNG" :disabled="!store.coverageResult" title="Download coverage PNG">
          PNG
        </button>
      </div>

      <!-- MQTT Integration -->
      <div class="section">
        <div class="section-header" @click="toggleSection('mqtt')">
          <span class="section-icon">&#128225;</span>
          <span>MQTT</span>
          <span class="chevron">{{ sections.mqtt ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.mqtt" class="section-body">
          <div class="mqtt-badge">Coming Soon (Phase 3)</div>
          <div class="field-row">
            <label>Server URL</label>
            <input type="text" placeholder="mqtt://broker.example.com" disabled />
          </div>
          <div class="field-row">
            <label>Port</label>
            <input type="number" value="1883" disabled />
          </div>
          <div class="field-row">
            <label>Topic</label>
            <input type="text" value="meshtastic/#" disabled />
          </div>
          <div class="mqtt-info">
            Real-time node position and telemetry data from MQTT-connected Meshtastic devices will be available in Phase 3.
          </div>
        </div>
      </div>

      <!-- Node List -->
      <div class="section">
        <div class="section-header" @click="toggleSection('nodes')">
          <span class="section-icon">&#128203;</span>
          <span>Nodes ({{ store.nodes.length }})</span>
          <span class="chevron">{{ sections.nodes ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.nodes" class="section-body">
          <div
            v-for="node in store.nodes"
            :key="node.id"
            class="node-item"
            :class="{ selected: node.id === store.selectedNodeId }"
            @click="() => { store.selectedNodeId = node.id ?? null; Object.assign(store.currentNode, node) }"
          >
            <input
              v-if="store.nodes.length > 1"
              type="checkbox"
              class="multi-site-check"
              :checked="node.id != null && multiSiteNodeIds.has(node.id)"
              @click.stop="() => node.id && toggleMultiSiteNode(node.id)"
              title="Include in multi-site coverage"
            />
            <div class="node-name">{{ node.name }}</div>
            <div class="node-detail">
              {{ node.lat.toFixed(4) }}, {{ node.lon.toFixed(4) }} |
              {{ store.devices[node.device_preset]?.name || node.device_preset }}
            </div>
            <button class="node-delete" @click.stop="() => node.id && store.deleteNode(node.id)">&#10005;</button>
          </div>
          <div v-if="!store.nodes.length" class="empty-state">
            No nodes yet. Click "+ Node" on the map to add one.
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.2s;
}

.sidebar.collapsed {
  width: 0;
  border-right: none;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.logo {
  font-size: 16px;
  font-weight: 700;
  color: var(--accent-green);
  white-space: nowrap;
}

.toggle-btn {
  background: none;
  color: var(--text-secondary);
  padding: 4px 8px;
  font-size: 12px;
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding-bottom: 20px;
}

.section {
  border-bottom: 1px solid var(--border-color);
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  user-select: none;
}

.section-header:hover {
  background: var(--bg-tertiary);
}

.section-icon {
  font-size: 14px;
  width: 20px;
  text-align: center;
}

.chevron {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-muted);
}

.section-body {
  padding: 8px 16px 12px;
}

.field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  gap: 8px;
}

.field-row label {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 80px;
  flex-shrink: 0;
}

.field-row input,
.field-row select {
  flex: 1;
  min-width: 0;
  max-width: 180px;
}

.input-unit {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  max-width: 180px;
}

.input-unit input {
  flex: 1;
  min-width: 0;
}

.unit {
  font-size: 11px;
  color: var(--text-muted);
  min-width: 30px;
}

.field-row.computed {
  background: var(--bg-primary);
  padding: 6px 8px;
  border-radius: 4px;
  margin-bottom: 4px;
}

.field-row.computed .value {
  font-size: 13px;
  color: var(--accent-teal);
  font-weight: 500;
}

.antenna-info {
  background: var(--bg-primary);
  border-radius: 4px;
  padding: 8px;
  margin-top: 4px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 2px 0;
}

.info-label {
  color: var(--text-muted);
}

.slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  max-width: 180px;
}

.slider {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  outline: none;
  border: none;
  padding: 0;
}

.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent-green);
  cursor: pointer;
}

.slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent-green);
  cursor: pointer;
  border: none;
}

.slider-value {
  font-size: 11px;
  color: var(--text-muted);
  min-width: 32px;
  text-align: right;
}

.gradient-preview {
  margin-top: 8px;
  padding: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
}

.gradient-bar {
  height: 12px;
  border-radius: 3px;
  margin-bottom: 4px;
}

.gradient-labels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-muted);
}

.actions {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.btn-save {
  flex: 1;
  background: var(--accent-blue);
  color: #fff;
  padding: 10px;
  font-weight: 600;
}

.btn-run {
  flex: 1;
  background: var(--accent-green);
  color: #000;
  padding: 10px;
  font-weight: 600;
}

.coverage-stats {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-primary);
}

.stats-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 3px 0;
}

.stats-label {
  color: var(--text-muted);
}

.stats-value {
  color: var(--accent-teal);
  font-weight: 500;
}

.node-item {
  padding: 8px 10px 8px 20px;
  border-radius: 4px;
  cursor: pointer;
  position: relative;
  margin-bottom: 4px;
}

.node-item:hover {
  background: var(--bg-tertiary);
}

.node-item.selected {
  background: var(--bg-tertiary);
  border-left: 3px solid var(--accent-green);
}

.node-name {
  font-size: 13px;
  font-weight: 500;
}

.node-detail {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.node-delete {
  position: absolute;
  top: 8px;
  right: 8px;
  background: none;
  color: var(--text-muted);
  padding: 2px 6px;
  font-size: 12px;
}

.node-delete:hover {
  color: var(--accent-red);
}

.empty-state {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 16px;
}

.selected-indicator {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: rgba(63, 185, 80, 0.1);
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
  color: var(--accent-green);
}

.btn-new-node {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  padding: 4px 10px;
  font-size: 11px;
  border: 1px solid var(--border-color);
}

.directional-hint {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
  margin-bottom: 4px;
}

.pattern-plot {
  margin-top: 8px;
  padding: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
}

.pattern-title {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
  text-align: center;
}

.polar-svg {
  width: 100%;
  max-width: 180px;
  display: block;
  margin: 0 auto;
}

.btn-multi {
  flex: 1;
  background: var(--accent-blue);
  color: #fff;
  padding: 10px;
  font-weight: 600;
}

.export-actions {
  flex-wrap: wrap;
}

.btn-export {
  flex: 1;
  min-width: 70px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  padding: 8px 10px;
  font-size: 12px;
  font-weight: 500;
}

.btn-export:hover:not(:disabled) {
  background: var(--accent-teal);
  color: #000;
}

.btn-export:disabled {
  opacity: 0.4;
}

.mqtt-badge {
  background: rgba(136, 136, 136, 0.15);
  color: var(--text-muted);
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  text-align: center;
  margin-bottom: 8px;
}

.mqtt-info {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 8px;
  line-height: 1.4;
}

.multi-site-check {
  position: absolute;
  left: 2px;
  top: 50%;
  transform: translateY(-50%);
  width: 14px;
  height: 14px;
  cursor: pointer;
  accent-color: var(--accent-green);
}

@media (max-width: 900px) {
  .sidebar {
    width: 100%;
    height: auto;
    max-height: 50vh;
    border-right: none;
    border-bottom: 1px solid var(--border-color);
  }

  .sidebar.collapsed {
    width: 100%;
    max-height: 0;
  }
}
</style>
