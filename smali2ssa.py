#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smali2ssa.py
- Smali → CFG → SSA IR
- 大規模実装前提の骨格版
"""

import sys
from pathlib import Path
import re
from collections import defaultdict, namedtuple

# -----------------------------
# 基本データ構造
# -----------------------------

Instruction = namedtuple("Instruction", ["opcode", "operands", "line", "label"])

class BasicBlock:
    def __init__(self, bid):
        self.id = bid
        self.instructions: list[Instruction] = []
        self.succ: list["BasicBlock"] = []
        self.pred: list["BasicBlock"] = []
        self.phi: dict[str, list[str]] = {}  # reg -> [versions]

    def __repr__(self):
        return f"<Block {self.id} instr={len(self.instructions)} succ={[b.id for b in self.succ]}>"


class MethodIR:
    def __init__(self, name: str):
        self.name = name
        self.blocks: list[BasicBlock] = []
        self.entry: BasicBlock | None = None
        self.label_to_block: dict[str, BasicBlock] = {}
        self.reg_versions: dict[str, int] = defaultdict(int)  # reg -> current version
        self.block_incoming: dict[int, dict[str, str]] = defaultdict(dict)  # block_id -> reg -> version

    def new_block(self) -> BasicBlock:
        b = BasicBlock(len(self.blocks))
        self.blocks.append(b)
        if self.entry is None:
            self.entry = b
        return b

    def new_version(self, reg: str) -> str:
        self.reg_versions[reg] += 1
        return f"{reg}_{self.reg_versions[reg]}"

    def __repr__(self):
        return f"<MethodIR {self.name} blocks={len(self.blocks)}>"

# -----------------------------
# Smali パーサ（メソッド単位）
# -----------------------------

METHOD_START_RE = re.compile(r'^\.method\b')
METHOD_END_RE = re.compile(r'^\.end\s+method\b')
LABEL_RE = re.compile(r'^\s*:(\w+)')
INSTR_RE = re.compile(r'^\s*([a-zA-Z0-9\-/]+)\s*(.*)$')

def parse_smali_methods(path: Path) -> list[MethodIR]:
    methods: list[MethodIR] = []
    current_method: MethodIR | None = None
    current_instrs: list[Instruction] = []
    current_labels: dict[int, str] = {}

    with path.open() as f:
        for idx, line in enumerate(f):
            raw = line.rstrip("\n")

            # メソッド開始
            if METHOD_START_RE.match(raw):
                current_method = MethodIR(name=raw.strip())
                current_instrs = []
                current_labels = {}
                continue

            # メソッド終了
            if METHOD_END_RE.match(raw):
                if current_method is not None:
                    build_cfg_for_method(current_method, current_instrs, current_labels)
                    methods.append(current_method)
                    current_method = None
                    current_instrs = []
                    current_labels = {}
                continue

            if current_method is None:
                continue

            # ラベル
            m_label = LABEL_RE.match(raw)
            if m_label:
                label_name = m_label.group(1)
                current_labels[len(current_instrs)] = label_name
                continue

            # 命令
            m_instr = INSTR_RE.match(raw)
            if m_instr:
                opcode = m_instr.group(1)
                ops_str = m_instr.group(2).strip()
                operands = [o.strip() for o in ops_str.split(",")] if ops_str else []
                label = current_labels.get(len(current_instrs))
                instr = Instruction(opcode=opcode, operands=operands, line=idx, label=label)
                current_instrs.append(instr)

    return methods

# -----------------------------
# CFG 構築
# -----------------------------

BRANCH_OPS = {
    "goto", "goto/16", "goto/32",
    "if-eq", "if-ne", "if-lt", "if-ge", "if-gt", "if-le",
    "if-eqz", "if-nez", "if-ltz", "if-gez", "if-gtz", "if-lez",
}
RETURN_PREFIX = "return"
SWITCH_OPS = {"packed-switch", "sparse-switch"}

def build_cfg_for_method(method: MethodIR, instructions: list[Instruction], labels: dict[int, str]):
    # 1. ブロック分割ポイント決定
    split_points = set()
    split_points.add(0)
    split_points.add(len(instructions))

    label_to_index = {v: k for k, v in labels.items()}

    for i, ins in enumerate(instructions):
        op = ins.opcode

        if op in BRANCH_OPS or op in SWITCH_OPS:
            # 分岐先
            target = ins.operands[-1].replace(":", "")
            if target in label_to_index:
                split_points.add(label_to_index[target])
            split_points.add(i + 1)

        if op.startswith(RETURN_PREFIX):
            split_points.add(i + 1)

    split_points = sorted(split_points)

    # 2. ブロック生成
    index_to_block: dict[int, BasicBlock] = {}
    for si, sj in zip(split_points[:-1], split_points[1:]):
        block = method.new_block()
        block.instructions.extend(instructions[si:sj])
        index_to_block[si] = block

    # 3. ラベル→ブロック対応
    for idx, label in labels.items():
        if idx in index_to_block:
            method.label_to_block[label] = index_to_block[idx]

    # 4. succ/pred 設定
    for si, sj in zip(split_points[:-1], split_points[1:]):
        block = index_to_block[si]
        if not block.instructions:
            continue

        last = block.instructions[-1]
        op = last.opcode

        if op in BRANCH_OPS:
            target_label = last.operands[-1].replace(":", "")
            target_block = method.label_to_block.get(target_label)
            if target_block:
                block.succ.append(target_block)
                target_block.pred.append(block)

            # fallthrough
            if sj in index_to_block:
                ft_block = index_to_block[sj]
                block.succ.append(ft_block)
                ft_block.pred.append(block)

        elif op.startswith(RETURN_PREFIX):
            # no succ
            pass

        else:
            # fallthroughのみ
            if sj in index_to_block:
                ft_block = index_to_block[sj]
                block.succ.append(ft_block)
                ft_block.pred.append(block)

# -----------------------------
# SSA 変換（大規模向け骨格）
# -----------------------------

WRITE_OP_PREFIXES = (
    "move", "move-wide", "move-object",
    "const", "const/4", "const/16", "const/high16",
    "add", "sub", "mul", "div", "rem",
    "and", "or", "xor", "shl", "shr", "ushr",
)

def is_reg(token: str) -> bool:
    return token.startswith("v") or token.startswith("p")

def ssa_transform_method(method: MethodIR):
    """
    大規模実装前提の SSA 変換骨格:
    - 各ブロック内でレジスタ書き込みにバージョンを割り当て
    - ブロック間の合流点で φ ノードを生成
    """
    # 1. 各ブロック内でレジスタ書き込みに SSA バージョンを付与
    for block in method.blocks:
        local_incoming: dict[str, str] = {}

        for ins in block.instructions:
            op = ins.opcode
            ops = ins.operands

            # 書き込み命令かどうか
            if any(op.startswith(prefix) for prefix in WRITE_OP_PREFIXES):
                if ops:
                    dst = ops[0]
                    if is_reg(dst):
                        ver = method.new_version(dst)
                        local_incoming[dst] = ver
                        method.block_incoming[block.id][dst] = ver

        # 既存 incoming をマージ
        for reg, ver in local_incoming.items():
            method.block_incoming[block.id][reg] = ver

    # 2. 合流点で φ ノード生成（簡易版）
    for block in method.blocks:
        if len(block.pred) > 1:
            # このブロックに入ってくるレジスタのバージョンを集める
            phi_map: dict[str, list[str]] = defaultdict(list)

            for pred in block.pred:
                incoming = method.block_incoming.get(pred.id, {})
                for reg, ver in incoming.items():
                    phi_map[reg].append(ver)

            # φ ノードとして登録
            for reg, versions in phi_map.items():
                if len(versions) > 1:
                    block.phi[reg] = versions

# -----------------------------
# SSA IR 出力
# -----------------------------

def write_method_ssa(method: MethodIR, out_dir: Path):
    safe_name = re.sub(r'\s+', '_', method.name)
    out_path = out_dir / f"{safe_name}.ssa"

    with out_path.open("w") as f:
        f.write(f"; METHOD {method.name}\n")

        for block in method.blocks:
            f.write(f"block {block.id}:\n")

            # φ ノード
            for reg, versions in block.phi.items():
                f.write(f"  {reg}_phi = phi({', '.join(versions)})\n")

            # 命令
            for ins in block.instructions:
                ops_str = ", ".join(ins.operands)
                f.write(f"  {ins.opcode} {ops_str}\n")

            f.write("\n")

# -----------------------------
# メイン
# -----------------------------

def main():
    if len(sys.argv) != 3:
        print("Usage: smali2ssa.py <smali_dir> <out_dir>", file=sys.stderr)
        sys.exit(1)

    smali_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    for smali_file in smali_dir.rglob("*.smali"):
        methods = parse_smali_methods(smali_file)
        for m in methods:
            ssa_transform_method(m)
            write_method_ssa(m, out_dir)

if __name__ == "__main__":
    main()
