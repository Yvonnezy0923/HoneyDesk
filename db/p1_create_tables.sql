-- ==============================================================
-- HoneyDesk: 补建 P1 业务表 replenishment_plans + alerts
-- 执行后这两张表会被创建在 honey_desk 库，与项目定义的字段完全一致
-- ==============================================================

USE honey_desk;
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- --------------------------------------------------------------
-- replenishment_plans: 补货计划表（补货建议 Agent 写操作落库目标）
-- --------------------------------------------------------------
DROP TABLE IF EXISTS `replenishment_plans`;
CREATE TABLE `replenishment_plans` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `store_id` varchar(40) DEFAULT NULL,
  `sku` varchar(40) DEFAULT NULL,
  `market` varchar(10) DEFAULT 'US',
  `warehouse` varchar(60) DEFAULT '',
  `plan_date` DATE DEFAULT (curdate()),
  `suggested_qty` int(11) DEFAULT 0,
  `suggested_arrival` DATE DEFAULT NULL,
  `days_of_supply` int(11) DEFAULT 0,
  `avg_daily_sales` float DEFAULT 0,
  `available` int(11) DEFAULT 0,
  `in_transit` int(11) DEFAULT 0,
  `safety_stock` int(11) DEFAULT 0,
  `lead_days` int(11) DEFAULT 0,
  `shortage_risk` varchar(10) DEFAULT 'low',
  `assumptions` JSON DEFAULT NULL,
  `status` varchar(20) DEFAULT 'draft',
  `source_task` varchar(40) DEFAULT '',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `store_id` (`store_id`),
  KEY `sku` (`sku`),
  KEY `market` (`market`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------
-- alerts: 预警记录表（库存/广告/运营预警记录，不审批，直接落库）
-- --------------------------------------------------------------
DROP TABLE IF EXISTS `alerts`;
CREATE TABLE `alerts` (
  `id` varchar(40) NOT NULL,
  `alert_type` varchar(30) NOT NULL,
  `scope` varchar(20) DEFAULT 'supply',
  `store_id` varchar(40) DEFAULT '',
  `sku` varchar(40) DEFAULT '',
  `market` varchar(10) DEFAULT 'US',
  `severity` varchar(10) DEFAULT 'medium',
  `title` varchar(200) DEFAULT '',
  `message` TEXT,
  `evidence` JSON DEFAULT NULL,
  `status` varchar(20) DEFAULT 'new',
  `resolution` TEXT,
  `source_task` varchar(40) DEFAULT '',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `alert_type` (`alert_type`),
  KEY `scope` (`scope`),
  KEY `sku` (`sku`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS=1;

-- 如果想初始化演示数据（几条预警和补货计划记录），也可以直接执行下面这个：
-- INSERT INTO `honey_desk`.`alerts` (`id`,`alert_type`,`scope`,`store_id`,`sku`,`market`,`severity`,`title`,`message`,`evidence`,`status`,`resolution`,`source_task`) VALUES
-- ('ALT-00001','inventory_shortage','supply','store_1001','SKU-10001','US','high','库存告急：SKU-10001','近30天日均销波动，可售库存低于安全库存建议线，建议补货','{\"demo\":true}','new','','seed_p1'),
-- ('ALT-00002','spend_surge','ads','store_1001','SKU-10002','US','high','广告花费激增：SKU-10002','今日广告花费显著高于近7日均值，需核查投放词与素材','{\"demo\":true}','new','','seed_p1'),
-- ('ALT-00003','conversion_drop','ads','store_1001','SKU-10003','US','high','广告转化骤降：SKU-10003','今日出单明显低于近期日均，需核查 Listing 与竞品价格','{\"demo\":true}','new','','seed_p1'),
-- ('ALT-00004','budget_depleted','ads','store_1001','SKU-10004','US','medium','广告预算将耗尽：SKU-10004','当月广告花费已达月度预算 90%，请注意控制','{\"demo\":true}','new','','seed_p1');
--
-- INSERT INTO `honey_desk`.`replenishment_plans` (`store_id`,`sku`,`market`,`warehouse`,`plan_date`,`suggested_qty`,`suggested_arrival`,`days_of_supply`,`avg_daily_sales`,`available`,`in_transit`,`safety_stock`,`lead_days`,`shortage_risk`,`assumptions`,`status`,`source_task`) VALUES
-- ('store_1001','SKU-10001','US','US-LAX',curdate() - interval 2 day,120,curdate() + interval 14 day,12,6.0,40,30,25,14,'medium','{\"target_days\":30,\"demo\":true}','confirmed','seed_p1'),
-- ('store_1001','SKU-10002','US','US-LAX',curdate() - interval 2 day,160,curdate() + interval 14 day,12,6.0,40,30,25,14,'medium','{\"target_days\":30,\"demo\":true}','confirmed','seed_p1'),
-- ('store_1001','SKU-10003','US','US-LAX',curdate() - interval 2 day,200,curdate() + interval 14 day,12,6.0,40,30,25,14,'medium','{\"target_days\":30,\"demo\":true}','confirmed','seed_p1');

SELECT 'done' as result, COUNT(*) as tables FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'honey_desk' AND TABLE_NAME IN ('replenishment_plans', 'alerts');
