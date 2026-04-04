export interface DevicePreset {
  name: string
  manufacturer: string
  radio: string
  tx_power_dbm: number
  rx_sensitivity_dbm: number
  frequency_range: string
  connector: string
  power_consumption_tx_ma: number
  power_consumption_rx_ma: number
  protocols: string[]
}

export interface AntennaPreset {
  name: string
  manufacturer: string
  type: string
  gain_dbi: number
  frequency: string
  connector: string
  polarization: string
  h_beamwidth: number
  v_beamwidth: number
  front_to_back_db: number
}

export interface CablePreset {
  name: string
  loss_db_per_meter: number
  frequency_mhz: number
  connector_loss_db: number
  description: string
}

export interface ChannelPreset {
  name: string
  spreading_factor: number
  bandwidth_khz: number
  coding_rate: string
  sensitivity_dbm: number
  data_rate_bps: number
  max_payload_bytes: number
  description: string
}

export interface NodeData {
  id?: number
  name: string
  lat: number
  lon: number
  height_agl: number
  device_preset: string
  antenna_preset: string
  cable_type: string
  cable_length_m: number
  connectors: number
  frequency_mhz: number
  tx_power_dbm: number
  rx_sensitivity_dbm: number
  antenna_gain_dbi: number
  antenna_azimuth_deg: number
  antenna_tilt_deg: number
  role: string
  channel_preset: string
  notes: string
}

export interface LosResult {
  distances: number[]
  elevations: number[]
  lats: number[]
  lons: number[]
  total_distance_m: number
  los_heights: number[]
  fresnel_60pct_top: number[]
  fresnel_60pct_bottom: number[]
  earth_curvature: number[]
  obstructions: Obstruction[]
  clearance_pct: number
  is_los: boolean
  tx_height_asl: number
  rx_height_asl: number
  path_loss: PathLoss
}

export interface Obstruction {
  index: number
  distance_m: number
  elevation_m: number
  los_height_m: number
  obstruction_m: number
  lat: number
  lon: number
}

export interface PathLoss {
  total_path_loss_db: number
  fspl_db: number
  diffraction_db: number
  weather_db: number
  distance_m: number
}

export interface CoverageResult {
  image_base64: string
  bounds: [[number, number], [number, number]]
  stats: CoverageStats
  resolution_m: number
  radius_km: number
  eirp_dbm: number
  tx_lat: number
  tx_lon: number
  min_dbm: number
  max_dbm: number
  colormap: string
}

export interface CoverageStats {
  min_power_dbm: number
  max_power_dbm: number
  mean_power_dbm: number
  cells_computed: number
  cells_total: number
  elapsed_seconds: number
}

export interface LinkBudgetResult {
  tx_power_dbm: number
  tx_power_w: number
  cable_loss_db: number
  tx_gain_dbi: number
  erp_dbm: number
  erp_w: number
  eirp_dbm: number
  eirp_w: number
  fspl_db: number
  diffraction_db: number
  weather_db: number
  total_path_loss_db: number
  rx_gain_dbi: number
  rx_power_dbm: number
  rx_sensitivity_dbm: number
  margin_db: number
  link_viable: boolean
}
