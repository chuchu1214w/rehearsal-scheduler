import type { CapacitorConfig } from '@capacitor/cli'

// iOS App 外壳:前端构建产物打进 App,API 指向线上(VITE_API_BASE,见 package.json 的 build:app)
const config: CapacitorConfig = {
  appId: 'app.timetomeet.season',
  appName: 'Season',
  webDir: 'dist',
  backgroundColor: '#fef0fb',
  ios: {
    contentInset: 'automatic',
  },
  plugins: {
    PushNotifications: { presentationOptions: ['badge', 'sound', 'banner', 'list'] },
    // style: LIGHT = 浅色背景、深色状态栏文字;insetsHandling 只对 Android 生效,iOS 用 CSS env(safe-area-inset-*)
    SystemBars: { insetsHandling: 'css', style: 'LIGHT' },
    Keyboard: { resize: 'native' },
  },
}

export default config
