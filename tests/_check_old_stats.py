path = r"d:\python\fastapi\tests\test_stats_async.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = 'f"******"'
print(f"OLD FOUND: {content.count(old)}")

# Print lines 27-167
lines = content.split("\n")
for i in range(26, min(167, len(lines))):
    print(f"{i+1}: {lines[i]}")
