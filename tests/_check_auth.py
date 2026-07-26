path = r"d:\python\fastapi\tests\test_student_async.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = 'f"******"'
count = content.count(old)
print(f"FOUND: {count}")
print(f"_bearer count: {content.count('_bearer')}")

lines = content.split("\n")
for i, l in enumerate(lines):
    if "_setup_student_with_assigned_test" in l:
        for j in range(i, i + 60):
            if j < len(lines):
                print(f"{j+1}: {lines[j]}")
        break
