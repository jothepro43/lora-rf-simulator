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
        <button class="btn-new-node" @click="() => { store.selectedNodeId = null; Object.assign(store.currentNode, { id: undefined, name: 'Site', lat: 0, lon: 0, height_agl: 10, device_preset: 'rak4631', antenna_preset: 'rak_pcb_patch', cable_type: 'ideal', cable_length_m: 0, connectors: 0, frequency_mhz: 915, tx_power_dbm: 22, rx_sensitivity_dbm: -148, antenna_gain_dbi: 2.0, role: 'CLIENT', channel_preset: 'LONG_FAST', notes: '' }) }">
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
