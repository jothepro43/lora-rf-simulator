<script setup lang="ts">
import { ref, computed } from 'vue'
import { useStore } from '../store'
import { api } from '../utils/api'
import AntennaPattern from './AntennaPattern.vue'

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
  precomputed: false,
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

async function runCoverage() {
  if (!store.nodes.length) return
  const node = store.selectedNode || store.nodes[0]
  store.loading = true

  // Create abort controller
  const controller = new AbortController()
  store.coverageAbort = controller

  // Get antenna directional params
  const antenna = store.antennas[node.antenna_preset]

  try {
    store.coverageResult = await api.simulateCoverage({
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
      antenna_h_beamwidth: antenna?.h_beamwidth ?? 360,
      antenna_v_beamwidth: antenna?.v_beamwidth ?? 90,
      antenna_front_to_back_db: antenna?.front_to_back_db ?? 0,
      model: store.simParams.model,
    }, controller.signal)
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      console.error('Coverage simulation failed:', err)
    }
  } finally {
    store.loading = false
    store.coverageAbort = null
  }
}

async function runMultiCoverage() {
  if (store.nodes.length < 2) return
  store.loading = true
  const controller = new AbortController()
  store.coverageAbort = controller

  try {
    const nodeRequests = store.nodes.map(node => {
      const antenna = store.antennas[node.antenna_preset]
      const cable = store.cables[node.cable_type]
      const nodeCableLoss = cable
        ? cable.loss_db_per_meter * (node.cable_length_m || 0) + cable.connector_loss_db * (node.connectors || 0)
        : 0
      return {
        tx_lat: node.lat,
        tx_lon: node.lon,
        tx_height_m: node.height_agl,
        tx_power_dbm: node.tx_power_dbm,
        tx_gain_dbi: node.antenna_gain_dbi,
        cable_loss_db: nodeCableLoss,
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
        antenna_h_beamwidth: antenna?.h_beamwidth ?? 360,
        antenna_v_beamwidth: antenna?.v_beamwidth ?? 90,
        antenna_front_to_back_db: antenna?.front_to_back_db ?? 0,
        model: store.simParams.model,
      }
    })
    store.coverageResult = await api.simulateMultiCoverage(
      { nodes: nodeRequests, combine_mode: 'best' },
      controller.signal,
    )
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      console.error('Multi-coverage simulation failed:', err)
    }
  } finally {
    store.loading = false
    store.coverageAbort = null
  }
}

async function deleteSelectedNode() {
  if (store.selectedNodeId != null) {
    await store.deleteNode(store.selectedNodeId)
  }
}

const precomputedList = ref<any[]>([])
const precomputeName = ref('')

async function loadPrecomputed() {
  precomputedList.value = await api.listPrecomputed()
}

async function runPrecompute() {
  if (!store.nodes.length || !precomputeName.value) return
  const node = store.selectedNode || store.nodes[0]
  const antenna = store.antennas[node.antenna_preset]
  store.loading = true
  try {
    await api.precompute({
      name: precomputeName.value,
      coverage: {
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
        antenna_h_beamwidth: antenna?.h_beamwidth ?? 360,
        antenna_v_beamwidth: antenna?.v_beamwidth ?? 90,
        antenna_front_to_back_db: antenna?.front_to_back_db ?? 0,
        model: store.simParams.model,
      },
    })
    await loadPrecomputed()
    precomputeName.value = ''
  } catch (err) {
    console.error('Precompute failed:', err)
  } finally {
    store.loading = false
  }
}

async function loadPrecomputedResult(name: string) {
  store.coverageResult = await api.getPrecomputed(name)
}

async function deletePrecomputed(name: string) {
  await api.deletePrecomputed(name)
  await loadPrecomputed()
}

const mqttConfig = ref({
  server_url: '',
  port: 1883,
  topic: 'meshtastic/#',
  username: '',
  password: '',
  enabled: false,
})

async function exportCoverageKmz() {
  if (!store.nodes.length) return
  const node = store.selectedNode || store.nodes[0]
  const antenna = store.antennas[node.antenna_preset]
  await api.exportCoverageKmz({
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
    antenna_h_beamwidth: antenna?.h_beamwidth ?? 360,
    antenna_v_beamwidth: antenna?.v_beamwidth ?? 90,
    antenna_front_to_back_db: antenna?.front_to_back_db ?? 0,
    model: store.simParams.model,
    site_name: node.name,
  }, `coverage_${node.name}.kmz`)
}

function exportCoveragePng() {
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

async function saveMqttConfig() {
  await api.updateMqttConfig(mqttConfig.value)
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
          <!-- Directional antenna controls -->
          <template v-if="store.antennas[store.currentNode.antenna_preset]?.type === 'directional'">
            <div class="field-row">
              <label>Azimuth</label>
              <div class="input-unit">
                <input v-model.number="store.currentNode.antenna_azimuth_deg" type="number" min="0" max="360" step="1" />
                <span class="unit">deg</span>
              </div>
            </div>
            <div class="field-row">
              <label>Tilt</label>
              <div class="input-unit">
                <input v-model.number="store.currentNode.antenna_tilt_deg" type="number" min="-30" max="30" step="0.5" />
                <span class="unit">deg</span>
              </div>
            </div>
          </template>
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
            <div v-if="store.antennas[store.currentNode.antenna_preset]?.front_to_back_db > 0" class="info-row">
              <span class="info-label">F/B Ratio</span>
              <span>{{ store.antennas[store.currentNode.antenna_preset]?.front_to_back_db }} dB</span>
            </div>
          </div>
          <AntennaPattern
            v-if="store.antennas[store.currentNode.antenna_preset]"
            :h-beamwidth="store.antennas[store.currentNode.antenna_preset]?.h_beamwidth ?? 360"
            :v-beamwidth="store.antennas[store.currentNode.antenna_preset]?.v_beamwidth ?? 90"
            :gain="store.currentNode.antenna_gain_dbi"
            :front-to-back="store.antennas[store.currentNode.antenna_preset]?.front_to_back_db ?? 0"
            :azimuth="store.currentNode.antenna_azimuth_deg"
            :type="store.antennas[store.currentNode.antenna_preset]?.type ?? 'omnidirectional'"
          />
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
              <option value="terrain">Full (Terrain)</option>
              <option value="fspl">Quick (FSPL only)</option>
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
        <button
          v-if="store.nodes.length >= 2"
          class="btn-multi"
          @click="runMultiCoverage"
          :disabled="store.loading"
          title="Run coverage from all nodes"
        >
          All Sites
        </button>
      </div>

      <!-- Export Buttons -->
      <div class="actions export-actions">
        <button class="btn-export" @click="exportCoverageKmz" :disabled="!store.nodes.length" title="Export coverage as KMZ for Google Earth">
          Export KMZ
        </button>
        <button class="btn-export" @click="exportCoveragePng" :disabled="!store.coverageResult?.image_base64" title="Download coverage PNG">
          Export PNG
        </button>
        <button class="btn-export" @click="api.exportNodesKml()" :disabled="!store.nodes.length" title="Export nodes as KML">
          Nodes KML
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

      <!-- Pre-computed Section -->
      <div class="section">
        <div class="section-header" @click="() => { toggleSection('precomputed'); if (sections.precomputed) loadPrecomputed() }">
          <span class="section-icon">&#128190;</span>
          <span>Pre-computed</span>
          <span class="chevron">{{ sections.precomputed ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.precomputed" class="section-body">
          <div class="field-row">
            <label>Name</label>
            <input v-model="precomputeName" type="text" placeholder="e.g. hilltop-5km" />
          </div>
          <button class="btn-mqtt-save" @click="runPrecompute" :disabled="!precomputeName || !store.nodes.length || store.loading">
            Pre-compute
          </button>
          <div v-if="precomputedList.length" class="precompute-list">
            <div
              v-for="item in precomputedList"
              :key="item.name"
              class="node-item"
              @click="loadPrecomputedResult(item.name)"
            >
              <div class="node-name">{{ item.name }}</div>
              <div class="node-detail">
                {{ item.stats?.cells_computed || 0 }} cells | {{ item.compute_time_s }}s
              </div>
              <button class="node-delete" @click.stop="deletePrecomputed(item.name)">&#10005;</button>
            </div>
          </div>
          <div v-else class="empty-state">
            No pre-computed results yet.
          </div>
        </div>
      </div>

      <!-- MQTT Section -->
      <div class="section">
        <div class="section-header" @click="toggleSection('mqtt')">
          <span class="section-icon">&#128225;</span>
          <span>MQTT</span>
          <span class="chevron">{{ sections.mqtt ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div v-if="sections.mqtt" class="section-body">
          <div class="mqtt-notice">MQTT Integration (Coming Soon)</div>
          <div class="field-row">
            <label>Server URL</label>
            <input v-model="mqttConfig.server_url" type="text" placeholder="mqtt://broker.example.com" />
          </div>
          <div class="field-row">
            <label>Port</label>
            <input v-model.number="mqttConfig.port" type="number" min="1" max="65535" />
          </div>
          <div class="field-row">
            <label>Topic</label>
            <input v-model="mqttConfig.topic" type="text" placeholder="meshtastic/#" />
          </div>
          <div class="field-row">
            <label>Username</label>
            <input v-model="mqttConfig.username" type="text" placeholder="optional" />
          </div>
          <div class="field-row">
            <label>Enabled</label>
            <input type="checkbox" v-model="mqttConfig.enabled" style="width:auto;" />
          </div>
          <button class="btn-mqtt-save" @click="saveMqttConfig" :disabled="!mqttConfig.server_url">
            Save Config
          </button>
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

.btn-multi {
  background: var(--accent-teal, #39d2c0);
  color: #000;
  padding: 10px;
  font-weight: 600;
  font-size: 12px;
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
  padding: 8px 10px;
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

.export-actions {
  flex-wrap: wrap;
}

.btn-export {
  flex: 1;
  min-width: 70px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  padding: 8px;
  font-weight: 500;
  font-size: 12px;
  border: 1px solid var(--border-color);
}

.btn-export:hover:not(:disabled) {
  background: var(--accent-blue);
  color: #fff;
  border-color: var(--accent-blue);
}

.btn-export:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.mqtt-notice {
  background: rgba(88, 166, 255, 0.1);
  color: var(--accent-blue);
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  text-align: center;
  margin-bottom: 10px;
  border: 1px solid rgba(88, 166, 255, 0.2);
}

.btn-mqtt-save {
  width: 100%;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  padding: 8px;
  font-size: 12px;
  border: 1px solid var(--border-color);
  margin-top: 4px;
}

.btn-mqtt-save:hover:not(:disabled) {
  background: var(--accent-blue);
  color: #fff;
}

.btn-mqtt-save:disabled {
  opacity: 0.4;
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
