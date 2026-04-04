<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'

const props = defineProps<{
  hBeamwidth: number
  vBeamwidth: number
  gain: number
  frontToBack: number
  azimuth: number
  type: string
}>()

const hCanvas = ref<HTMLCanvasElement>()
const vCanvas = ref<HTMLCanvasElement>()

function drawPattern(
  canvas: HTMLCanvasElement,
  beamwidth: number,
  frontToBackDb: number,
  isHorizontal: boolean,
  pointingAngle: number,
) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const w = canvas.width
  const h = canvas.height
  const cx = w / 2
  const cy = h / 2
  const radius = Math.min(cx, cy) - 12

  ctx.clearRect(0, 0, w, h)

  // Draw grid circles
  ctx.strokeStyle = '#30363d'
  ctx.lineWidth = 0.5
  for (let r = 0.25; r <= 1; r += 0.25) {
    ctx.beginPath()
    ctx.arc(cx, cy, radius * r, 0, Math.PI * 2)
    ctx.stroke()
  }

  // Draw grid lines
  for (let a = 0; a < 360; a += 30) {
    const rad = (a * Math.PI) / 180
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(cx + radius * Math.cos(rad), cy - radius * Math.sin(rad))
    ctx.stroke()
  }

  // Cardinal labels
  ctx.fillStyle = '#8b949e'
  ctx.font = '9px monospace'
  ctx.textAlign = 'center'
  if (isHorizontal) {
    ctx.fillText('N', cx, 8)
    ctx.fillText('S', cx, h - 2)
    ctx.fillText('E', w - 2, cy + 4)
    ctx.fillText('W', 6, cy + 4)
  } else {
    ctx.fillText('0\u00b0', cx, 8)
    ctx.fillText('180\u00b0', cx, h - 2)
    ctx.fillText('90\u00b0', w - 4, cy + 4)
    ctx.fillText('-90\u00b0', 10, cy + 4)
  }

  // Draw pattern
  const halfBw = beamwidth / 2
  const isOmni = beamwidth >= 360

  ctx.beginPath()
  ctx.strokeStyle = '#3fb950'
  ctx.fillStyle = 'rgba(63, 185, 80, 0.15)'
  ctx.lineWidth = 1.5

  for (let deg = 0; deg <= 360; deg++) {
    let offset = deg
    if (offset > 180) offset = 360 - offset

    let gainNorm: number
    if (isOmni) {
      gainNorm = 0.8
    } else if (offset <= halfBw) {
      gainNorm = 1.0 - 0.5 * (offset / halfBw) ** 2
    } else if (offset <= 90) {
      const fbNorm = Math.max(0.05, 1.0 - frontToBackDb / 30)
      gainNorm = 0.5 - (offset - halfBw) / (90 - halfBw) * (0.5 - fbNorm)
    } else {
      gainNorm = Math.max(0.05, 1.0 - frontToBackDb / 30)
    }

    // Rotate by pointing angle
    const plotAngle = isHorizontal
      ? ((90 - deg - pointingAngle) * Math.PI) / 180
      : ((90 - deg) * Math.PI) / 180

    const r = radius * gainNorm
    const x = cx + r * Math.cos(plotAngle)
    const y = cy - r * Math.sin(plotAngle)

    if (deg === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.closePath()
  ctx.fill()
  ctx.stroke()

  // Draw pointing direction indicator for horizontal
  if (isHorizontal && !isOmni) {
    const pRad = ((90 - pointingAngle) * Math.PI) / 180
    ctx.beginPath()
    ctx.strokeStyle = '#f85149'
    ctx.lineWidth = 1
    ctx.setLineDash([4, 3])
    ctx.moveTo(cx, cy)
    ctx.lineTo(cx + (radius + 6) * Math.cos(pRad), cy - (radius + 6) * Math.sin(pRad))
    ctx.stroke()
    ctx.setLineDash([])
  }

  // dB scale
  ctx.fillStyle = '#6e7681'
  ctx.font = '8px monospace'
  ctx.textAlign = 'left'
  ctx.fillText('0dB', cx + 2, cy - radius + 10)
  ctx.fillText('-3dB', cx + 2, cy - radius * 0.75 + 10)
}

function draw() {
  if (hCanvas.value) {
    drawPattern(hCanvas.value, props.hBeamwidth, props.frontToBack, true, props.azimuth)
  }
  if (vCanvas.value) {
    drawPattern(vCanvas.value, props.vBeamwidth, 15, false, 0)
  }
}

onMounted(draw)
watch(() => [props.hBeamwidth, props.vBeamwidth, props.gain, props.frontToBack, props.azimuth, props.type], draw)
</script>

<template>
  <div class="pattern-container">
    <div class="pattern-col">
      <div class="pattern-label">H-Plane</div>
      <canvas ref="hCanvas" width="120" height="120" class="pattern-canvas"></canvas>
    </div>
    <div class="pattern-col">
      <div class="pattern-label">V-Plane</div>
      <canvas ref="vCanvas" width="120" height="120" class="pattern-canvas"></canvas>
    </div>
  </div>
</template>

<style scoped>
.pattern-container {
  display: flex;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
}

.pattern-col {
  text-align: center;
}

.pattern-label {
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 2px;
}

.pattern-canvas {
  background: var(--bg-primary);
  border-radius: 4px;
  border: 1px solid var(--border-color);
}
</style>
