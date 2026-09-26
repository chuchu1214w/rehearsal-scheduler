#!/usr/bin/env bash
# 构建 iOS 正式包并上传到 App Store Connect(TestFlight)。
# 用法:./scripts/ios-release.sh [构建号]   —— 构建号默认取当前时间(YYYYMMDDHHMM)
# 签名 / 上传的身份二选一:
#   A) Xcode → Settings → Accounts 已登录开发者账号(自动签名);
#   B) App Store Connect API 密钥:ASC_KEY_PATH(.p8 路径)、ASC_KEY_ID、ASC_ISSUER_ID(三个都要,xcodebuild 强制要求 Issuer ID)。
# 注意:桌面文件夹由 iCloud 文件提供程序托管,写在这里的构建产物会带附加属性导致签名失败,
#       所以 archive / export 放在 ~/Library/Developer/Xcode 下。
set -euo pipefail
cd "$(dirname "$0")/../frontend"
BUILD_NO="${1:-$(date +%Y%m%d%H%M)}"
OUT="${HOME}/Library/Developer/Xcode/Archives/Season"
ARCHIVE="${OUT}/App-${BUILD_NO}.xcarchive"
EXPORT="${OUT}/export-${BUILD_NO}"
LOG="${OUT}/release-${BUILD_NO}.log"
mkdir -p "$OUT"

AUTH=()
if [ -n "${ASC_KEY_PATH:-}" ]; then
  : "${ASC_KEY_ID:?设置了 ASC_KEY_PATH 就必须同时设置 ASC_KEY_ID}"
  : "${ASC_ISSUER_ID:?还需要 ASC_ISSUER_ID(App Store Connect → 用户和访问 → 集成 → App Store Connect API 页面顶部)}"
  AUTH=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")
  echo "▶ 使用 App Store Connect API 密钥 ${ASC_KEY_ID}"
fi

echo "▶ 构建前端(API 指向线上)并同步到 iOS 工程"
npm run build:app
npx cap sync ios

echo "▶ Archive(构建号 ${BUILD_NO}),日志:${LOG}"
rm -rf "$ARCHIVE" "$EXPORT"
# macOS 自带 bash 3.2 下空数组配合 set -u 会报错,用 ${AUTH[@]+"${AUTH[@]}"} 展开
if ! xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
  -destination "generic/platform=iOS" -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates ${AUTH[@]+"${AUTH[@]}"} CURRENT_PROJECT_VERSION="${BUILD_NO}" archive > "$LOG" 2>&1; then
  grep -E "error:|ARCHIVE FAILED" "$LOG" | head -20
  echo "❌ Archive 失败,完整日志见 ${LOG}"
  exit 1
fi
echo "✓ Archive 完成"

echo "▶ 导出并上传到 App Store Connect"
if ! xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportOptionsPlist ios/ExportOptions.plist \
  -exportPath "$EXPORT" -allowProvisioningUpdates ${AUTH[@]+"${AUTH[@]}"} >> "$LOG" 2>&1; then
  grep -E "error|Error|failed" "$LOG" | tail -20
  echo "❌ 上传失败,完整日志见 ${LOG}"
  exit 1
fi
UPLOADED=$(/usr/libexec/PlistBuddy -c "Print :ApplicationProperties:CFBundleVersion" "$ARCHIVE/Info.plist" 2>/dev/null || echo "$BUILD_NO")
echo "✅ 已上传构建 ${UPLOADED};几分钟后在 App Store Connect → TestFlight 里能看到"

echo "▶ 恢复网页版构建(本机 start.sh 用)"
npm run build > /dev/null
