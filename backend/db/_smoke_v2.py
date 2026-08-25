"""把 schema_v2.sql 导入临时数据库 honey_test_v2，逐条执行验证语法与字段匹配."""
import pymysql
import re
from pathlib import Path

HOST = "localhost"
USER = "root"
PWD = "Zyazj19960923"

sql = Path(__file__).resolve().parent / "schema_v2.sql"
text = sql.read_text(encoding="utf-8")
# 去注释（保留行内也去掉）
lines = [l for l in text.splitlines() if not l.strip().startswith("--")]
body = "\n".join(lines)

# 按 ; 分句（INSERT 内不允许有裸分号，已有）
stmts = [s.strip() for s in body.split(";") if s.strip()]

conn = pymysql.connect(host=HOST, user=USER, password=PWD, charset="utf8mb4")
cur = conn.cursor()
cur.execute("CREATE DATABASE IF NOT EXISTS honey_test_v2 DEFAULT CHARSET utf8mb4")
for stmt in stmts:
    # 把 USE honey_system → 替换为测试库；把库名指向测试实例避免污染真实数据
    s = stmt.replace("honey_desk", "honey_test_v2").replace("honey_system", "honey_test_v2")
    s = s.replace("USE honey_test_v2;", "USE honey_test_v2")
    try:
        cur.execute(s)
    except Exception as e:
        print(f"!! FAIL 前45字: {s[:70]!r}")
        print(f"   -> {e}")
        conn.rollback()
        raise
conn.commit()
print("== 导入完成，无语法/字段错误 ==")

# 统计每表行数与维度多样性
cur.execute("USE honey_test_v2")
tables = ["products", "product_materials", "listings", "sales_orders",
          "competitors", "inventory", "ad_performance", "ad_budgets", "stores"]
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    n = cur.fetchone()[0]
    print(f"  {t}: {n} rows")
cur.execute("SELECT COUNT(DISTINCT store_id) FROM inventory"); print("inventory stores:", cur.fetchone()[0])
cur.execute("SELECT COUNT(DISTINCT warehouse) FROM inventory"); print("inventory warehouses:", cur.fetchone()[0])
cur.execute("SELECT COUNT(DISTINCT market) FROM sales_orders"); print("orders markets:", cur.fetchone()[0])
cur.execute("SELECT COUNT(DISTINCT market) FROM ad_performance"); print("ad markets:", cur.fetchone()[0])
cur.execute("SELECT COUNT(DISTINCT platform) FROM ad_performance"); print("ad platforms:", cur.fetchone()[0])
cur.execute("SELECT COUNT(DISTINCT language) FROM listings"); print("listing langs:", cur.fetchone()[0])
cur.execute("SELECT COUNT(DISTINCT currency) FROM sales_orders"); print("orders currency:", cur.fetchone()[0])

# 关联一致性：订单 sku 在 products 中都有；inventory sku 在 products 都有
cur.execute("""SELECT COUNT(*) FROM sales_orders o LEFT JOIN products p ON o.sku=p.id
               WHERE p.id IS NULL"""); print("orders sku 在 products 缺失:", cur.fetchone()[0])
cur.execute("""SELECT COUNT(*) FROM inventory i LEFT JOIN products p ON i.sku=p.id
               WHERE p.id IS NULL"""); print("inventory sku 在 products 缺失:", cur.fetchone()[0])
cur.execute("""SELECT COUNT(*) FROM ad_performance a LEFT JOIN products p ON a.sku=p.id
               WHERE p.id IS NULL"""); print("ad sku 在 products 缺失:", cur.fetchone()[0])
cur.execute("""SELECT COUNT(*) FROM inventory i LEFT JOIN stores s ON i.store_id=s.id
               WHERE s.id IS NULL"""); print("inventory store 在 stores 缺失:", cur.fetchone()[0])
cur.execute("""SELECT COUNT(*) FROM sales_orders o LEFT JOIN stores s ON o.store_id=s.id
               WHERE s.id IS NULL"""); print("orders store 在 stores 缺失:", cur.fetchone()[0])
cur.execute("""SELECT COUNT(*) FROM products p LEFT JOIN stores s ON p.store_id=s.id
               WHERE s.id IS NULL"""); print("products store 在 stores 缺失:", cur.fetchone()[0])

# 清理测试库
cur.execute("DROP DATABASE IF EXISTS honey_test_v2")
conn.commit()
conn.close()
print("== 测试库已清理 ==")