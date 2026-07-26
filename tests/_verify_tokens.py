path = r"d:\python\fastapi\tests\test_stats_async.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find all _bearer calls with their context (the endpoint 1-3 lines above)
lines = content.split("\n")
for i, line in enumerate(lines):
    if "_bearer(" in line:
        # Find endpoint in previous lines
        endpoint = ""
        for j in range(max(0, i-5), i):
            for kw in ["/stats/", "/admin/", "/login", "/student/", "/teacher/", "/register"]:
                if kw in lines[j]:
                    endpoint = lines[j].strip().rstrip(",")
                    break
            if endpoint:
                break
        token = line[line.index("_bearer("):line.index(")")+1]
        print(f"L{i+1}: {token:45s} <- {endpoint}")
