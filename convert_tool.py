import re
import json

input_file = "source.txt"
output_file = "responses.json"

with open(input_file, "r", encoding="utf-8") as f:
    raw = f.read()

# 关键一步：
# 把“换行 + 周围的空格”全部删掉
# 比如 "今天运气爆棚！ \n 2. 不要放弃" -> "今天运气爆棚！2. 不要放弃"
clean = re.sub(r'\s*\n\s*', '', raw)

# 按“数字+点”切割，如 1.  2.  10.
parts = re.split(r'\s*\d+\.\s*', clean)

# 去掉空串，strip 前后空格
messages = [p.strip() for p in parts if p.strip()]

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(messages, f, ensure_ascii=False, indent=2)

print(json.dumps(messages, ensure_ascii=False, indent=2))
