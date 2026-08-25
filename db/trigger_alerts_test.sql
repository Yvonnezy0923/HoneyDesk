-- ==============================================================
-- HoneyDesk: 今日数据触发预警测试（2026-08-24）
-- 修改今日数据以触发 7 类预警规则
-- ==============================================================

USE honey_desk;
SET NAMES utf8mb4;

-- ── 1. spend_surge（广告花费激增）──────────────────────────
-- SKU-10013 近7天日均花费 274.89 → 今日设为 900（3.27倍 ≥ 3.0 阈值）
UPDATE `ad_performance`
SET spend = 900.00
WHERE sku = 'SKU-10013' AND stat_date = '2026-08-24';

-- ── 2. conversion_drop（转化骤降）──────────────────────────
-- SKU-10008 近7天日均出单 2.0 → 今日设为 0（0 ≤ 2.0×0.5=1.0 阈值）
UPDATE `ad_performance`
SET orders = 0
WHERE sku = 'SKU-10008' AND stat_date = '2026-08-24';

-- ── 3. ctr_abnormal（CTR异常偏低）──────────────────────────
-- SKU-10012 今日设为曝光 5000、点击 6（CTR=0.0012 < 0.0015 阈值，曝光 ≥ 2000）
UPDATE `ad_performance`
SET impressions = 5000, clicks = 6, ctr = 0.0012
WHERE sku = 'SKU-10012' AND stat_date = '2026-08-24';

-- ── 4. inventory_shortage（库存告急）─────────────────────────
-- 已存在：SKU-10014 (available=0, safety=69)、SKU-10016 (50, 82)、SKU-10026 (0, 92)
-- 无需修改，已满足 available ≤ safety_stock×1.2 条件

-- ── 5. budget_depleted（预算将耗尽）─────────────────────────
-- 已存在：SKU-10012 (spent=638.94, budget=663)、SKU-10014 (963.37, 989.1)
-- 无需修改，已满足 spent ≥ monthly_budget×0.9 条件

-- ── 6. price_mutation（竞品降价）───────────────────────────
-- 已存在：SKU-10025 竞品 PureAura 价格从 15.94 降至 13.25（降幅 16.9% > 5%）
-- 无需修改，已满足 last_price < first_price×0.95 条件

-- ── 7. competitor_oos（竞品缺货）───────────────────────────
-- 已存在：SKU-10017 竞品 RadiantLab out_of_stock=1
-- 无需修改

-- ── 验证修改结果 ──────────────────────────────────────────
SELECT '=== spend_surge ===' as check_name, sku, spend
FROM ad_performance WHERE sku='SKU-10013' AND stat_date='2026-08-24'
UNION ALL
SELECT '=== conversion_drop ===', sku, orders
FROM ad_performance WHERE sku='SKU-10008' AND stat_date='2026-08-24'
UNION ALL
SELECT '=== ctr_abnormal ===', sku, CONCAT(impressions,'/',clicks,'/',ctr)
FROM ad_performance WHERE sku='SKU-10012' AND stat_date='2026-08-24';
