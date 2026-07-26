path = r"d:\python\fastapi\tests\test_stats_async.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()
for i, l in enumerate(lines):
    if "_bearer" in l:
        print(f"{i+1}: {l.rstrip()}")
