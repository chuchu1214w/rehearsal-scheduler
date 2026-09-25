#!/usr/bin/env bash
# 构建 iOS 正式包并上传到 App Store Connect(TestFlight)。
# 用法:./scripts/ios-release.sh [构建号]   —— 构建号默认取当前时间(YYYYMMDDHHMM)
# 前提:Xcode 已登录开发者账号;线上 API 为 https://timetomeet.fly.dev(build:app)。
set -euo pipefail
cd "$(dirname "$0")/../frontend"
BUILD_NO="${1:-$(date +%Y%m%d%H%M)}"
echo "▶ 构建前端(API 指向线上)并同步到 iOS 工程"
npm run build:app
npx cap sync ios
echo "▶ Archive(构建号 ${BUILD_NO})"
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
  -destination "generic/platform=iOS" -archivePath "build/App.xcarchive" \
  -allowProvisioningUpdates CURRENT_PROJECT_VERSION="${BUILD_NO}" archive | tail -5
echo "▶ 上传到 App Store Connect"
xcodebuild -exportArchive -archivePath "build/App.xcarchive" -exportOptionsPlist ios/ExportOptions.plist \
  -exportPath "build/export" -allowProvisioningUpdates | tail -15
echo "✅ 已上传;几分钟后在 App Store Connect → TestFlight 里能看到构建 ${BUILD_NO}"
