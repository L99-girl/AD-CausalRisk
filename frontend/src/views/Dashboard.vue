<template>
  <div class="page">
    <div class="page-head">
      <div class="page-title">
        <div class="title-badge">
          <icon-home class="title-icon" />
        </div>
        <div>
          <h2 class="head-title">数据总览</h2>
          <span class="head-sub">实时掌握平台档案、风险与质量情况</span>
        </div>
      </div>
      <a-space>
        <a-radio-group v-model="range" type="button">
          <a-radio value="7d">近 7 天</a-radio>
          <a-radio value="30d">近 30 天</a-radio>
          <a-radio value="90d">近 90 天</a-radio>
          <a-radio value="all">全部</a-radio>
        </a-radio-group>
        <a-button type="text" size="small" @click="refreshAll">
          <icon-refresh /> 刷新
        </a-button>
      </a-space>
    </div>

    <a-row :gutter="[16, 16]" class="stat-row">
      <a-col :xs="24" :sm="12" :md="6" v-for="s in stats" :key="s.title">
        <a-card :bordered="false" class="stat-card" :style="{ '--card-accent': s.color }">
          <div class="stat-wrap">
            <div class="stat-icon" :style="{ background: s.color + '1F', color: s.color }">
              <component :is="s.icon" />
            </div>
            <div class="stat-main">
              <div class="stat-value-row">
                <a-statistic :value="s.value" class="stat-num">
                  <template #suffix v-if="s.unit">
                    <span class="stat-unit">{{ s.unit }}</span>
                  </template>
                </a-statistic>
                <span v-if="s.trend" class="stat-trend" :class="s.trend > 0 ? 'up' : 'down'">
                  {{ s.trend > 0 ? '+' : '' }}{{ s.trend }}%
                  <icon-arrow-rise v-if="s.trend > 0" />
                  <icon-arrow-fall v-else />
                </span>
              </div>
              <div class="stat-title">
                {{ s.title }}
                <a-tag color="orange" size="small" class="mock-tag">演示 Mock</a-tag>
              </div>
              <div class="stat-foot">{{ s.foot }}</div>
            </div>
          </div>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" class="chart-row">
      <a-col :xs="24" :md="24">
        <a-card :bordered="false" class="chart-card">
          <template #title class="card-title-row">
            <div class="card-title-inner">
              <span class="card-title-dot" />
              档案增长趋势
              <a-tag color="orange" size="small" class="mock-tag">演示 Mock</a-tag>
            </div>
          </template>
          <BaseChart :options="growthOption" height="320px" />
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" class="chart-row">
      <a-col :xs="24" :md="12">
        <a-card :bordered="false" class="chart-card">
          <template #title>
            <div class="card-title-inner">
              <span class="card-title-dot orange" />
              风险等级分布
              <a-tag color="orange" size="small" class="mock-tag">演示 Mock</a-tag>
            </div>
          </template>
          <BaseChart :options="riskOption" height="320px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :md="12">
        <a-card :bordered="false" class="chart-card">
          <template #title>
            <div class="card-title-inner">
              <span class="card-title-dot green" />
              诊断类型统计
              <a-tag color="orange" size="small" class="mock-tag">演示 Mock</a-tag>
            </div>
          </template>
          <BaseChart :options="diagnosisOption" height="320px" />
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import {
  IconUser, IconPlus, IconExclamation, IconCloseCircle,
  IconHome, IconRefresh, IconArrowRise, IconArrowFall
} from '@arco-design/web-vue/es/icon'
import BaseChart from '../components/BaseChart.vue'

const range = ref('30d')

const stats = computed(() => [
  {
    title: '总档案数',
    value: 2847,
    unit: '人',
    trend: 12.4,
    foot: '较上月 +313 人',
    icon: IconUser,
    color: '#165DFF'
  },
  {
    title: '今日新增',
    value: 28,
    unit: '人',
    trend: -3.5,
    foot: '昨日 29 人 · 本周均值 26',
    icon: IconPlus,
    color: '#00B42A'
  },
  {
    title: '高风险人数',
    value: 412,
    unit: '人',
    trend: 8.2,
    foot: '占比 14.5% · 需重点干预',
    icon: IconExclamation,
    color: '#F77234'
  },
  {
    title: '质量拦截数',
    value: 17,
    unit: '条',
    trend: -22.8,
    foot: '校验未通过，已阻止入库',
    icon: IconCloseCircle,
    color: '#F53F3F'
  }
])

const growthOption = ref({
  tooltip: {
    trigger: 'axis',
    backgroundColor: 'rgba(0,0,0,0.8)',
    borderWidth: 0,
    textStyle: { color: '#fff', fontSize: 12 },
    axisPointer: { type: 'line', lineStyle: { color: '#165DFF', type: 'dashed' } }
  },
  legend: {
    data: ['新增档案', '累计档案'],
    right: 0,
    top: 0,
    textStyle: { color: '#86909C', fontSize: 12 },
    itemWidth: 14,
    itemHeight: 8
  },
  grid: { left: 12, right: 16, top: 44, bottom: 8, containLabel: true },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: ['10-01','10-03','10-05','10-07','10-09','10-11','10-13','10-15','10-17','10-19','10-21','10-23','10-25','10-27','10-29','10-31'],
    axisLine: { lineStyle: { color: '#E5E6EB' } },
    axisTick: { show: false },
    axisLabel: { color: '#86909C', fontSize: 11 }
  },
  yAxis: [
    {
      type: 'value',
      name: '新增',
      nameTextStyle: { color: '#86909C', fontSize: 11, padding: [0, 0, 4, -20] },
      splitLine: { lineStyle: { color: '#F2F3F5', type: 'dashed' } },
      axisLabel: { color: '#86909C', fontSize: 11 }
    },
    {
      type: 'value',
      name: '累计',
      nameTextStyle: { color: '#86909C', fontSize: 11, padding: [0, -20, 4, 0] },
      splitLine: { show: false },
      axisLabel: { color: '#86909C', fontSize: 11 }
    }
  ],
  series: [
    {
      name: '新增档案',
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      data: [22, 28, 25, 31, 29, 35, 41, 38, 44, 48, 52, 47, 55, 58, 51, 60],
      itemStyle: { color: '#165DFF' },
      lineStyle: { width: 2.5 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(22,93,255,0.35)' },
            { offset: 1, color: 'rgba(22,93,255,0.02)' }
          ]
        }
      }
    },
    {
      name: '累计档案',
      type: 'line',
      yAxisIndex: 1,
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      data: [2400, 2428, 2453, 2484, 2513, 2548, 2589, 2627, 2671, 2719, 2771, 2818, 2873, 2931, 2982, 3042],
      itemStyle: { color: '#722ED1' },
      lineStyle: { width: 2.5 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(114,46,209,0.25)' },
            { offset: 1, color: 'rgba(114,46,209,0.02)' }
          ]
        }
      }
    }
  ]
})

const riskOption = ref({
  tooltip: {
    trigger: 'item',
    backgroundColor: 'rgba(0,0,0,0.8)',
    borderWidth: 0,
    textStyle: { color: '#fff', fontSize: 12 },
    formatter: '{b}: {c} 人 ({d}%)'
  },
  legend: {
    bottom: 4,
    left: 'center',
    textStyle: { color: '#86909C', fontSize: 12 },
    itemWidth: 10,
    itemHeight: 10,
    itemGap: 14
  },
  color: ['#00B42A', '#7BC618', '#F7BA1E', '#F77234', '#F53F3F'],
  series: [{
    type: 'pie',
    radius: ['48%', '72%'],
    center: ['50%', '44%'],
    avoidLabelOverlap: true,
    itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 3 },
    label: {
      show: true,
      formatter: '{b}\n{d}%',
      fontSize: 12,
      color: '#4E5969',
      lineHeight: 18
    },
    labelLine: { length: 10, length2: 8, lineStyle: { color: '#C9CDD4' } },
    data: [
      { value: 1245, name: '低风险' },
      { value: 823,  name: '较低风险' },
      { value: 367,  name: '中风险' },
      { value: 278,  name: '较高风险' },
      { value: 134,  name: '高风险' }
    ]
  }]
})

const diagnosisOption = ref({
  tooltip: {
    trigger: 'axis',
    backgroundColor: 'rgba(0,0,0,0.8)',
    borderWidth: 0,
    textStyle: { color: '#fff', fontSize: 12 },
    axisPointer: { type: 'shadow' }
  },
  grid: { left: 12, right: 16, top: 24, bottom: 8, containLabel: true },
  xAxis: {
    type: 'category',
    data: ['AD', 'MCI', 'Normal', 'Other', 'Unknown'],
    axisLine: { lineStyle: { color: '#E5E6EB' } },
    axisTick: { show: false },
    axisLabel: { color: '#4E5969', fontSize: 12 }
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#F2F3F5', type: 'dashed' } },
    axisLabel: { color: '#86909C', fontSize: 11 }
  },
  series: [{
    type: 'bar',
    barWidth: 36,
    borderRadius: [6, 6, 0, 0],
    itemStyle: {
      color: {
        type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: '#3491FA' },
          { offset: 1, color: '#165DFF' }
        ]
      }
    },
    label: {
      show: true,
      position: 'top',
      fontSize: 12,
      color: '#4E5969',
      fontWeight: 600,
      offset: [0, 4]
    },
    data: [892, 1047, 712, 158, 38]
  }]
})

function refreshAll() {
  range.value = range.value
}
</script>

<style scoped>
.page { padding: 20px 24px 40px; }

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 14px;
}
.title-badge {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, #165DFF 0%, #722ED1 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.title-icon { font-size: 20px; }
.head-title { font-size: 18px; font-weight: 600; color: var(--color-text-1); margin: 0; }
.head-sub { font-size: 12px; color: var(--color-text-3); }

.stat-row { margin-bottom: 16px; }

.stat-card {
  border-radius: 12px;
  border: 1px solid var(--color-border-2);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
  transition: all 0.25s;
  background: var(--color-bg-2);
}
.stat-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.07);
}
.stat-wrap {
  display: flex;
  gap: 16px;
  padding: 4px 0;
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
}
.stat-main { flex: 1; min-width: 0; }
.stat-value-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.stat-num { font-size: 26px !important; font-weight: 700 !important; line-height: 1.2 !important; }
.stat-num :deep(.arco-statistic-content-value) { font-family: 'SF Mono', Consolas, monospace; }
.stat-unit { font-size: 12px; color: var(--color-text-3); font-weight: 500; }
.stat-trend {
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.stat-trend.up { color: #00B42A; }
.stat-trend.down { color: #F53F3F; }
.stat-title { font-size: 13px; color: var(--color-text-2); margin-top: 4px; font-weight: 500; display: flex; align-items: center; gap: 6px; }
.mock-tag { margin-left: 4px; vertical-align: middle; }
.stat-foot { font-size: 11px; color: var(--color-text-3); margin-top: 2px; }

.chart-row { margin-bottom: 16px; }

.chart-card {
  border-radius: 12px;
  border: 1px solid var(--color-border-2);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
  background: var(--color-bg-2);
}
.card-title-inner {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-1);
}
.card-title-dot {
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: #165DFF;
}
.card-title-dot.orange { background: #F77234; }
.card-title-dot.green { background: #00B42A; }
</style>