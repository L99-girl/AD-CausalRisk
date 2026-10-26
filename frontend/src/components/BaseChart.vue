<template>
  <div ref="chartRef" class="base-chart">
    <div v-if="loading" class="chart-loading">
      <a-spin dot />
    </div>
    <div v-if="!options && !loading" class="chart-empty">
      <icon-apps />
      <span>暂无数据</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, shallowRef, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import {
  LineChart, BarChart, PieChart, RadarChart,
  ScatterChart, GaugeChart, FunnelChart, HeatmapChart,
  TreemapChart, SunburstChart, BoxplotChart, CandlestickChart,
  GraphChart, EffectScatterChart, ParallelChart, SankeyChart,
  PictorialBarChart, ThemeRiverChart, CustomChart
} from 'echarts/charts'
import {
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent, PolarComponent, RadarComponent,
  DataZoomComponent, VisualMapComponent, VisualMapComponent as VisualMapContinuousComponent,
  GeoComponent, MarkPointComponent, MarkLineComponent, MarkAreaComponent,
  ToolboxComponent, BrushComponent, AriaComponent,
  DatasetComponent, TransformComponent
} from 'echarts/components'
import { LabelLayout, UniversalTransition } from 'echarts/features'
import { IconApps } from '@arco-design/web-vue/es/icon'

echarts.use([
  CanvasRenderer,
  LineChart, BarChart, PieChart, RadarChart,
  ScatterChart, GaugeChart, FunnelChart, HeatmapChart,
  TreemapChart, SunburstChart, BoxplotChart, CandlestickChart,
  GraphChart, EffectScatterChart, ParallelChart, SankeyChart,
  PictorialBarChart, ThemeRiverChart, CustomChart,
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent, PolarComponent, RadarComponent,
  DataZoomComponent, VisualMapComponent, VisualMapContinuousComponent,
  GeoComponent, MarkPointComponent, MarkLineComponent, MarkAreaComponent,
  ToolboxComponent, BrushComponent, AriaComponent,
  DatasetComponent, TransformComponent,
  LabelLayout, UniversalTransition
])

const props = defineProps({
  options: { type: Object, default: null },
  theme: { type: [String, Object], default: null },
  autoresize: { type: Boolean, default: true },
  loading: { type: Boolean, default: false },
  notMerge: { type: Boolean, default: false },
  lazyUpdate: { type: Boolean, default: false },
  width: { type: [String, Number], default: '100%' },
  height: { type: [String, Number], default: '100%' }
})

const chartRef = ref(null)
const chartInstance = shallowRef(null)
let resizeObserver = null
let resizeHandler = null

function initChart() {
  if (!chartRef.value || chartInstance.value) return
  chartInstance.value = echarts.init(chartRef.value, props.theme || undefined)
  if (props.options) {
    chartInstance.value.setOption(props.options)
  }
}

function disposeChart() {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    resizeHandler = null
  }
  if (chartInstance.value) {
    chartInstance.value.dispose()
    chartInstance.value = null
  }
}

function handleResize() {
  chartInstance.value?.resize()
}

function setupResize() {
  if (!props.autoresize || !chartRef.value) return
  resizeHandler = handleResize
  window.addEventListener('resize', resizeHandler)
  if ('ResizeObserver' in window) {
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(chartRef.value)
  }
}

function renderOptions() {
  if (!chartInstance.value || !props.options) return
  chartInstance.value.setOption(props.options, {
    notMerge: props.notMerge,
    lazyUpdate: props.lazyUpdate
  })
}

watch(() => props.options, () => {
  nextTick(renderOptions)
}, { deep: true })

watch(() => props.theme, (newTheme, oldTheme) => {
  if (newTheme === oldTheme) return
  disposeChart()
  nextTick(() => {
    initChart()
    setupResize()
  })
})

onMounted(async () => {
  await nextTick()
  initChart()
  setupResize()
})

onUnmounted(() => {
  disposeChart()
})

defineExpose({
  getInstance: () => chartInstance.value,
  resize: handleResize,
  setOption: (opt, opts) => chartInstance.value?.setOption(opt, opts),
  dispatchAction: (action) => chartInstance.value?.dispatchAction(action),
  showLoading: (cfg) => chartInstance.value?.showLoading(cfg),
  hideLoading: () => chartInstance.value?.hideLoading()
})
</script>

<style scoped>
.base-chart {
  position: relative;
  width: v-bind(width);
  height: v-bind(height);
  min-height: 100px;
}
.chart-loading,
.chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--color-text-3);
  font-size: 13px;
}
.chart-empty .arco-icon {
  font-size: 28px;
  opacity: 0.4;
}
</style>