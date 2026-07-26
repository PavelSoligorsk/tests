path = r"d:\python\fastapi\tests\test_stats_async.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix test_get_user_stats_as_teacher: /stats/user/{id}/full → teacher_token
# The line is at the end of that test function. It should use teacher_token not admin_token.
# Find: after "Teacher views student stats" the /stats/user/ call
old_block_1 = '''    resp = await async_client.get(
        f"/stats/user/{student_id}/full",
        params={"period": "all"},
        headers=_bearer(admin_token),
    )
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# Контроль доступа'''

new_block_1 = '''    resp = await async_client.get(
        f"/stats/user/{student_id}/full",
        params={"period": "all"},
        headers=_bearer(teacher_token),
    )
    assert resp.status_code == 200, resp.text


# ═══════════════════════════════════════════════════════════════
# Контроль доступа'''

if old_block_1 in content:
    content = content.replace(old_block_1, new_block_1)
    print("Fixed test_get_user_stats_as_teacher: teacher_token")
else:
    print("Block 1 NOT FOUND - searching...")
    # Try finding it differently
    idx = content.find('/stats/user/{student_id}/full')
    if idx != -1:
        snippet = content[idx-80:idx+150]
        print(repr(snippet))

# Fix test_student_cannot_view_other_user_stats: /stats/user/{id}/full → student_token
old_block_2 = '''    resp = await async_client.get(
        f"/stats/user/{student2['id']}/full",
        params={"period": "all"},
        headers=_bearer(admin_token),
    )
    assert resp.status_code == 403, resp.text'''

new_block_2 = '''    resp = await async_client.get(
        f"/stats/user/{student2['id']}/full",
        params={"period": "all"},
        headers=_bearer(student_token),
    )
    assert resp.status_code == 403, resp.text'''

if old_block_2 in content:
    content = content.replace(old_block_2, new_block_2)
    print("Fixed test_student_cannot_view_other_user_stats: student_token")
else:
    print("Block 2 NOT FOUND - searching...")
    idx = content.find("/stats/user/{student2['id']}/full")
    if idx != -1:
        snippet = content[idx-80:idx+150]
        print(repr(snippet))

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
