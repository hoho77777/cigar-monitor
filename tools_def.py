# -*- coding: utf-8 -*-
"""AI 工具定义（MCP 原生格式）。

软件不内置大模型，而是通过标准 MCP 端点把本机能力暴露给任意支持 MCP 的 AI 助手。
这里只声明工具名称、描述与参数 JSON Schema；具体执行在 app.py 的 execute_ai_tool。
"""

TOOL_DEFS = [
    {"name": "get_app_status",
     "description": "查询软件运行状态、版本、监控项数量、启用数量、下次检查时间",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},

    {"name": "list_inventory",
     "description": "查询监控与库存列表，可按状态或品牌关键词过滤",
     "inputSchema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["in_stock", "out_of_stock", "unknown"],
                    "description": "可选：有货/缺货/未知"},
         "keyword": {"type": "string", "description": "可选，商品名或品牌关键词"}}}},

    {"name": "add_monitor_url",
     "description": "添加雪茄商品网页监控网址，添加后立即检查一次",
     "inputSchema": {"type": "object", "properties": {
         "url": {"type": "string", "description": "商品页完整 http/https 网址"},
         "name": {"type": "string", "description": "可选，留空自动抓取"}},
         "required": ["url"]}},

    {"name": "run_check",
     "description": "立即检查库存，可检查单个或全部启用项",
     "inputSchema": {"type": "object", "properties": {
         "url": {"type": "string", "description": "可选，指定单个商品网址；留空查全部"}}}},

    {"name": "set_enabled",
     "description": "启用或停用某个监控项（停用后不再自动检查，保留数据）",
     "inputSchema": {"type": "object", "properties": {
         "url": {"type": "string", "description": "商品网址"},
         "enabled": {"type": "boolean", "description": "true 启用 / false 停用"}},
         "required": ["url", "enabled"]}},

    {"name": "delete_monitor",
     "description": "永久删除一个监控项及其检查日志，不可恢复",
     "inputSchema": {"type": "object", "properties": {
         "url": {"type": "string", "description": "要删除的商品网址"}},
         "required": ["url"]}},

    {"name": "calculate_landed_cost",
     "description": "按汇率和税费估算雪茄到手价（人民币），烟草税率50%",
     "inputSchema": {"type": "object", "properties": {
         "currency": {"type": "string", "description": "货币代码，如 EUR/USD/GBP",
                      "default": "EUR"},
         "price": {"type": "number", "description": "商品单价（外币）"},
         "count": {"type": "integer", "description": "数量，默认 1", "default": 1},
         "shipping": {"type": "number", "description": "运费（外币），默认 0",
                      "default": 0}},
         "required": ["price"]}},

    {"name": "manage_address",
     "description": "读取或保存英文收货地址",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["get", "save"]},
         "line1": {"type": "string"}, "line2": {"type": "string"},
         "country": {"type": "string"}, "state": {"type": "string"},
         "city": {"type": "string"}, "zip": {"type": "string"}},
         "required": ["action"]}},
]
