import { useEffect, useState } from 'react'

import { Button, Note, Panel } from '../ui'
import { useToast } from '../ui/Toast'
import { currentSubscription, disablePush, enablePush, isIOS, isStandalone, pushSupported } from '../push'

/** 「安装到手机」+「开启推送」:账号页完整版;首页 / 通知页用 compact(可关闭,记在本机) */
export function InstallPushPanel({ compact = false }: { compact?: boolean }) {
  const { toast } = useToast()
  const [installable, setInstallable] = useState(!!window.__installPrompt)
  const [standalone] = useState(isStandalone())
  const [subscribed, setSubscribed] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [hidden, setHidden] = useState(() => {
    try {
      return compact && localStorage.getItem('season:hide-install-panel') === '1'
    } catch {
      return false
    }
  })

  useEffect(() => {
    const on = () => setInstallable(true)
    window.addEventListener('season:installable', on)
    void currentSubscription().then((s) => setSubscribed(!!s))
    return () => window.removeEventListener('season:installable', on)
  }, [])

  const install = async () => {
    const p = window.__installPrompt
    if (!p) return
    await p.prompt()
    const { outcome } = await p.userChoice
    if (outcome === 'accepted') {
      toast('已添加到主屏幕')
      window.__installPrompt = null
      setInstallable(false)
    }
  }
  const toggle = async () => {
    setBusy(true)
    try {
      if (subscribed) {
        await disablePush()
        setSubscribed(false)
        toast('已关闭这台设备的推送')
      } else {
        const err = await enablePush()
        if (err) toast(err, 'error')
        else {
          setSubscribed(true)
          toast('推送已开启:排练表发布、地点更新、明天的排练都会弹到手机')
        }
      }
    } catch {
      toast('操作失败,请稍后再试', 'error')
    } finally {
      setBusy(false)
    }
  }
  const dismiss = () => {
    setHidden(true)
    try {
      localStorage.setItem('season:hide-install-panel', '1')
    } catch {
      /* ignore */
    }
  }

  if (hidden) return null
  if (compact && standalone && subscribed) return null // 都弄好了就不打扰

  const ios = isIOS()
  return (
    <Panel>
      <div className="section">
        <h3 className="card-title" style={{ fontSize: 15 }}>
          {compact ? '装到手机,消息直接弹出来' : '安装到手机 · 推送通知'}
        </h3>
        {compact && (
          <Button small variant="ghost" onClick={dismiss}>
            不再提示
          </Button>
        )}
      </div>
      {!standalone && (
        <p className="card-copy">
          {installable
            ? '把 Season 添加到主屏幕,像 App 一样打开。'
            : ios
              ? 'iPhone:在 Safari 里点底部「分享」按钮 → 「添加到主屏幕」。'
              : '在浏览器菜单里选「添加到主屏幕」或「安装应用」。'}
        </p>
      )}
      {standalone && !compact && <p className="card-copy">已安装到主屏幕。</p>}
      {ios && !standalone && <Note>iPhone 需要先添加到主屏幕、从主屏幕图标打开,才能开启推送(iOS 16.4 以上)。</Note>}
      <div className="actions" style={{ justifyContent: 'flex-start' }}>
        {installable && !standalone && (
          <Button variant="primary" onClick={() => void install()}>
            添加到主屏幕
          </Button>
        )}
        {pushSupported() && (
          <Button variant={subscribed ? 'ghost' : 'primary'} loading={busy} onClick={() => void toggle()} disabled={subscribed === null}>
            {subscribed ? '关闭推送' : '开启推送通知'}
          </Button>
        )}
      </div>
    </Panel>
  )
}
