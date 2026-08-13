# binary_to_ir.py

import sys, os, struct, re

def binary_to_llvm_ir(bin_path, ir_path):
    # ファイル名からアルファベットと数値以外の記号を削って安全な関数名を作る
    base_name = os.path.basename(bin_path)
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', base_name)
    entry_func = f"entry_{clean_name}"

    # 登場したユニークな命令を記録するセット
    inst_set = set()
    
    instruction_count = 0
    try:
        with open(bin_path, 'rb') as f_in, open(ir_path, 'w', encoding='utf-8') as f_out:
            f_out.write(f'; ModuleID = "{base_name}"\n')
            f_out.write('target datalayout = "e-m:e-p:32:32-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"\n')
            f_out.write('target triple = "wasm32-unknown-unknown"\n\n')
            
            f_out.write(f'define void @{entry_func}() {{\nentry:\n')

            addr = 0
            while True:
                chunk = f_in.read(4)
                if not chunk or len(chunk) < 4:
                    break
                
                val = struct.unpack('<I', chunk)[0]
                hex_str = f"{val:08x}"
                inst_func = f"arm64_inst_0x{hex_str}"
                inst_set.add(inst_func)
                
                f_out.write(f'  ; block_0x{addr:08x}: instruction 0x{hex_str}\n')
                f_out.write(f'  call void @{inst_func}()\n')
                
                instruction_count += 1
                addr += 4

            f_out.write('  ret void\n}\n\n')

            # 呼び出しエラー(Undefined Symbol)を防ぐため、登場した命令のダミー定義（空関数）を末尾に吐き出す！
            f_out.write('; Dummy definitions for instruction nodes\n')
            for inst in inst_set:
                f_out.write(f'define linkonce_odr void @{inst}() {{\n  ret void\n}}\n')

    except Exception as e:
        print(f"Error processing binary: {e}")

    print(f"LOG: [{base_name}] 抽出命令数: {instruction_count}")

if __name__ == '__main__':
    binary_to_llvm_ir(sys.argv[1], sys.argv[2])
# EOF
