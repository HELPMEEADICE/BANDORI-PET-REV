#!/bin/bash
# 双击运行本文件，自动解除 BandoriPet 的“已损坏 / 无法打开”限制。
# 原理：清除 macOS 下载时打上的 com.apple.quarantine 隔离标记。
# 本脚本不会联网、不改系统设置，只对 BandoriPet.app 生效。

set -u

APP_NAME="BandoriPet.app"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "  BandoriPet 首次打开修复工具"
echo "========================================"
echo

# 按优先级查找 app：脚本同目录(dmg 内) -> /Applications -> 用户 Applications
CANDIDATES=(
  "$SCRIPT_DIR/$APP_NAME"
  "/Applications/$APP_NAME"
  "$HOME/Applications/$APP_NAME"
)

TARGET=""
for p in "${CANDIDATES[@]}"; do
  if [ -d "$p" ]; then
    TARGET="$p"
    break
  fi
done

if [ -z "$TARGET" ]; then
  echo "✗ 没找到 $APP_NAME。"
  echo "  请先把 BandoriPet 拖到「应用程序」文件夹，再双击运行本工具。"
  echo
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi

echo "找到应用：$TARGET"
echo "正在解除隔离标记…"
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null

if xattr -p com.apple.quarantine "$TARGET" >/dev/null 2>&1; then
  echo
  echo "✗ 仍有隔离标记，可能需要管理员权限。请输入开机密码后重试："
  sudo xattr -dr com.apple.quarantine "$TARGET"
fi

if xattr -p com.apple.quarantine "$TARGET" >/dev/null 2>&1; then
  echo "✗ 解除失败，请把这个窗口的内容截图反馈给开发者。"
else
  echo
  echo "✓ 修复完成！现在可以正常双击打开 BandoriPet 了。"
fi

echo
read -n 1 -s -r -p "按任意键关闭…"
echo
