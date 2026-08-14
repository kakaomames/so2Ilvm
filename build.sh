#!/bin/bash
set -e

mkdir -p split_ll
mkdir -p objs
mkdir -p build

echo "LOG: 1. 巨大な .ll ファイルを小さなチャンクに分割中..."

for ll_file in *.ll; do
  [ -f "$ll_file" ] || continue
  # 以前の処理で作成されたファイルや一時ファイルはスキップ
  [[ "$ll_file" == "common_insts.ll" ]] && continue
  
  base_name=$(basename "$ll_file" .ll)
  echo "Processing: $ll_file"

  # ヘッダー情報を取得
  header=$(head -n 4 "$ll_file")

  # call文の行だけを抽出して 10,000 行ずつ分割
  grep "call void @arm64_inst_" "$ll_file" | split -l 10000 - "split_ll/${base_name}_part_"

  # 分割した各ファイルに正しい LLVM IR 構造 & 外部宣言（declare）を付与
  part_num=0
  for part in split_ll/${base_name}_part_*; do
    [ -f "$part" ] || continue
    func_name="entry_${base_name}_part_${part_num}"
    
    tmp_ll="${part}.ll"
    echo "$header" > "$tmp_ll"
    echo "" >> "$tmp_ll"
    
    # 登場する arm64_inst_... を抽出して「宣言 (declare)」のみを追加！(実体 define は作らない)
    grep -o "arm64_inst_0x[0-9a-fA-F]*" "$part" | sort -u | while read -r inst_name; do
      echo "declare void @${inst_name}()" >> "$tmp_ll"
    done

    echo "" >> "$tmp_ll"
    echo "define void @${func_name}() {" >> "$tmp_ll"
    echo "entry:" >> "$tmp_ll"
    cat "$part" >> "$tmp_ll"
    echo "  ret void" >> "$tmp_ll"
    echo "}" >> "$tmp_ll"

    # 元の分割一時ファイルを削除
    rm "$part"
    part_num=$((part_num + 1))
  done
done

echo "--------------------------------------------------"
echo "LOG: 2. 分割された .ll を 1 つずつ .o にコンパイル中..."

for sub_ll in split_ll/*.ll; do
  [ -f "$sub_ll" ] || continue
  obj_file="objs/$(basename "$sub_ll" .ll).o"
  
  echo "Compiling: $sub_ll -> $obj_file"
  emcc -O0 -c "$sub_ll" -o "$obj_file"
done

echo "--------------------------------------------------"
echo "LOG: 3. wasm-ld で軽量リンク実行..."

wasm-ld objs/*.o \
  --no-entry \
  --export-all \
  --allow-undefined \
  -o build/output.wasm

echo "--------------------------------------------------"
echo "🎉 大成功！！ 軽量化された build/output.wasm の生成が完了しました！！"
