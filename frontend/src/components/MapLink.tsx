import { isNative, openExternal } from '../native'

/** 排练地点 + 「Naver 地图」按钮:装了 Naver Map 就直接在 App 里搜索这个地点(可再点 길찾기 导航),否则打开 Naver 地图网页。
 *  地点里如果含有链接(如 Naver 地图分享的 naver.me 链接),按钮直接打开这个链接。 */

const URL_RE = /https?:\/\/\S+/

export function splitLocation(location: string): { text: string; url: string | null } {
  const url = location.match(URL_RE)?.[0] ?? null
  return { text: (url ? location.replace(url, '') : location).trim(), url }
}

export function openNaverMap(location: string): void {
  const { text, url } = splitLocation(location)
  if (url) {
    void openExternal(url)
    return
  }
  const q = encodeURIComponent(text)
  const web = `https://map.naver.com/p/search/${q}`
  const mobile = isNative() || /iPhone|iPad|Android/i.test(navigator.userAgent)
  if (!mobile) {
    void openExternal(web)
    return
  }
  // 先试 Naver Map App;1.5 秒后页面仍在前台,说明没装 → 改开网页
  const timer = setTimeout(() => {
    if (document.visibilityState === 'visible') void openExternal(web)
  }, 1500)
  const cancel = () => {
    if (document.visibilityState === 'hidden') clearTimeout(timer)
  }
  document.addEventListener('visibilitychange', cancel, { once: true })
  window.location.assign(`nmap://search?query=${q}&appname=app.timetomeet.season`)
}

export function Location({ location, inline = false }: { location: string; inline?: boolean }) {
  const { text, url } = splitLocation(location)
  const button = (
    <button
      type="button"
      className="maplink"
      onClick={(e) => {
        e.stopPropagation()
        openNaverMap(location)
      }}
      aria-label={`在 Naver 地图中打开 ${text || '地点'}`}
    >
      Naver 地图
    </button>
  )
  return (
    <span className={'location' + (inline ? ' location--inline' : '')}>
      📍 {text || (url ? '地图链接' : '')} {button}
    </span>
  )
}
