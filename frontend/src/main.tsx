import 'dayjs/locale/zh-cn'
import dayjs from 'dayjs'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './styles/app.css'
import { App } from './App'
import { registerServiceWorker } from './push'

dayjs.locale('zh-cn')
registerServiceWorker()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
