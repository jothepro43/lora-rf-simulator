<script setup lang="ts">
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import { useStore } from '../store'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

const store = useStore()
const canvasRef = ref<HTMLCanvasElement>()
let chartInstance: Chart | null = null

function renderChart() {
  if (!canvasRef.value || !store.losResult) return

  if (chartInstance) {
    chartInstance.destroy()
  }

  const result = store.losResult
  const labels = result.distances.map((d: number) => (d / 1000).toFixed(2))

  chartInstance = new Chart(canvasRef.value, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Terrain',
          data: result.elevations,
          borderColor: '#8b6914',
          backgroundColor: 'rgba(139, 105, 20, 0.3)',
          fill: true,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.1,
        },
        {
          label: 'Line of Sight',
          data: result.los_heights,
          borderColor: result.is_los ? '#3fb950' : '#f85149',
          borderWidth: 2,
          borderDash: [5, 3],
          pointRadius: 0,
          fill: false,
        },
        {
          label: '60% Fresnel Zone (top)',
          data: result.fresnel_60pct_top,
          borderColor: 'rgba(88, 166, 255, 0.4)',
          backgroundColor: 'rgba(88, 166, 255, 0.08)',
          borderWidth: 1,
          pointRadius: 0,
          fill: '+1',
        },
        {
          label: '60% Fresnel Zone (bottom)',
          data: result.fresnel_60pct_bottom,
          borderColor: 'rgba(88, 166, 255, 0.4)',
          borderWidth: 1,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: {
            color: '#8b949e',
            font: { size: 11 },
            boxWidth: 12,
            padding: 8,
          },
        },
        tooltip: {
          backgroundColor: '#21262d',
          titleColor: '#e6edf3',
          bodyColor: '#8b949e',
          borderColor: '#30363d',
          borderWidth: 1,
          callbacks: {
            title: (items: any) => `Distance: ${items[0].label} km`,
            label: (item: any) => `${item.dataset.label}: ${item.formattedValue} m`,
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: 'Distance (km)', color: '#8b949e' },
          ticks: { color: '#6e7681', maxTicksLimit: 15 },
          grid: { color: 'rgba(48, 54, 61, 0.5)' },
        },
        y: {
          title: { display: true, text: 'Elevation (m ASL)', color: '#8b949e' },
          ticks: { color: '#6e7681' },
          grid: { color: 'rgba(48, 54, 61, 0.5)' },
        },
      },
    },
  })
}

watch(() => store.losResult, async () => {
  await nextTick()
  renderChart()
}, { deep: true })

onMounted(() => {
  if (store.losResult) renderChart()
})
</script>

<template>
  <div class="terrain-profile">
    <div class="profile-header">
      <h3>Terrain Profile</h3>
      <div class="profile-stats" v-if="store.losResult">
        <span :class="store.losResult.is_los ? 'stat-good' : 'stat-bad'">
          {{ store.losResult.is_los ? 'Clear LoS' : 'Obstructed' }}
        </span>
        <span class="stat">
          {{ (store.losResult.total_distance_m / 1000).toFixed(2) }} km
        </span>
        <span class="stat" v-if="store.losResult.path_loss">
          Path Loss: {{ store.losResult.path_loss.total_path_loss_db }} dB
        </span>
        <span class="stat">
          Clearance: {{ store.losResult.clearance_pct }}%
        </span>
        <span class="stat" v-if="store.losResult.obstructions?.length">
          {{ store.losResult.obstructions.length }} obstruction(s)
        </span>
      </div>
      <button class="close-btn" @click="store.terrainProfileOpen = false">&#10005;</button>
    </div>
    <div class="chart-container">
      <canvas ref="canvasRef"></canvas>
    </div>
    <div class="path-loss-detail" v-if="store.losResult?.path_loss">
      <div class="loss-item">
        <span class="loss-label">FSPL</span>
        <span class="loss-value">{{ store.losResult.path_loss.fspl_db }} dB</span>
      </div>
      <div class="loss-item">
        <span class="loss-label">Diffraction</span>
        <span class="loss-value">{{ store.losResult.path_loss.diffraction_db }} dB</span>
      </div>
      <div class="loss-item">
        <span class="loss-label">Weather</span>
        <span class="loss-value">{{ store.losResult.path_loss.weather_db }} dB</span>
      </div>
      <div class="loss-item total">
        <span class="loss-label">Total</span>
        <span class="loss-value">{{ store.losResult.path_loss.total_path_loss_db }} dB</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.terrain-profile {
  height: 300px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
}

.profile-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.profile-header h3 {
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
}

.profile-stats {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  flex: 1;
}

.stat {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 3px;
}

.stat-good {
  font-size: 12px;
  color: var(--accent-green);
  background: rgba(63, 185, 80, 0.1);
  padding: 2px 8px;
  border-radius: 3px;
  font-weight: 600;
}

.stat-bad {
  font-size: 12px;
  color: var(--accent-red);
  background: rgba(248, 81, 73, 0.1);
  padding: 2px 8px;
  border-radius: 3px;
  font-weight: 600;
}

.close-btn {
  background: none;
  color: var(--text-muted);
  padding: 4px 8px;
  font-size: 14px;
  margin-left: auto;
}

.close-btn:hover {
  color: var(--text-primary);
}

.chart-container {
  flex: 1;
  padding: 8px 12px;
  min-height: 0;
}

.path-loss-detail {
  display: flex;
  gap: 4px;
  padding: 6px 16px 8px;
  flex-shrink: 0;
}

.loss-item {
  display: flex;
  gap: 6px;
  font-size: 11px;
  background: var(--bg-primary);
  padding: 3px 8px;
  border-radius: 3px;
}

.loss-label {
  color: var(--text-muted);
}

.loss-value {
  color: var(--text-secondary);
}

.loss-item.total {
  border: 1px solid var(--border-color);
}

.loss-item.total .loss-value {
  color: var(--accent-teal);
  font-weight: 600;
}
</style>
