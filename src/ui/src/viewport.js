/**
 * 跨显示器拖拽时同步视口尺寸并强制 Chromium 重算布局视口。
 *
 * Windows + Chrome：窗口拖到另一块屏后，常出现
 *   outerWidth >> innerWidth（例如 2554 vs 1280）
 * 页面只占窗口一角，其余发白/空白，侧栏与输入框看起来「错位」。
 * 纯 CSS height:100% / 写死 --app-* 像素都救不了，需 nudge 逼浏览器重算。
 */

export const VIEWPORT_EVENT = 'app-viewport-change'

const RELOAD_GUARD_KEY = 'viewport_dpi_reload_once'
let lastKey = ''
let recovering = false

function measure() {
  const vv = window.visualViewport
  const w = Math.round(vv?.width || window.innerWidth || 0)
  const h = Math.round(vv?.height || window.innerHeight || 0)
  const dpr = window.devicePixelRatio || 1
  const outerW = Math.round(window.outerWidth || 0)
  const outerH = Math.round(window.outerHeight || 0)
  return { w, h, dpr, outerW, outerH }
}

/** outer 远大于 inner（超出正常窗口边框）→ 布局视口很可能卡住 */
function isViewportStale({ w, h, outerW, outerH }) {
  if (w <= 0 || h <= 0 || outerW <= 0) return false
  // 正常边框大约几十 px；拖屏卡死时常接近 2x
  const wide = outerW > w + 160 && outerW / w > 1.2
  const tall = outerH > h + 220 && outerH / h > 1.2
  return wide || tall
}

function applyCssVars({ w, h, dpr }) {
  const root = document.documentElement
  root.style.setProperty('--app-width', `${w}px`)
  root.style.setProperty('--app-height', `${h}px`)
  root.style.setProperty('--app-dpr', String(dpr))
  void document.body?.offsetHeight
  window.dispatchEvent(
    new CustomEvent(VIEWPORT_EVENT, { detail: { width: w, height: h, dpr } }),
  )
}

function applyViewport(force = false) {
  const m = measure()
  if (m.w <= 0 || m.h <= 0) return m

  const key = `${m.w}x${m.h}@${m.dpr}:${m.outerW}x${m.outerH}`
  if (!force && key === lastKey) return m
  lastKey = key
  applyCssVars(m)
  return m
}

/** Chromium 跨屏 DPI 常用 workaround：轻微 zoom 触发布局视口重建 */
function nudgeZoomRecover() {
  const root = document.documentElement
  const prev = root.style.zoom
  root.style.zoom = '100.02%'
  void root.offsetHeight
  root.style.zoom = prev || ''
  void root.offsetHeight
}

function tryReloadOnce() {
  try {
    if (sessionStorage.getItem(RELOAD_GUARD_KEY) === '1') return false
    sessionStorage.setItem(RELOAD_GUARD_KEY, '1')
    location.reload()
    return true
  } catch {
    return false
  }
}

function clearReloadGuard() {
  try {
    const m = measure()
    if (!isViewportStale(m)) sessionStorage.removeItem(RELOAD_GUARD_KEY)
  } catch {
    /* ignore */
  }
}

async function recoverStaleViewport() {
  if (recovering) return
  const before = measure()
  if (!isViewportStale(before)) {
    applyViewport(true)
    return
  }

  recovering = true
  try {
    nudgeZoomRecover()
    applyViewport(true)

    await new Promise((r) => setTimeout(r, 80))
    nudgeZoomRecover()
    applyViewport(true)

    await new Promise((r) => setTimeout(r, 200))
    const after = measure()
    if (isViewportStale(after)) {
      // zoom 无效则整页刷新一次（session 内最多一次，防死循环）
      tryReloadOnce()
    }
  } finally {
    recovering = false
  }
}

function reflowSoon() {
  applyViewport(true)
  requestAnimationFrame(() => applyViewport(true))
  setTimeout(() => applyViewport(true), 50)
  setTimeout(() => recoverStaleViewport(), 100)
  setTimeout(() => applyViewport(true), 300)
  setTimeout(() => recoverStaleViewport(), 500)
}

/** 启动视口同步（幂等） */
export function setupViewportHeight() {
  clearReloadGuard()
  applyViewport(true)
  if (isViewportStale(measure())) {
    recoverStaleViewport()
  }

  window.addEventListener('resize', () => {
    applyViewport()
    if (isViewportStale(measure())) recoverStaleViewport()
  })
  window.addEventListener('orientationchange', reflowSoon)
  window.visualViewport?.addEventListener('resize', () => applyViewport())
  window.visualViewport?.addEventListener('scroll', () => applyViewport())

  try {
    const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`)
    const onMq = () => reflowSoon()
    if (typeof mq.addEventListener === 'function') mq.addEventListener('change', onMq)
    else if (typeof mq.addListener === 'function') mq.addListener(onMq)
  } catch {
    /* ignore */
  }

  // 拖到另一屏后常先 focus，再延迟更新几何
  window.addEventListener('focus', reflowSoon)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') reflowSoon()
  })
}
