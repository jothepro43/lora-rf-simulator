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

export const api = {
  // Data catalogs
  getDevices: () => request<Record<string, any>>('/data/devices'),
  getAntennas: () => request<Record<string, any>>('/data/antennas'),
  getCables: () => request<Record<string, any>>('/data/cables'),
  getChannels: () => request<Record<string, any>>('/data/channels'),

  // Nodes
  listNodes: () => request<any[]>('/nodes'),
  createNode: (node: any) => request<any>('/nodes', { method: 'POST', body: JSON.stringify(node) }),
  updateNode: (id: number, data: any) => request<any>(`/nodes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteNode: (id: number) => request<any>(`/nodes/${id}`, { method: 'DELETE' }),

  // Terrain
  getElevation: (lat: number, lon: number) => request<any>(`/terrain/elevation?lat=${lat}&lon=${lon}`),

  // Simulation
  simulateLos: (data: any) => request<any>('/simulate/los', { method: 'POST', body: JSON.stringify(data) }),
  simulateCoverage: (data: any) => request<any>('/simulate/coverage', { method: 'POST', body: JSON.stringify(data) }),
  simulateLinkBudget: (data: any) => request<any>('/simulate/link-budget', { method: 'POST', body: JSON.stringify(data) }),
}
