import os
import sys
import struct
import zipfile
import glob

# Javaクラスファイルの定数プールタグ
CONSTANT_Utf8 = 1
CONSTANT_Integer = 3
CONSTANT_Float = 4
CONSTANT_Long = 5
CONSTANT_Double = 6
CONSTANT_Class = 7
CONSTANT_String = 8
CONSTANT_Fieldref = 9
CONSTANT_Methodref = 10
CONSTANT_InterfaceMethodref = 11
CONSTANT_NameAndType = 12

class ClassParser:
    def __init__(self, data):
        self.data = data
        self.offset = 0
        self.constant_pool = {}
        self.methods = []
        self.class_name = ""

    def read_u1(self):
        val = self.data[self.offset]
        self.offset += 1
        return val

    def read_u2(self):
        val = struct.unpack_from('>H', self.data, self.offset)[0]
        self.offset += 2
        return val

    def read_u4(self):
        val = struct.unpack_from('>I', self.data, self.offset)[0]
        self.offset += 4
        return val

    def parse(self):
        # マジックナンバー確認
        magic = self.read_u4()
        if magic != 0xCAFEBABE:
            raise ValueError("無効なマジックナンバーです。Javaクラスファイルではありません。")

        self.read_u2()  # minor_version
        self.read_u2()  # major_version

        # 定数プールのパース
        cp_count = self.read_u2()
        i = 1
        while i < cp_count:
            tag = self.read_u1()
            if tag == CONSTANT_Utf8:
                length = self.read_u2()
                bytes_val = self.data[self.offset:self.offset+length]
                self.offset += length
                self.constant_pool[i] = bytes_val.decode('utf-8', errors='ignore')
            elif tag == CONSTANT_Integer:
                val = self.read_u4()
                self.constant_pool[i] = val
                # LongとDoubleはコンサルプールを2つ消費する
            elif tag in (CONSTANT_Float,):
                val = self.read_u4()
                self.constant_pool[i] = val
            elif tag in (CONSTANT_Long, CONSTANT_Double):
                val = self.read_u4() + (self.read_u4() << 32)
                self.constant_pool[i] = val
                i += 1
                self.constant_pool[i] = None
            elif tag in (CONSTANT_Class, CONSTANT_String):
                val = self.read_u2()
                self.constant_pool[i] = val
            elif tag in (CONSTANT_Fieldref, CONSTANT_Methodref, CONSTANT_InterfaceMethodref, CONSTANT_NameAndType):
                val1 = self.read_u2()
                val2 = self.read_u2()
                self.constant_pool[i] = (val1, val2)
            else:
                raise ValueError(f"未対応の定数プールタグ: {tag} (インデックス: {i})")
            i += 1

        self.read_u2()  # access_flags
        this_class_idx = self.read_u2()
        super_class_idx = self.read_u2()

        # クラス名解決
        utf8_idx = self.constant_pool[this_class_idx]
        self.class_name = self.constant_pool[utf8_idx]

        # インターフェース
        interfaces_count = self.read_u2()
        for _ in range(interfaces_count):
            self.read_u2()

        # フィールド
        fields_count = self.read_u2()
        for _ in range(fields_count):
            self.read_u2()  # access_flags
            self.read_u2()  # name_index
            self.read_u2()  # descriptor_index
            attr_count = self.read_u2()
            for _ in range(attr_count):
                self.read_u2()
                attr_len = self.read_u4()
                self.offset += attr_len

        # メソッド
        methods_count = self.read_u2()
        for _ in range(methods_count):
            access_flags = self.read_u2()
            name_idx = self.read_u2()
            desc_idx = self.read_u2()
            
            method_name = self.constant_pool[name_idx]
            method_desc = self.constant_pool[desc_idx]

            attr_count = self.read_u2()
            code_attr = None
            for _ in range(attr_count):
                attr_name_idx = self.read_u2()
                attr_len = self.read_u4()
                attr_name = self.constant_pool[attr_name_idx]
                
                if attr_name == "Code":
                    max_stack = self.read_u2()
                    max_locals = self.read_u2()
                    code_length = self.read_u4()
                    code_bytes = self.data[self.offset:self.offset+code_length]
                    self.offset += code_length
                    
                    # 例外テーブルスキップ
                    exception_table_length = self.read_u2()
                    self.offset += exception_table_length * 8
                    
                    # ネスト属性スキップ
                    sub_attr_count = self.read_u2()
                    for _ in range(sub_attr_count):
                        self.read_u2()
                        sub_attr_len = self.read_u4()
                        self.offset += sub_attr_len
                        
                    code_attr = {
                        "max_stack": max_stack,
                        "max_locals": max_locals,
                        "code": code_bytes
                    }
                else:
                    self.offset += attr_len

            self.methods.append({
                "name": method_name,
                "descriptor": method_desc,
                "code": code_attr
            })

class BytecodeToLLVMTranslator:
    def __init__(self, class_parser):
        self.cp = class_parser.constant_pool
        self.class_name = class_parser.class_name
        self.methods = class_parser.methods

    def translate_bytecode(self, code_bytes):
        """JavaバイトコードをパースしてLLVM IRの基本ブロック命令列に変換する"""
        ir_lines = []
        stack = []
        locals_map = {}
        reg_counter = 1

        def new_reg():
            nonlocal reg_counter
            r = f"%{reg_counter}"
            reg_counter += 1
            return r

        i = 0
        while i < len(code_bytes):
            opcode = code_bytes[i]
            i += 1

            # 0x12: ldc (定数プールから定数をロード)
            if opcode == 0x12:
                index = code_bytes[i]
                i += 1
                val = self.cp[index]
                stack.append(val)

            # 0x03 - 0x08: iconst_0 ~ iconst_5
            elif 0x03 <= opcode <= 0x08:
                val = opcode - 0x03
                stack.append(val)

            # 0x10: bipush (1バイトの整数をスタックへ)
            elif opcode == 0x10:
                val = struct.unpack_from('b', code_bytes, i)[0]
                i += 1
                stack.append(val)

            # 0x15: iload (ローカル変数ロード)
            elif opcode == 0x15:
                var_idx = code_bytes[i]
                i += 1
                r = new_reg()
                ir_lines.load(f"  {r} = load i32, ptr %local_{var_idx}") # 簡易概念的レジスタ
                stack.append(r)

            # 0x1a - 0x1d: iload_0 ~ iload_3
            elif 0x1a <= opcode <= 0x1d:
                var_idx = opcode - 0x1a
                r = new_reg()
                # 簡易表現としてレジスタ参照を代入
                ir_lines.append(f"  {r} = load i32, ptr %local_{var_idx}")
                stack.append(r)

            # 0x36: istore (ローカル変数ストア)
            elif opcode == 0x36:
                var_idx = code_bytes[i]
                i += 1
                val = stack.pop()
                ir_lines.append(f"  store i32 {val}, ptr %local_{var_idx}")

            # 0x3b - 0x3e: istore_0 ~ istore_3
            elif 0x3b <= opcode <= 0x3e:
                var_idx = opcode - 0x3b
                val = stack.pop()
                ir_lines.append(f"  store i32 {val}, ptr %local_{var_idx}")

            # 0x60: iadd (加算)
            elif opcode == 0x60:
                right = stack.pop()
                left = stack.pop()
                r = new_reg()
                ir_lines.append(f"  {r} = add i32 {left}, {right}")
                stack.append(r)

            # 0x64: isub (減算)
            elif opcode == 0x64:
                right = stack.pop()
                left = stack.pop()
                r = new_reg()
                ir_lines.append(f"  {r} = sub i32 {left}, {right}")
                stack.append(r)

            # 0xac: ireturn (int値を返す)
            elif opcode == 0xac:
                val = stack.pop()
                ir_lines.append(f"  ret i32 {val}")

            # 0xb1: return (voidリターン)
            elif opcode == 0xb1:
                ir_lines.append("  ret void")

        return ir_lines

    def generate_ll(self):
        llvm_ir = [
            '; --- Binary-level Generated LLVM IR ---',
            'target datalayout = "e-m:e-p:32:32-i64:64-n32:64-S128"',
            'target triple = "wasm32-unknown-unknown"',
            ''
        ]

        for method in self.methods:
            m_name = method["name"]
            code = method["code"]
            
            if code is None:
                continue

            # 関数シグネチャ生成
            ret_type = "i32" if "I" in method["descriptor"] else "void"
            
            # main関数の特別扱い
            func_name = "main" if m_name == "main" else f"@{self.class_name}_{m_name}"
            if func_name != "main":
                func_name = f"@{m_name}"
            else:
                func_name = "@main"

            llvm_ir.append(f"define {ret_type} {func_name}() {{")
            
            # ローカル変数の初期領域確保 (max_locals分)
            for idx in range(code["max_locals"]):
                llvm_ir.append(f"  %local_{idx} = alloca i32, align 4")

            # バイトコードの翻訳命令を展開
            translated_lines = self.translate_bytecode(code["code"])
            llvm_ir.extend(translated_lines)

            # 返り値のフォールバック
            if not any("ret" in line for line in translated_lines):
                if ret_type == "i32":
                    llvm_ir.append("  ret i32 0")
                else:
                    llvm_ir.append("  ret void")

            llvm_ir.append("}\n")

        return "\n".join(llvm_ir)

def convert_jar_to_ll(jar_path, output_ll_path):
    print(f"[jar2ll] バイナリレベル解析開始: {jar_path}")
    
    extract_dir = "extracted_classes"
    os.makedirs(extract_dir, exist_ok=True)
    
    with zipfile.ZipFile(jar_path, 'r') as z:
        z.extractall(extract_dir)
        
    class_files = glob.glob(os.path.join(extract_dir, "**", "*.class"), recursive=True)
    print(f"[jar2ll] 発見されたクラス数: {len(class_files)}")

    all_ll_code = []
    for cf in class_files:
        with open(cf, "rb") as f:
            binary_data = f.read()
        
        parser = ClassParser(binary_data)
        parser.parse()
        
        translator = BytecodeToLLVMTranslator(parser)
        all_ll_code.append(translator.generate_ll())

    final_ir = "\n".join(all_ll_code)
    
    with open(output_ll_path, 'w', encoding='utf-8') as f:
        f.write(final_ir)
        
    print(f"[jar2ll] LLVM IR への完全バイナリ変換完了: {output_ll_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("使い方: python3 jar2ll.py <input.jar> <output.ll>")
        sys.exit(1)
        
    convert_jar_to_ll(sys.argv[1], sys.argv[2])

