#!/usr/bin/env bash
# 构建 iOS 正式包并上传到 App Store Connect(TestFlight)。
# 用法:./scripts/ios-release.sh [构建号]   —— 构建号默认取当前时间(YYYYMMDDHHMM)
# 签名 / 上传的身份二选一:
#   A) Xcode → Settings → Accounts 已登录开发者账号(自动签名);
#   B) 用 App Store Connect API 密钥:导出环境变量 ASC_KEY_PATH(.p8 路径)、ASC_KEY_ID、ASC_ISSUER_ID。
# 线上 API 为 https://timetomeet.fly.dev(build:app)。
set -euo pipefail
cd "$(dirname "$0")/../frontend"
BUILD_NO="${1:-$(date +%Y%m%d%H%M)}"
AUTH=()
if [ -n "${ASC_KEY_PATH:-}" ]; then
  AUTH=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")
  echo "▶ 使用 App Store Connect API 密钥 ${ASC_KEY_ID} 签名与上传"
fi
echo "▶ 构建前端(API 指向线上)并同步到 iOS 工程"
npm run build:app
npx cap sync ios
echo "▶ Archive(构建号 ${BUILD_NO})"
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
  -destination "generic/platform=iOS" -archivePath "build/App.xcarchive" \
  -allowProvisioningUpdates "${AUTH[@]}" CURRENT_PROJECT_VERSION="${BUILD_NO}" archive | grep -E "error:|warning: .*(sign|profile)|ARCHIVE (SUCCEEDED|FAILED)" || true
[ -d build/App.xcarchive ] || { echo "❌ Archive 失败,见上面的 error"; exit 1; }
echo "▶ 上传到 App Store Connect"
xcodebuild -exportArchive -archivePath "build/App.xcarchive" -exportOptionsPlist ios/ExportOptions.plist \
  -exportPath "build/export" -allowProvisioningUpdates "${AUTH[@]}" | grep -vE "^\s*$" | tail -15
echo "✅ 已上传;几分钟后在 App Store Connect → TestFlight 里能看到构建 ${BUILD_NO}"
echo "▶ 恢复网页版构建(本机 start.sh 用)"
npm run build >/dev/null
