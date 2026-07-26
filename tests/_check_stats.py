path = r"d:\python\fastapi\tests\test_stats_async.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = 'f"******"'
print(f"FOUND f\"******\": {content.count(old)}")
print(f"_bearer count: {content.count('_bearer')}")
print(f"from tests.helpers_async import: {content.count('from tests.helpers_async import')}")
print(f"async_create_task: {content.count('async_create_task')}")
