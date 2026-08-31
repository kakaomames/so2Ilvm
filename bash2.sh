#!/bin/bash
set -euo pipefail

# 値が変更されたときにログを出す関数
log_change() {
  local key="$1"
  local val="$2"
  echo "[LOG] ${key} changed to: ${val}"
}

TAGS_FILE="allTag2.json"
log_change "TAGS_FILE" "${TAGS_FILE}"

REPO_OWNER_REPO="${GITHUB_REPOSITORY:-kakaomames/so2Ilvm}"
log_change "REPO_OWNER_REPO" "${REPO_OWNER_REPO}"

OUTPUT_FILE="exe_targets.json"
log_change "OUTPUT_FILE" "${OUTPUT_FILE}"

# 1. allTag.json が存在するか確認
if [ ! -f "${TAGS_FILE}" ]; then
  echo "[ERROR] ${TAGS_FILE} が見つかりません！"
  exit 1
fi

# 2. 全グループを保持する空のオブジェクトを作成
GROUPS_JSON="{}"

# 3. allTag.json からタグ（グループ名）を配列として読み込んでループ処理
TAG_LIST=$(jq -r '.[]' "${TAGS_FILE}")

for TAG_NAME in ${TAG_LIST}; do
  log_change "Current Target Tag" "${TAG_NAME}"
  
  # APIで該当タグのリリーストアセットを取得（エラー時は空配列）
  ASSETS_JSON=""
  if ! ASSETS_JSON=$(gh api "repos/${REPO_OWNER_REPO}/releases/tags/${TAG_NAME}" --jq '.assets[] | {name: .name, url: .browser_download_url}' 2>/dev/null); then
    echo "[LOG] Tag '${TAG_NAME}' のリリースが見つからないか、アセットがありません。スキップします。"
    GROUPS_JSON=$(echo "${GROUPS_JSON}" | jq --arg tag "${TAG_NAME}" '.[$tag] = []')
    continue
  fi

  # 各タグのアセット配列を初期化
  TAG_ASSETS="[]"

  # アセットを1つずつ処理
  while read -r asset; do
    [ -z "${asset}" ] && continue
    
    NAME=$(echo "${asset}" | jq -r '.name')
    URL=$(echo "${asset}" | jq -r '.url')
    
    # .so ファイル以外はスキップ
    if [[ "${NAME}" != *.exe ]]; then
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
    
    # 要素JSON作成
    ITEM_JSON=$(jq -n \
      --arg name "${NAME}" \
      --arg url "${URL}" \
      --arg arch "${ARCH}" \
      '{name: $name, url: $url, arch: $arch}')
      
    # タグごとのリストに追加
    TAG_ASSETS=$(echo "${TAG_ASSETS}" | jq --argjson item "${ITEM_JSON}" '. + [$item]')
    log_change "Current Group (${TAG_NAME}) Count" "$(echo "${TAG_ASSETS}" | jq 'length')"

  done <<< "${ASSETS_JSON}"

  # 該当タグの配列を groups オブジェクトに追加
  GROUPS_JSON=$(echo "${GROUPS_JSON}" | jq --arg tag "${TAG_NAME}" --argjson assets "${TAG_ASSETS}" '.[$tag] = $assets')

done

# 4. 最終的なJSON構造の生成とファイル保存
echo "[LOG] Building final JSON..."
FINAL_JSON=$(jq -n --argjson groups "${GROUPS_JSON}" '{groups: $groups}')

echo "${FINAL_JSON}" > "${OUTPUT_FILE}"
echo "[LOG] Successfully generated ${OUTPUT_FILE}!"

# 結果の確認ログ出力
log_change "${OUTPUT_FILE} Content" "$(cat "${OUTPUT_FILE}")"
