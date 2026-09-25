import 'dayjs/locale/zh-cn'
import dayjs from 'dayjs'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './styles/app.css'
import { App } from './App'
import { isNative } from './native'
import { registerServiceWorker } from './push'

dayjs.locale('zh-cn')
if (!isNative()) registerServiceWorker() // 原生 App 里没有 Service Worker / Web Push,推送走 APNs

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
