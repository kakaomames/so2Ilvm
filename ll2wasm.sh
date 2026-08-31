llc -O0 -march=wasm32 -filetype=obj "$1" -o "$1.o"
echo "llc完"
echo "wasm-ld始"
wasm-ld --no-entry --export-all -o $1.wasm $1.o


