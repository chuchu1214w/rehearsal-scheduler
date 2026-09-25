import type { CapacitorConfig } from '@capacitor/cli'

// iOS App 外壳:前端构建产物打进 App,API 指向线上(VITE_API_BASE,见 package.json 的 build:app)
const config: CapacitorConfig = {
  appId: 'app.timetomeet.season',
  appName: 'Season',
  webDir: 'dist',
  ios: {
    contentInset: 'automatic',
  },
  plugins: {
    PushNotifications: { presentationOptions: ['badge', 'sound', 'banner', 'list'] },
    SystemBars: { insetsHandling: 'css', style: 'DARK' },
    Keyboard: { resize: 'native' },
  },
}

export default config
