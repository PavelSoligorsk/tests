import sys

path = sys.argv[1] if len(sys.argv) > 1 else r"d:\python\fastapi\tests\test_student_async.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = 'f"******"'

# 1. student/me -> student_token
idx = content.find("/student/me")
idx = content.find(old, idx)
if idx != -1:
    content = content[:idx] + "_bearer(student_token)" + content[idx+len(old):]
    print("1: student/me OK")

# 2. admin/users -> admin_token
idx = content.find("/admin/users")
idx = content.find(old, idx)
if idx != -1:
    content = content[:idx] + "_bearer(admin_token)" + content[idx+len(old):]
    print("2: admin/users OK")

# 3. assign-student-to-teacher -> admin_token
idx = content.find("/admin/assign-student-to-teacher")
idx = content.find(old, idx)
if idx != -1:
    content = content[:idx] + "_bearer(admin_token)" + content[idx+len(old):]
    print("3: assign-student-to-teacher OK")

# 4. /teacher/tests -> teacher_token
idx = content.find("/teacher/tests")
idx = content.find(old, idx)
if idx != -1:
    content = content[:idx] + "_bearer(teacher_token)" + content[idx+len(old):]
    print("4: teacher/tests OK")

# 5. /teacher/assign-test -> teacher_token
idx = content.find("/teacher/assign-test")
idx = content.find(old, idx)
if idx != -1:
    content = content[:idx] + "_bearer(teacher_token)" + content[idx+len(old):]
    print("5: assign-test OK")

# Also fix stats_async.py
remaining = content.count(old)
print(f"Remaining f\"******\" in student: {remaining}")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

# Now fix stats
stat_path = r"d:\python\fastapi\tests\test_stats_async.py"
with open(stat_path, "r", encoding="utf-8") as f:
    stat = f.read()

# Replace all remaining f"******" with _bearer(admin_token) or student_token as appropriate
import re

# Map endpoints to tokens
stat_replacements = [
    ("/admin/users", "_bearer(admin_token)"),
    ("/admin/assign-student-to-teacher", "_bearer(admin_token)"),
    ("/stats/me/period", "_bearer(student_token)"),
    ("/stats/me/topics", "_bearer(student_token)"),
    ("/stats/me/difficulty", "_bearer(student_token)"),
    ("/stats/me/full", "_bearer(student_token)"),
    ("/stats/user/", "_bearer(admin_token)"),  # generic for user stats
]

for endpoint, replacement in stat_replacements:
    idx = 0
    while True:
        idx = stat.find(endpoint, idx)
        if idx == -1:
            break
        # Find next f"******" after this endpoint
        match_idx = stat.find(old, idx)
        if match_idx != -1:
            stat = stat[:match_idx] + replacement + stat[match_idx+len(old):]
            print(f"Stats: {endpoint} -> {replacement}")
            idx = match_idx
        else:
            break
        idx += len(replacement)

print(f"Remaining f\"******\" in stats: {stat.count(old)}")

with open(stat_path, "w", encoding="utf-8") as f:
    f.write(stat)

print("All done")
