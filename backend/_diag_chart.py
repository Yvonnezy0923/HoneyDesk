import pymysql, json

conn = pymysql.connect(host='localhost', port=3306, user='root',
                       password='Zyazj19960923', database='honey_system', charset='utf8mb4')
cur = conn.cursor()
cur.execute("SELECT id, agent_code, title, content FROM honey_system.artifacts "
            "WHERE art_type='report' ORDER BY created_at DESC LIMIT 12")
rows = cur.fetchall()
print('report artifacts scanned:', len(rows))
for r in rows:
    content = r[3] or ''
    print('---')
    print('id:', r[0], '| agent:', r[1], '| title:', (r[2] or '')[:30])
    print('content len:', len(content))

cur.execute("SELECT id, result FROM honey_system.tasks "
            "WHERE status='completed' AND result LIKE '%\\\"chart\\\"%' ORDER BY created_at DESC LIMIT 8")
for r in cur.fetchall():
    try:
        res = json.loads(r[1]) if isinstance(r[1], str) else r[1]
    except Exception:
        continue
    anas = (res or {}).get('analyses') or []
    for a in anas:
        ch = a.get('chart')
        if not ch:
            continue
        sc = ch.get('series') or []
        cats = ch.get('categories')
        types = ch.get('types')
        print('task', r[0], '=> chart:', a.get('table'),
              '| series=%d' % len(sc),
              '| cats is None=%s len=%s' % (cats is None, len(cats) if cats is not None else '-'),
              '| types=%s' % (types if types is not None else 'NONE'),
              '| series data lens:', [len(x.get('data') or []) for x in sc])
conn.close()