import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { NodeData, DevicePreset, AntennaPreset, CablePreset, ChannelPreset, LosResult, CoverageResult } from './types'
import { api } from './utils/api'

export const useStore = defineStore('main', () => {
  // Data catalogs
  const devices = ref<Record<string, DevicePreset>>({})
  const antennas = ref<Record<string, AntennaPreset>>({})
  const cables = ref<Record<string, CablePreset>>({})
  const channels = ref<Record<string, ChannelPreset>>({})

  // Nodes
  const nodes = ref<NodeData[]>([])
  const selectedNodeId = ref<number | null>(null)

  // UI state
  const sidebarOpen = ref(true)
  const activeMode = ref<'place' | 'los' | 'coverage' | 'none'>('none')
  const losPoints = ref<{ lat: number; lon: number }[]>([])
  const losResult = ref<LosResult | null>(null)
  const coverageResult = ref<CoverageResult | null>(null)
  const loading = ref(false)
  const terrainProfileOpen = ref(false)

  // Current node being edited
  const currentNode = ref<NodeData>({
    name: 'Site',
    lat: 0,
    lon: 0,
    height_agl: 10,
    device_preset: 'rak4631',
    antenna_preset: 'rak_pcb_patch',
    cable_type: 'ideal',
    cable_length_m: 0,
    connectors: 0,
    frequency_mhz: 915,
    tx_power_dbm: 22,
    rx_sensitivity_dbm: -148,
    antenna_gain_dbi: 2.0,
    role: 'CLIENT',
    channel_preset: 'LONG_FAST',
    notes: '',
  })

  // Simulation parameters
  const simParams = ref({
    radius_km: 5,
    resolution_m: 180,
    rx_height_m: 1.5,
    rx_gain_dbi: 2.0,
    k_factor: 1.333,
    rain_rate_mmh: 0,
    model: 'fspl_diffraction',
    environment: 'temperate',
    noise_floor_dbm: -120,
  })

  const selectedNode = computed(() =>
    nodes.value.find(n => n.id === selectedNodeId.value) || null
  )

  async function loadCatalogs() {
    const [d, a, c, ch] = await Promise.all([
      api.getDevices(),
      api.getAntennas(),
      api.getCables(),
      api.getChannels(),
    ])
    devices.value = d
    antennas.value = a
    cables.value = c
    channels.value = ch
  }

  async function loadNodes() {
    nodes.value = await api.listNodes()
  }

  async function saveNode(node: NodeData) {
    if (node.id) {
      const updated = await api.updateNode(node.id, node)
      const idx = nodes.value.findIndex(n => n.id === node.id)
      if (idx >= 0) nodes.value[idx] = updated
    } else {
      const created = await api.createNode(node)
      nodes.value.push(created)
    }
  }

  async function deleteNode(id: number) {
    await api.deleteNode(id)
    nodes.value = nodes.value.filter(n => n.id !== id)
    if (selectedNodeId.value === id) selectedNodeId.value = null
  }

  function applyDevicePreset(presetKey: string) {
    const device = devices.value[presetKey]
    if (device) {
      currentNode.value.device_preset = presetKey
      currentNode.value.tx_power_dbm = device.tx_power_dbm
      currentNode.value.rx_sensitivity_dbm = device.rx_sensitivity_dbm
    }
  }

  function applyAntennaPreset(presetKey: string) {
    const antenna = antennas.value[presetKey]
    if (antenna) {
      currentNode.value.antenna_preset = presetKey
      currentNode.value.antenna_gain_dbi = antenna.gain_dbi
    }
  }

  function applyChannelPreset(presetKey: string) {
    const channel = channels.value[presetKey]
    if (channel) {
      currentNode.value.channel_preset = presetKey
      // Channel affects sensitivity — update if using default device sensitivity
      currentNode.value.rx_sensitivity_dbm = channel.sensitivity_dbm
    }
  }

  return {
    devices, antennas, cables, channels,
    nodes, selectedNodeId, selectedNode,
    sidebarOpen, activeMode, losPoints, losResult, coverageResult,
    loading, terrainProfileOpen,
    currentNode, simParams,
    loadCatalogs, loadNodes, saveNode, deleteNode,
    applyDevicePreset, applyAntennaPreset, applyChannelPreset,
  }
})
