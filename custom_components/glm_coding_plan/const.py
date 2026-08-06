"""Constants for the GLM Coding Plan integration."""
DOMAIN = "glm_coding_plan"

# ===== 配置项字段名 =====
CONF_TOKEN = "token"
CONF_ENDPOINT = "endpoint"
CONF_NAME = "name"

# ===== 端点定义（与官方 glm-plan-usage 插件、glm-usage-monitor 同源）=====
ENDPOINTS = {
    "zhipu": {
        "label": "智谱国内 (open.bigmodel.cn)",
        "base_url": "https://open.bigmodel.cn/api/anthropic",
    },
    "zai": {
        "label": "Z.ai 国际 (api.z.ai)",
        "base_url": "https://api.z.ai/api/anthropic",
    },
}

DEFAULT_ENDPOINT = "zhipu"

# ===== 配额 type 枚举（实测，2026-08）=====
# TOKENS_LIMIT : Token 用量百分比配额（5 小时窗口），仅有 percentage + nextResetTime
# TIME_LIMIT   : MCP 工具调用次数配额（月窗口），有 usage/currentValue/remaining + 明细
QUOTA_TYPE_TOKENS = "TOKENS_LIMIT"
QUOTA_TYPE_TIME = "TIME_LIMIT"

# 配额窗口 unit 枚举（实测）：3=小时, 4=天, 5=月, 6=周
QUOTA_UNIT_MAP = {3: "小时", 4: "天", 5: "月", 6: "周"}

# ===== 用量时间窗口定义 =====
# 关键发现（实测）：model-usage 的 totalUsage 是【窗口内用量】而非历史累计，
# 故"今日/本周/本月"需用不同时间窗口分别查询。
# WIDGET_KEY 同时也是 sensor 定义的 key，贯穿 const → sensor。
WINDOW_TODAY = "today"      # 今日：从当天 00:00 到现在
WINDOW_WEEK = "week"        # 本周：最近 7 天（168h）
WINDOW_MONTH = "month"      # 本月：最近 30 天（720h）

# 周期标签（用于传感器名、attributes）
WINDOW_LABELS = {
    WINDOW_TODAY: "今日",
    WINDOW_WEEK: "本周",
    WINDOW_MONTH: "本月",
}

# ===== 传感器类型 =====
# 维度组织（按用户确认）：Token 用量按 今日/本周/本月；配额保留 5h%MCP月度；历史每日作 attributes
SENSOR_TYPES = {
    # —— Token 用量（按周期）——
    "tokens_today": {
        "name": "Token 用量 (今日)",
        "icon": "mdi:counter",
        "kind": "period_tokens",
        "window": WINDOW_TODAY,
    },
    "tokens_week": {
        "name": "Token 用量 (本周)",
        "icon": "mdi:counter",
        "kind": "period_tokens",
        "window": WINDOW_WEEK,
    },
    "tokens_month": {
        "name": "Token 用量 (本月)",
        "icon": "mdi:counter",
        "kind": "period_tokens",
        "window": WINDOW_MONTH,
    },
    # —— 调用次数（按周期）——
    "calls_today": {
        "name": "模型调用次数 (今日)",
        "icon": "mdi:robot-outline",
        "kind": "period_calls",
        "window": WINDOW_TODAY,
    },
    "calls_week": {
        "name": "模型调用次数 (本周)",
        "icon": "mdi:robot-outline",
        "kind": "period_calls",
        "window": WINDOW_WEEK,
    },
    "calls_month": {
        "name": "模型调用次数 (本月)",
        "icon": "mdi:robot-outline",
        "kind": "period_calls",
        "window": WINDOW_MONTH,
    },
    # —— 配额（state = 剩余百分比，更直观）——
    "quota_tokens_5h": {
        "name": "五小时剩余配额",
        "icon": "mdi:progress-clock",
        "kind": "quota_tokens",
        "match_type": QUOTA_TYPE_TOKENS,
        "match_unit": 3,
    },
    "quota_mcp_month": {
        "name": "本月 MCP 工具剩余",
        "icon": "mdi:toolbox-outline",
        "kind": "quota_time",
        "match_type": QUOTA_TYPE_TIME,
        "match_unit": 5,
    },
    # —— 套餐等级 ——
    "plan_level": {
        "name": "套餐等级",
        "icon": "mdi:medal-outline",
        "kind": "plan_level",
    },
}

# ===== API 端点路径 =====
API_PATH_MODEL_USAGE = "/api/monitor/usage/model-usage"
API_PATH_TOOL_USAGE = "/api/monitor/usage/tool-usage"
API_PATH_QUOTA_LIMIT = "/api/monitor/usage/quota/limit"
