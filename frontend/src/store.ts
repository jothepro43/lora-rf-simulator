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
  const panRequest = ref<{ lat: number; lon: number } | null>(null)
  const sidebarOpen = ref(true)
  const activeMode = ref<'place' | 'los' | 'link' | 'coverage' | 'none'>('none')
  const linkStartNodeId = ref<number | null>(null)
  const losPoints = ref<{ lat: number; lon: number }[]>([])
  const losResult = ref<LosResult | null>(null)
  const coverageResult = ref<CoverageResult | null>(null)
  const loading = ref(false)
  const terrainProfileOpen = ref(false)
  const coverageAbort = ref<AbortController | null>(null)

  // LoS interactive profile state
  const losHoverPoint = ref<{
    lat: number; lon: number; distance_km: number; elevation_m: number; index: number
  } | null>(null)
  const losInspectPoint = ref<{
    lat: number; lon: number; elevation_m: number; los_height_m: number;
    is_obstruction: boolean; distance_km: number; intrusion_m: number
  } | null>(null)

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
    antenna_azimuth_deg: 0,
    antenna_tilt_deg: 0,
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
    model: 'terrain',
    environment: 'temperate',
    noise_floor_dbm: -120,
    // ITM (Longley-Rice) parameters
    itm_reliability_pct: 90,
    itm_radio_climate: 5,
    itm_ground_eps: 15.0,
    itm_ground_sigma: 0.005,
    itm_polarization: 1,
    // Clutter / foliage attenuation (ITU-R P.833)
    clutter_profile: 'temperate_forest' as string,
    clutter_tree_height_m: null as number | null,
    clutter_tree_density: null as number | null,
  })

  // Display parameters
  const displayParams = ref({
    min_dbm: -130,
    max_dbm: -80,
    colormap: 'plasma' as string,
    transparency: 50,
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

  function cancelCoverage() {
    if (coverageAbort.value) {
      coverageAbort.value.abort()
      coverageAbort.value = null
      loading.value = false
    }
  }

  async function runNodeToNodeLos(nodeId1: number, nodeId2: number) {
    const n1 = nodes.value.find(n => n.id === nodeId1)
    const n2 = nodes.value.find(n => n.id === nodeId2)
    if (!n1 || !n2) return

    losPoints.value = [
      { lat: n1.lat, lon: n1.lon },
      { lat: n2.lat, lon: n2.lon },
    ]

    loading.value = true
    try {
      const result = await api.simulateLos({
        tx_lat: n1.lat,
        tx_lon: n1.lon,
        tx_height_m: n1.height_agl,
        rx_lat: n2.lat,
        rx_lon: n2.lon,
        rx_height_m: n2.height_agl,
        frequency_mhz: n1.frequency_mhz,
        num_points: 200,
        k_factor: simParams.value.k_factor,
      })
      losResult.value = result
      terrainProfileOpen.value = true
    } catch (err) {
      console.error('Node-to-Node LoS failed:', err)
    } finally {
      loading.value = false
    }
  }

  async function addCustomDevice(device: Record<string, any>) {
    const created = await api.addCustomDevice(device)
    // Refresh devices catalog
    devices.value = await api.getDevices()
    return created
  }

  async function updateCustomDevice(key: string, device: Record<string, any>) {
    const updated = await api.updateCustomDevice(key, device)
    devices.value = await api.getDevices()
    return updated
  }

  async function deleteCustomDevice(key: string) {
    await api.deleteCustomDevice(key)
    devices.value = await api.getDevices()
  }

  // ---- Network Links ----
  const networkLinks = ref<any[]>([])

  // ---- Routing / multi-hop path ----
  type PathObjective = 'hops' | 'lowest_total_loss' | 'best_bottleneck_margin'
  const pathQuery = ref<{
    source_id: number | null
    dest_id: number | null
    objective: PathObjective
    max_hops: number | null
    min_margin_db: number | null
    allow_unanalyzed: boolean
  }>({
    source_id: null,
    dest_id: null,
    objective: 'hops',
    max_hops: null,
    min_margin_db: null,
    allow_unanalyzed: false,
  })
  const pathResult = ref<any | null>(null)
  const pathLoading = ref(false)

  async function loadLinks() {
    try { networkLinks.value = await api.listLinks() } catch { networkLinks.value = [] }
  }

  async function createLink(node1Id: number, node2Id: number) {
    await api.createLink({ node1_id: node1Id, node2_id: node2Id })
    await loadLinks()
  }

  async function deleteLink(id: number) {
    await api.deleteLink(id)
    await loadLinks()
  }

  async function deleteAllLinks() {
    await api.deleteAllLinks()
    await loadLinks()
  }

  async function analyzeAllLinks() {
    const results = await api.analyzeLinks()
    await loadLinks()
    return results
  }

  async function autoDiscoverLinks(maxDistKm: number = 50) {
    await api.autoDiscoverLinks(maxDistKm)
    await loadLinks()
  }

  async function findPath() {
    if (pathQuery.value.source_id == null || pathQuery.value.dest_id == null) {
      pathResult.value = { found: false, reason: 'Pick source and destination nodes.' }
      return
    }
    if (pathQuery.value.source_id === pathQuery.value.dest_id) {
      pathResult.value = { found: false, reason: 'Source and destination must differ.' }
      return
    }
    pathLoading.value = true
    try {
      pathResult.value = await api.findPath({
        source_id: pathQuery.value.source_id,
        dest_id: pathQuery.value.dest_id,
        objective: pathQuery.value.objective,
        max_hops: pathQuery.value.max_hops ?? undefined,
        min_margin_db: pathQuery.value.min_margin_db ?? undefined,
        allow_unanalyzed: pathQuery.value.allow_unanalyzed,
      })
    } catch (err: any) {
      pathResult.value = { found: false, reason: err?.message || String(err) }
    } finally {
      pathLoading.value = false
    }
  }

  function clearPath() {
    pathResult.value = null
  }

  return {
    devices, antennas, cables, channels,
    nodes, selectedNodeId, selectedNode,
    panRequest, sidebarOpen, activeMode, losPoints, losResult, coverageResult,
    loading, terrainProfileOpen, coverageAbort, losHoverPoint, losInspectPoint,
    currentNode, simParams, displayParams,
    loadCatalogs, loadNodes, saveNode, deleteNode,
    applyDevicePreset, applyAntennaPreset, applyChannelPreset,
    cancelCoverage, runNodeToNodeLos,
    addCustomDevice, updateCustomDevice, deleteCustomDevice,
    networkLinks, linkStartNodeId, loadLinks, createLink, deleteLink,
    deleteAllLinks, analyzeAllLinks, autoDiscoverLinks,
    pathQuery, pathResult, pathLoading, findPath, clearPath,
  }
})
