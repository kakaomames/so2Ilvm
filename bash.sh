#!/bin/bash
set -euo pipefail

# 値が変更されたときにログを出す関数
log_change() {
  local key="$1"
  local val="$2"
  echo "[LOG] ${key} changed to: ${val}"
}

# 1. ターゲットとなるタグ名とリポジトリ情報の取得
# GitHub Actionsの環境変数から自動取得（ローカル実行時はフォールバック）
TAG_NAME="${GITHUB_REF_NAME:-v1.0.0}"
log_change "TAG_NAME" "${TAG_NAME}"

REPO_OWNER_REPO="${GITHUB_REPOSITORY:-OWNER/REPO}"
log_change "REPO_OWNER_REPO" "${REPO_OWNER_REPO}"

OUTPUT_FILE="so_targets.json"
log_change "OUTPUT_FILE" "${OUTPUT_FILE}"

# 2. リリース情報をGitHub API (gh CLI) から取得
echo "[LOG] Fetching release assets for tag: ${TAG_NAME}..."
ASSETS_JSON=$(gh api "repos/${REPO_OWNER_REPO}/releases/tags/${TAG_NAME}" --jq '.assets[] | {name: .name, url: .browser_download_url}')

# 3. 各グループ（core_modules / game_logic）の配列を初期化
CORE_MODULES="[]"
GAME_LOGIC="[]"

# 4. 取得したアセットをループ処理してアーキテクチャ判定＆分類
while read -r asset; do
  [ -z "${asset}" ] && continue
  
  NAME=$(echo "${asset}" | jq -r '.name')
  URL=$(echo "${asset}" | jq -r '.url')
  
  # .so ファイル以外はスキップ
  if [[ "${NAME}" != *.so ]]; then
    continue
  fi
  
  log_change "Processing Asset Name" "${NAME}"
  log_change "Processing Asset URL" "${URL}"
  
  # アーキテクチャの自動判別
  ARCH="unknown"
  if [[ "${NAME}" == *"arm64"* ]] || [[ "${NAME}" == *"v8a"* ]]; then
    ARCH="arm64-v8a"
  elif [[ "${NAME}" == *"x64"* ]] || [[ "${NAME}" == *"x86_64"* ]]; then
    ARCH="x86_64"
  elif [[ "${NAME}" == *"v7a"* ]] || [[ "${NAME}" == *"armv7"* ]]; then
    ARCH="armeabi-v7a"
  elif [[ "${NAME}" == *"x86"* ]]; then
    ARCH="x86"
  fi
  log_change "Detected Arch" "${ARCH}"
  
  # JSONオブジェクトの作成
  ITEM_JSON=$(jq -n \
    --arg name "${NAME}" \
    --arg url "${URL}" \
    --arg arch "${ARCH}" \
    '{name: $name, url: $url, arch: $arch}')
    
  # ファイル名に基づいてグループ分け
  if [[ "${NAME}" == *"core"* ]]; then
    CORE_MODULES=$(echo "${CORE_MODULES}" | jq --argjson item "${ITEM_JSON}" '. + [$item]')
    log_change "Group core_modules Count" "$(echo "${CORE_MODULES}" | jq 'length')"
  elif [[ "${NAME}" == *"game"* ]]; then
    GAME_LOGIC=$(echo "${GAME_LOGIC}" | jq --argjson item "${ITEM_JSON}" '. + [$item]')
    log_change "Group game_logic Count" "$(echo "${GAME_LOGIC}" | jq 'length')"
  fi

done <<< "${ASSETS_JSON}"

# 5. 最終的なJSON構造の生成とファイル保存
echo "[LOG] Building final JSON..."
FINAL_JSON=$(jq -n \
  --argjson core "${CORE_MODULES}" \
  --argjson game "${GAME_LOGIC}" \
  '{
    groups: {
      core_modules: $core,
      game_logic: $game
    }
  }')

echo "${FINAL_JSON}" > "${OUTPUT_FILE}"
echo "[LOG] Successfully generated ${OUTPUT_FILE}!"

# 結果の確認ログ出力
log_change "${OUTPUT_FILE} Content" "$(cat "${OUTPUT_FILE}")"

