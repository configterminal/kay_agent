<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import Plyr from 'plyr'
import 'plyr/dist/plyr.css'
import { VIEWPORT_EVENT } from '../viewport.js'

const props = defineProps({
  /** { mediaUrl, captionsUrl, mediaPath, startSec, title, source } | null */
  clip: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['close'])

const videoRef = ref(null)
const loadError = ref('')
const resumeAt = ref(null)
/** @type {import('plyr').default | null} */
let player = null
let progressTimer = null

const PROGRESS_KEY = 'video_playback_progress'
const SETTINGS_KEY = 'video_player_settings'

/** 播放器设置的默认值 */
const DEFAULT_SETTINGS = {
  speed: 1,
  muted: false,
  volume: 1,
  captions: { active: false, language: 'zh' },
}

const PLYR_OPTIONS = {
  controls: [
    'play-large',
    'play',
    'progress',
    'current-time',
    'mute',
    'volume',
    'captions',
    'settings',
    'pip',
    'fullscreen',
  ],
  settings: ['captions', 'speed'],
  speed: { selected: 1, options: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2] },
  ratio: '16:9',
  clickToPlay: true,
  hideControls: true,
}

// ── 播放器设置持久化 ──────────────────────────────

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (!raw) return { ...DEFAULT_SETTINGS }
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

function saveSettings(s) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({
      speed: s.speed ?? DEFAULT_SETTINGS.speed,
      muted: s.muted ?? DEFAULT_SETTINGS.muted,
      volume: s.volume ?? DEFAULT_SETTINGS.volume,
      captions: s.captions ?? DEFAULT_SETTINGS.captions,
    }))
  } catch { /* ignore */ }
}

function applySavedSettings() {
  if (!player) return
  const s = loadSettings()
  try { player.speed = s.speed } catch { /* ignore */ }
  try { player.volume = s.volume } catch { /* ignore */ }
  try { player.muted = s.muted } catch { /* ignore */ }
  try {
    if (s.captions?.active) {
      player.toggleCaptions(true)
    }
  } catch { /* ignore */ }
}

// ── 播放进度持久化 ────────────────────────────────

function progressStorageKey() {
  return props.clip?.mediaPath || props.clip?.mediaUrl || ''
}

function loadSavedProgress() {
  const key = progressStorageKey()
  if (!key) return null
  try {
    const raw = localStorage.getItem(PROGRESS_KEY)
    const map = raw ? JSON.parse(raw) : {}
    const t = Number(map[key])
    return Number.isFinite(t) && t > 0 ? t : null
  } catch {
    return null
  }
}

function saveProgress(time) {
  const key = progressStorageKey()
  if (!key || !Number.isFinite(time) || time < 1) return
  try {
    const raw = localStorage.getItem(PROGRESS_KEY)
    const map = raw ? JSON.parse(raw) : {}
    map[key] = Math.floor(time)
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(map))
  } catch {
    /* ignore */
  }
}

function formatTime(sec) {
  const s = Math.max(0, Math.floor(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}

function destroyPlayer() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
  if (player) {
    const t = player.currentTime
    if (Number.isFinite(t)) saveProgress(t)
    // 销毁前保存当前设置
    try {
      saveSettings({
        speed: player.speed,
        muted: player.muted,
        volume: player.volume,
      })
    } catch { /* ignore */ }
    player.destroy()
    player = null
  }
}

function updateResumeHint() {
  const saved = loadSavedProgress()
  const start = Number(props.clip?.startSec) || 0
  if (saved != null && saved > start + 10) {
    resumeAt.value = saved
  } else {
    resumeAt.value = null
  }
}

function seekTo(time, autoplay = true) {
  if (!player || !Number.isFinite(time) || time < 0) return
  player.currentTime = time
  if (autoplay) {
    player.play().catch(() => {
      /* 浏览器可能拦截自动播放 */
    })
  }
}

function seekAndPlay() {
  if (!player || !props.clip) return
  const start = Number(props.clip.startSec)
  const target = Number.isFinite(start) && start >= 0 ? start : 0
  seekTo(target)
  updateResumeHint()
}

function resumeFromSaved() {
  if (resumeAt.value == null) return
  seekTo(resumeAt.value)
  resumeAt.value = null
}

function bindPlayerEvents() {
  if (!player) return
  player.on('ready', () => {
    applySavedSettings()
    seekAndPlay()
  })
  player.on('loadeddata', () => {
    applySavedSettings()
    seekAndPlay()
  })
  player.on('error', () => {
    loadError.value = '视频暂不可用'
  })
  player.on('timeupdate', () => {
    const t = player?.currentTime
    if (Number.isFinite(t) && t > 0) saveProgress(t)
  })
  // 用户手动改设置时实时保存
  player.on('speedchange', () => {
    try { saveSettings({ ...loadSettings(), speed: player.speed }) } catch { /* ignore */ }
  })
  player.on('volumechange', () => {
    try { saveSettings({ ...loadSettings(), volume: player.volume, muted: player.muted }) } catch { /* ignore */ }
  })
  player.on('captionsdisabled', () => {
    try { saveSettings({ ...loadSettings(), captions: { active: false } }) } catch { /* ignore */ }
  })
  player.on('captionsenabled', () => {
    try {
      const track = player.currentTrack ?? player.tracks?.find?.(t => t.kind === 'captions')
      saveSettings({ ...loadSettings(), captions: { active: true, language: track?.srclang || 'zh' } })
    } catch { /* ignore */ }
  })
  progressTimer = setInterval(() => {
    const t = player?.currentTime
    if (Number.isFinite(t) && t > 0) saveProgress(t)
  }, 5000)
}

function ensurePlayer() {
  const el = videoRef.value
  if (!el || !props.clip?.mediaUrl) return
  if (!player) {
    player = new Plyr(el, PLYR_OPTIONS)
    bindPlayerEvents()
  }
}

watch(
  () => props.clip && `${props.clip.mediaUrl}|${props.clip.startSec}|${props.clip.captionsUrl || ''}`,
  async (key, prev) => {
    loadError.value = ''
    if (!props.clip?.mediaUrl) {
      destroyPlayer()
      resumeAt.value = null
      return
    }
    await nextTick()
    const el = videoRef.value
    if (!el) return

    const prevUrl = prev ? String(prev).split('|')[0] : ''
    const urlChanged = prevUrl !== props.clip.mediaUrl

    ensurePlayer()
    updateResumeHint()
    if (urlChanged && el.src !== props.clip.mediaUrl) {
      el.src = props.clip.mediaUrl
      el.load()
    } else if (player) {
      seekAndPlay()
    }
  },
  { immediate: true },
)

function onViewportChange() {
  // 换屏后容器宽高变了，Plyr 需主动 resize，否则画面停在旧尺寸
  try {
    player?.resize?.()
  } catch {
    /* ignore */
  }
}

onMounted(() => {
  window.addEventListener(VIEWPORT_EVENT, onViewportChange)
})

onBeforeUnmount(() => {
  window.removeEventListener(VIEWPORT_EVENT, onViewportChange)
  destroyPlayer()
})

function onClose() {
  destroyPlayer()
  emit('close')
}
</script>

<template>
  <div v-if="clip && clip.mediaUrl" class="video-dock">
    <div class="video-dock-header">
      <div class="video-dock-title">
        <span class="label">课程片段</span>
        <span class="title">{{ clip.title || clip.source || '视频' }}</span>
      </div>
      <button type="button" class="close-btn" title="关闭" @click="onClose">✕</button>
    </div>
    <p v-if="loadError" class="video-error">{{ loadError }}</p>
    <button
      v-if="resumeAt != null"
      type="button"
      class="resume-btn"
      @click="resumeFromSaved"
    >
      从上次 {{ formatTime(resumeAt) }} 继续
    </button>
    <div class="video-wrap">
      <video
        ref="videoRef"
        class="video-el"
        playsinline
        crossorigin="anonymous"
        preload="metadata"
        :src="clip.mediaUrl"
      >
        <track
          v-if="clip.captionsUrl"
          kind="captions"
          srclang="zh"
          label="中文"
          :src="clip.captionsUrl"
          default
        />
      </video>
    </div>
  </div>
</template>

<style scoped>
.video-dock {
  border-top: 1px solid var(--border-color);
  background: var(--bg-surface);
  padding: 10px 16px 12px;
  flex-shrink: 0;
  min-width: 0;
}

.video-dock-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 8px;
}

.video-dock-title {
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

.resume-btn {
  display: inline-block;
  margin: 0 0 8px;
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-hover);
  color: var(--text-primary);
  cursor: pointer;
}

.resume-btn:hover {
  border-color: var(--accent-color, #4a90d9);
}

/* Plyr 容器：小窗 16:9，不变形 */
.video-wrap {
  border-radius: 8px;
  overflow: hidden;
  background: #000;
  max-width: 480px;
}

.video-wrap :deep(.plyr) {
  border-radius: 8px;
}

.video-wrap :deep(.plyr--video) {
  overflow: hidden;
}

.video-el {
  display: block;
  width: 100%;
}

.video-error {
  margin: 0 0 8px;
  font-size: 12px;
  color: #c45c5c;
}
</style>
