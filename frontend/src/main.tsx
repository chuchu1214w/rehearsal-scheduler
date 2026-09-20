import 'dayjs/locale/zh-cn'
import dayjs from 'dayjs'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '../../design/tokens.css'
import './styles/global.css'
import { App } from './App'

dayjs.locale('zh-cn')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
