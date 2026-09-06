import os
import sys
import struct
import zipfile
import glob
import json

class ClassParser:
    def __init__(self, data, mapping):
        self.data = data
        self.offset = 0
        self.constant_pool = {}
        self.methods = []
        self.class_name = ""
        self.mapping = mapping["constant_pool_tags"]

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
        magic = self.read_u4()
        if magic != 0xCAFEBABE:
            raise ValueError("無効なマジックナンバーです。Javaクラスファイルではありません。")

        self.read_u2()  # minor_version
        self.read_u2()  # major_version

        cp_count = self.read_u2()
        i = 1
        while i < cp_count:
            tag_num = self.read_u1()
            tag_name = self.mapping.get(str(tag_num))

            if not tag_name:
                raise ValueError(f"未対応の定数プールタグ番号: {tag_num} (インデックス: {i})")

            if tag_name == "CONSTANT_Utf8":
                length = self.read_u2()
                bytes_val = self.data[self.offset:self.offset+length]
                self.offset += length
                self.constant_pool[i] = bytes_val.decode('utf-8', errors='ignore')
            elif tag_name == "CONSTANT_Integer":
                val = self.read_u4()
                self.constant_pool[i] = val
            elif tag_name == "CONSTANT_Float":
                val = self.read_u4()
                self.constant_pool[i] = val
            elif tag_name in ("CONSTANT_Long", "CONSTANT_Double"):
                val = self.read_u4() + (self.read_u4() << 32)
                self.constant_pool[i] = val
                i += 1
                self.constant_pool[i] = None
            elif tag_name in ("CONSTANT_Class", "CONSTANT_String"):
                val = self.read_u2()
                self.constant_pool[i] = val
            elif tag_name in ("CONSTANT_Fieldref", "CONSTANT_Methodref", "CONSTANT_InterfaceMethodref", "CONSTANT_NameAndType", "CONSTANT_InvokeDynamic"):
                val1 = self.read_u2()
                val2 = self.read_u2()
                self.constant_pool[i] = (val1, val2)
            elif tag_name == "CONSTANT_MethodHandle":
                self.read_u1()
                self.read_u2()
                self.constant_pool[i] = None
            elif tag_name == "CONSTANT_MethodType":
                self.read_u2()
                self.constant_pool[i] = None
            i += 1

        self.read_u2()  # access_flags
        this_class_idx = self.read_u2()
        super_class_idx = self.read_u2()

        utf8_idx = self.constant_pool[this_class_idx]
        self.class_name = self.constant_pool[utf8_idx]

        interfaces_count = self.read_u2()
        for _ in range(interfaces_count):
            self.read_u2()

        fields_count = self.read_u2()
        for _ in range(fields_count):
            self.read_u2()
            self.read_u2()
            self.read_u2()
            attr_count = self.read_u2()
            for _ in range(attr_count):
                self.read_u2()
                attr_len = self.read_u4()
                self.offset += attr_len

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
                    
                    exception_table_length = self.read_u2()
                    self.offset += exception_table_length * 8
                    
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
        ir_lines = []
        stack = []
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

            if opcode == 0x12:
                index = code_bytes[i]
                i += 1
                val = self.cp.get(index, 0)
                if isinstance(val, int):
                    stack.append(val)
                else:
                    stack.append(0)
            elif 0x03 <= opcode <= 0x08:
                val = opcode - 0x03
                stack.append(val)
            elif opcode == 0x10:
                val = struct.unpack_from('b', code_bytes, i)[0]
                i += 1
                stack.append(val)
            elif opcode == 0x15:
                var_idx = code_bytes[i]
                i += 1
                r = new_reg()
                ir_lines.append(f"  {r} = load i32, ptr %local_{var_idx}")
                stack.append(r)
            elif 0x1a <= opcode <= 0x1d:
                var_idx = opcode - 0x1a
                r = new_reg()
                ir_lines.append(f"  {r} = load i32, ptr %local_{var_idx}")
                stack.append(r)
            elif opcode == 0x36:
                var_idx = code_bytes[i]
                i += 1
                if stack:
                    val = stack.pop()
                    ir_lines.append(f"  store i32 {val}, ptr %local_{var_idx}")
            elif 0x3b <= opcode <= 0x3e:
                var_idx = opcode - 0x3b
                if stack:
                    val = stack.pop()
                    ir_lines.append(f"  store i32 {val}, ptr %local_{var_idx}")
            elif opcode == 0x60:
                right = stack.pop() if stack else 0
                left = stack.pop() if stack else 0
                r = new_reg()
                ir_lines.append(f"  {r} = add i32 {left}, {right}")
                stack.append(r)
            elif opcode == 0x64:
                right = stack.pop() if stack else 0
                left = stack.pop() if stack else 0
                r = new_reg()
                ir_lines.append(f"  {r} = sub i32 {left}, {right}")
                stack.append(r)
            elif opcode == 0xac:
                val = stack.pop() if stack else 0
                ir_lines.append(f"  ret i32 {val}")
            elif opcode == 0xb1:
                ir_lines.append("  ret void")

        return ir_lines

    def generate_ll(self):
        llvm_ir = [
            '; --- JSON-driven Binary Generated LLVM IR ---',
            'target datalayout = "e-m:e-p:32:32-i64:64-n32:64-S128"',
            'target triple = "wasm32-unknown-unknown"',
            ''
        ]

        safe_class_name = self.class_name.replace("/", "_").replace(".", "_").replace("$", "_")

        for method_idx, method in enumerate(self.methods):
            m_name = method["name"]
            m_desc = method["descriptor"]
            code = method["code"]
            
            if code is None:
                continue

            ret_type = "i32" if "I" in m_desc else "void"
            
            # 特殊文字（<init>など）をサニタイズ
            sanitized_m_name = m_name.replace("<", "_").replace(">", "_")
            
            # ディスクリプタ（引数等の型情報）も安全な文字列に変換して関数名に組み込み、オーバーロードを完全回避！
            sanitized_desc = m_desc.replace("/", "_").replace(".", "_").replace("(", "_").replace(")", "_").replace("[", "arr_").replace(";", "").replace("$", "_")
            
            # main関数以外は、クラス名 + メソッド名 + 引数シグネチャ + インデックスで完全に一意にする
            if m_name == "main":
                func_name = "@main"
            else:
                func_name = f"@{safe_class_name}_{sanitized_m_name}_{sanitized_desc}_{method_idx}"

            llvm_ir.append(f"define {ret_type} {func_name}() {{")
            
            num_locals = max(code["max_locals"], 32)
            for idx in range(num_locals):
                llvm_ir.append(f"  %local_{idx} = alloca i32, align 4")

            translated_lines = self.translate_bytecode(code["code"])
            llvm_ir.extend(translated_lines)

            if not any("ret" in line for line in translated_lines):
                if ret_type == "i32":
                    llvm_ir.append("  ret i32 0")
                else:
                    llvm_ir.append("  ret void")

            llvm_ir.append("}\n")

        return "\n".join(llvm_ir)


def convert_jar_to_ll(jar_path, output_ll_path, mapping_path):
    print(f"[jar2ll] JSON設定を用いたバイナリ解析開始: {jar_path}")
    
    with open(mapping_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

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
        
        try:
            parser = ClassParser(binary_data, mapping)
            parser.parse()
            translator = BytecodeToLLVMTranslator(parser)
            all_ll_code.append(translator.generate_ll())
        except Exception as e:
            print(f"  [スキップ] クラス解析エラー ({cf}): {e}")

    final_ir = "\n".join(all_ll_code)
    
    with open(output_ll_path, 'w', encoding='utf-8') as f:
        f.write(final_ir)
        
    print(f"[jar2ll] 全クラスのLLVM IR変換完了: {output_ll_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("使い方: python3 jar2ll.py <input.jar> <output.ll>")
        sys.exit(1)
        
    mapping_file = "mapping.json"
    convert_jar_to_ll(sys.argv[1], sys.argv[2], mapping_file)
