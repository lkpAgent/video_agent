"""
将录音文件转为 base64 编码
"""
import base64
import sys
from pathlib import Path

# 源文件
src = r"C:\Users\lkp\Documents\录音\录音 (37).m4a"

if not Path(src).exists():
    print(f"文件不存在: {src}")
    sys.exit(1)

# 读取并编码
with open(src, "rb") as f:
    data = f.read()

b64 = base64.b64encode(data).decode()

# 保存到文本文件（太大，不打印）
out = Path(src).with_suffix(".b64.txt")
with open(out, "w") as f:
    f.write(b64)

print(f"源文件: {src}")
print(f"大小: {len(data) / 1024:.1f} KB")
print(f"Base64: {len(b64)} 字符")
print(f"✅ 已保存到: {out}")
