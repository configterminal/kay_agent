<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** { artifactId, mode, title, previewUrl, pdfUrl } | null */
  artifact: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['close'])

const isTarget = computed(() => (props.artifact?.mode || '') === 'target')

const heading = computed(() => {
  if (isTarget.value) return '目标蓝图简历'
  return '优化简历预览'
})

const subtitle = computed(() => {
  return props.artifact?.title || props.artifact?.artifactId || ''
})

function onDownload() {
  const url = props.artifact?.pdfUrl
  if (!url) return
  window.open(url, '_blank', 'noopener')
}

function onClose() {
  emit('close')
}
</script>

<template>
  <div v-if="artifact && artifact.previewUrl" class="resume-dock" :class="{ target: isTarget }">
    <div class="resume-dock-header">
      <div class="resume-dock-title">
        <span class="label">{{ heading }}</span>
        <span class="title">{{ subtitle }}</span>
        <span v-if="isTarget" class="warn-tag">完成学习前勿当已有经历投递</span>
      </div>
      <div class="resume-dock-actions">
        <button type="button" class="dl-btn" @click="onDownload">下载 PDF</button>
        <button type="button" class="close-btn" title="关闭" @click="onClose">✕</button>
      </div>
    </div>
    <div class="preview-wrap">
      <iframe
        class="preview-frame"
        :src="artifact.previewUrl"
        title="简历 A4 预览"
      />
    </div>
  </div>
</template>

<style scoped>
.resume-dock {
  border-top: 1px solid var(--border-color);
  background: var(--bg-surface);
  padding: 10px 16px 12px;
  flex-shrink: 0;
  max-height: calc(var(--app-height, 100dvh) * 0.52);
  display: flex;
  flex-direction: column;
}

.resume-dock.target {
  border-top-color: #c9a227;
}

.resume-dock-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 8px;
}

.resume-dock-title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.label {
  font-size: 11px;
  color: var(--text-secondary);
}

.title {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.warn-tag {
  font-size: 11px;
  color: #6d5a00;
  background: #fff8e1;
  border: 1px solid #e6d48a;
  padding: 2px 6px;
  border-radius: 4px;
  width: fit-content;
}

.resume-dock-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.dl-btn {
  border: 1px solid var(--border-color);
  background: var(--bg-hover);
  color: var(--text-primary);
  cursor: pointer;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.dl-btn:hover {
  border-color: var(--accent-color, #4a90d9);
}

.close-btn {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 14px;
}

.close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.preview-wrap {
  flex: 1;
  min-height: 220px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  background: #e8e8e8;
}

.preview-frame {
  display: block;
  width: 100%;
  height: min(calc(var(--app-height, 100dvh) * 0.42), 480px);
  border: 0;
  background: #fff;
}
</style>
