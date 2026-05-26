CREATE DATABASE IF NOT EXISTS dingtalk_bot DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE dingtalk_bot;

CREATE TABLE IF NOT EXISTS fact_dingtalk_bot_call_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '调用时间',
  bot_module VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '模块：logistics/cp/split',
  event_type VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '事件类型',
  request_id VARCHAR(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '请求ID',
  message_id VARCHAR(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '钉钉消息ID',
  user_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '钉钉用户ID',
  user_name VARCHAR(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户名称',
  ack_status VARCHAR(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '处理状态',
  shipment_sns TEXT COLLATE utf8mb4_unicode_ci COMMENT '发货单号列表',
  message_text TEXT COLLATE utf8mb4_unicode_ci COMMENT '用户消息或事件详情',
  PRIMARY KEY (id),
  KEY idx_module_created (bot_module, created_at),
  KEY idx_event_created (event_type, created_at),
  KEY idx_user_created (user_id, created_at),
  KEY idx_request_id (request_id),
  KEY idx_message_id (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='钉钉机器人项目统一调用日志';

