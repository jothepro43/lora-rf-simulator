const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

async function downloadBlob(path: string, filename: string, options?: RequestInit): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export const api = {
  // Data catalogs
  getDevices: () => request<Record<string, any>>('/data/devices'),
  getAntennas: () => request<Record<string, any>>('/data/antennas'),
  getCables: () => request<Record<string, any>>('/data/cables'),
  getChannels: () => request<Record<string, any>>('/data/channels'),

  // Custom devices
  addCustomDevice: (device: any) =>
    request<any>('/data/devices/custom', { method: 'POST', body: JSON.stringify(device) }),
  deleteCustomDevice: (key: string) =>
    request<any>(`/data/devices/custom/${encodeURIComponent(key)}`, { method: 'DELETE' }),

  // Nodes
  listNodes: () => request<any[]>('/nodes'),
  createNode: (node: any) => request<any>('/nodes', { method: 'POST', body: JSON.stringify(node) }),
  updateNode: (id: number, data: any) => request<any>(`/nodes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteNode: (id: number) => request<any>(`/nodes/${id}`, { method: 'DELETE' }),

  // Terrain
  getElevation: (lat: number, lon: number) => request<any>(`/terrain/elevation?lat=${lat}&lon=${lon}`),

  // Simulation
  simulateLos: (data: any) => request<any>('/simulate/los', { method: 'POST', body: JSON.stringify(data) }),
  simulateCoverage: (data: any, signal?: AbortSignal) =>
    request<any>('/simulate/coverage', { method: 'POST', body: JSON.stringify(data), signal }),
  simulateMultiCoverage: (data: any, signal?: AbortSignal) =>
    request<any>('/simulate/coverage/multi', { method: 'POST', body: JSON.stringify(data), signal }),
  simulateLinkBudget: (data: any) => request<any>('/simulate/link-budget', { method: 'POST', body: JSON.stringify(data) }),

  // Precompute
  precompute: (data: any) => request<any>('/simulate/precompute', { method: 'POST', body: JSON.stringify(data) }),
  listPrecomputed: () => request<any[]>('/simulate/precompute'),
  getPrecomputed: (name: string) => request<any>(`/simulate/precompute/${encodeURIComponent(name)}`),
  deletePrecomputed: (name: string) => request<any>(`/simulate/precompute/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // Export
  exportCoverageKmz: (data: any, filename: string = 'coverage.kmz') =>
    downloadBlob('/export/kml/coverage', filename, { method: 'POST', body: JSON.stringify(data) }),
  exportNodesKml: () =>
    downloadBlob('/export/kml/nodes', 'nodes.kml'),

  // MQTT
  getMqttConfig: () => request<any>('/mqtt/config'),
  updateMqttConfig: (config: any) => request<any>('/mqtt/config', { method: 'POST', body: JSON.stringify(config) }),
  getMqttStatus: () => request<any>('/mqtt/status'),
}
