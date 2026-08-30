# .ll をバイナリのビットコード (.bc) に変換
llvm-as $1 -o $1.bc

# .bc からオブジェクトファイルを作る (-O0)
llc -O0 -march=wasm32 -filetype=obj $1.bc -o $1.o


wasm-ld --no-entry --export-all -o $1.wasm $1.o


