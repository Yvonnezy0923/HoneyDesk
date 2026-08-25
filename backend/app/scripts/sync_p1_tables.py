"""补建 replenishment_plans 和 alerts 表 + 种子数据，确保本地 MySQL 与 ORM 定义一致."""
import sys
from pathlib import Path

# 确保能 import backend 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models import create_all
from app.seed import seed_p1


def run():
    print("=" * 60)
    print("补建 P1 业务表：replenishment_plans、alerts")
    print("-" * 60)

    # create_all 幂等，只会补建不存在的表
    create_all()
    print("[OK] 表结构已就绪（若不存在则已创建）")

    # 表为空时自动写入演示数据
    result = seed_p1()
    if result["alerts"]:
        print(f"[OK] 写入 {result['alerts']} 条预警记录（演示数据）")
    else:
        print("[SKIP] 预警表已有数据，跳过种子")

    if result["replenishment_plans"]:
        print(f"[OK] 写入 {result['replenishment_plans']} 条补货计划（演示数据）")
    else:
        print("[SKIP] 补货计划表已有数据，跳过种子")

    print("=" * 60)
    print("完成。现在这两张表已存在于本地 MySQL 的 honey_desk 库中。")


if __name__ == "__main__":
    run()