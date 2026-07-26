path = r"d:\python\fastapi\tests\test_stats_async.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Count all patterns
patterns = [
    'f"******"',
    'headers={"Authorization": f"******"}',
    'headers=_bearer(',
]
for p in patterns:
    print(f"'{p}': {content.count(p)}")

# Fix: find each f"******" occurrence by context
lines = content.split("\n")
for i, line in enumerate(lines):
    if 'f"******"' in line:
        print(f"Line {i+1}: {line.strip()}")
        # Show context
        for j in range(max(0,i-3), min(len(lines), i+2)):
            print(f"  {j+1}: {lines[j].strip()}")
        print()
