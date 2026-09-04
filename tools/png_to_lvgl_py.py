"""Convert an RGBA PNG to an LVGL RGB565A8 C header."""
import sys
from pathlib import Path
from PIL import Image

src, dst, symbol, w_macro, h_macro = sys.argv[1:6]
image = Image.open(src).convert("RGBA")
w, h = image.size
colors = bytearray()
alpha = bytearray()
for r, g, b, a in image.getdata():
    value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    colors.extend((value & 0xFF, value >> 8))
    alpha.append(a)
data = colors + alpha
lines = [", ".join(f"0x{x:02X}" for x in data[i:i + 16])
         for i in range(0, len(data), 16)]
text = (f"#pragma once\n#include <stdint.h>\n\n#define {w_macro} {w}\n"
        f"#define {h_macro} {h}\nstatic const uint8_t {symbol}[{len(data)}] = {{\n    "
        + ",\n    ".join(lines) + "\n};\n")
Path(dst).write_text(text, encoding="ascii")
