#!/usr/bin/env python3
import sys
from pathlib import Path
import re

# -----------------------------
# Smali Parser
# -----------------------------

INSTR_RE = re.compile(r'^\s*([a-zA-Z0-9\-]+)\s*(.*)$')
LABEL_RE = re.compile(r'^\s*:(\w+)')

def parse_smali_file(path: Path):
    instructions = []
    labels = {}

    with path.open() as f:
        for idx, line in enumerate(f):
            line = line.strip()

            # label
            m = LABEL_RE.match(line)
            if m:
                labels[m.group(1)] = len(instructions)
                continue

            # instruction
            m = INSTR_RE.match(line)
            if m:
                opcode = m.group(1)
                operands = [x.strip() for x in m.group(2).split(',')] if m.group(2) else []
                instructions.append({
                    "opcode": opcode,
                    "operands": operands,
                    "line": idx
                })

    return instructions, labels


# -----------------------------
# CFG Builder
# -----------------------------

BRANCH_OPS = {
    "goto", "goto/16", "goto/32",
    "if-eq", "if-ne", "if-lt", "if-ge", "if-gt", "if-le",
    "if-eqz", "if-nez", "if-ltz", "if-gez", "if-gtz", "if-lez"
}

def build_cfg(instructions, labels):
    blocks = []
    block_map = {}

    # split blocks at branch targets
    split_points = set()

    for i, ins in enumerate(instructions):
        if ins["opcode"] in BRANCH_OPS:
            # branch target
            target = ins["operands"][-1].replace(":", "")
            if target in labels:
                split_points.add(labels[target])
            split_points.add(i + 1)

        if ins["opcode"].startswith("return"):
            split_points.add(i + 1)

    split_points.add(0)
    split_points.add(len(instructions))

    split_points = sorted(split_points)

    # build blocks
    for i in range(len(split_points) - 1):
        start = split_points[i]
        end = split_points[i + 1]
        block = {
            "id": i,
            "start": start,
            "end": end,
            "instructions": instructions[start:end],
            "succ": []
        }
        blocks.append(block)
        block_map[start] = block

    # successors
    for block in blocks:
        if not block["instructions"]:
            continue

        last = block["instructions"][-1]
        op = last["opcode"]

        if op in BRANCH_OPS:
            target = last["operands"][-1].replace(":", "")
            if target in labels:
                succ = block_map[labels[target]]
                block["succ"].append(succ)

            # fallthrough
            next_start = block["end"]
            if next_start in block_map:
                block["succ"].append(block_map[next_start])

        elif op.startswith("return"):
            pass
        else:
            next_start = block["end"]
            if next_start in block_map:
                block["succ"].append(block_map[next_start])

    return blocks


# -----------------------------
# SSA Transformer (Minimal)
# -----------------------------

def ssa_transform(blocks):
    """
    Minimal SSA transformer:
    - Assign unique SSA names per write
    - Insert φ nodes at merge points
    """

    ssa = {}
    reg_version = {}

    def new_version(reg):
        reg_version.setdefault(reg, 0)
        reg_version[reg] += 1
        return f"{reg}_{reg_version[reg]}"

    # per-block incoming values
    incoming = {b["id"]: {} for b in blocks}

    # first pass: assign SSA names
    for block in blocks:
        for ins in block["instructions"]:
            op = ins["opcode"]
            ops = ins["operands"]

            # detect register writes
            if op.startswith("move") or op.startswith("const") or op.startswith("add") or op.startswith("sub"):
                dst = ops[0]
                ssa_name = new_version(dst)
                incoming[block["id"]][dst] = ssa_name
                ins["ssa_dst"] = ssa_name
            else:
                ins["ssa_dst"] = None

    # second pass: φ nodes at merge points
    phi_nodes = {}

    for block in blocks:
        if len(block["succ"]) > 1:
            # merge point
            phi_nodes[block["id"]] = {}
            for succ in block["succ"]:
                for reg, val in incoming[block["id"]].items():
                    phi_nodes[block["id"]].setdefault(reg, []).append(val)

    return blocks, phi_nodes


# -----------------------------
# SSA IR Writer
# -----------------------------

def write_ssa(blocks, phi_nodes, out_path: Path):
    with out_path.open("w") as f:
        for block in blocks:
            f.write(f"block {block['id']}:\n")

            # phi nodes
            if block["id"] in phi_nodes:
                for reg, vals in phi_nodes[block["id"]].items():
                    f.write(f"  {reg}_phi = phi({', '.join(vals)})\n")

            # instructions
            for ins in block["instructions"]:
                dst = f"{ins['ssa_dst']} = " if ins["ssa_dst"] else ""
                ops = ", ".join(ins["operands"])
                f.write(f"  {dst}{ins['opcode']} {ops}\n")

            f.write("\n")


# -----------------------------
# Main
# -----------------------------

def main():
    smali_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(exist_ok=True)

    for smali_file in smali_dir.rglob("*.smali"):
        instructions, labels = parse_smali_file(smali_file)
        blocks = build_cfg(instructions, labels)
        blocks, phi_nodes = ssa_transform(blocks)

        out_path = out_dir / (smali_file.stem + ".ssa")
        write_ssa(blocks, phi_nodes, out_path)


if __name__ == "__main__":
    main()
