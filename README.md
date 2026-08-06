# GLM Coding Plan for Home Assistant

在 Home Assistant 里监控 **智谱 / Z.ai GLM Coding Plan** 的用量与配额。

直接调用智谱官方监控接口（与官方 `glm-plan-usage` 插件、[glm-usage-monitor](https://github.com/) 同源），填入自己的 Token 即可使用——**不依赖 Claude Code，不读取任何本地配置文件**。

## ✨ 特性

- 📊 **三周期用量** —— 今日 / 本周 / 本月 的 Token 用量与调用次数
- 📅 **历史每日数据** —— 最近 30 天每天的用量，作为传感器属性查看
- ⏱ **配额剩余** —— 5 小时窗口 + MCP 工具月度配额，显示**剩余百分比**，临近告警一目了然
- 👥 **多账号** —— 每个集成实例独立成设备，可同时监控多个账号
- 🎨 **本地品牌图标** —— HA 2026.3+ 自动加载 GLM 图标，无需联网获取
- 🔐 **Token 加固** —— 输入框密码掩码、唯一 ID 用 SHA-256 指纹、options 不回显旧值

## 🚀 安装

### 方式一：手动安装（HACS 自定义仓库）

1. 下载本仓库，把 `custom_components/glm_coding_plan` 整个目录复制到 HA 的 `config/custom_components/` 下
2. **重启 Home Assistant**
3. 设置 → 设备与服务 → 添加集成 → 搜索「**GLM Coding Plan**」
4. 填入 Token、选择端点、自定义名称 → 完成

### 目录结构

```
config/custom_components/glm_coding_plan/
├── __init__.py        # 集成入口 + DataUpdateCoordinator（5 分钟轮询）
├── config_flow.py     # 可视化配置流程（含 Re-auth / Options）
├── glm_api.py         # GLM 监控接口客户端
├── sensor.py          # 传感器实体
├── const.py           # 常量与传感器定义
├── manifest.json
├── strings.json
├── brand/             # 本地品牌图标（HA 2026.3+）
│   ├── icon.png
│   ├── dark_icon.png
│   └── logo.png
└── translations/
    ├── en.json
    └── zh-Hans.json
```

## 🔑 获取 Token

1. 访问 [open.bigmodel.cn](https://open.bigmodel.cn)（国内）或 [z.ai](https://z.ai)（国际）
2. 开通 **GLM Coding Plan** 套餐
3. 在控制台创建 / 查看 API Key（格式 `xxxxxxxx.yyyyyyyy`）
4. 粘贴进集成配置的「Token」栏

## 📡 传感器

添加集成后，每个账号生成 **1 个设备 + 9 个传感器**：

| 传感器 | State | 说明 |
|--------|-------|------|
| **Token 用量 (今日)** | Token 数 | 从今天 00:00 累计 |
| **Token 用量 (本周)** | Token 数 | 最近 7 天 |
| **Token 用量 (本月)** | Token 数 | 最近 30 天 |
| **模型调用次数 (今日)** | 次数 | — |
| **模型调用次数 (本周)** | 次数 | — |
| **模型调用次数 (本月)** | 次数 | — |
| **五小时剩余配额** | 剩余 % | GLM 5 小时窗口 Token 配额 |
| **本月 MCP 工具剩余** | 剩余 % | MCP 工具月度调用配额 |
| **套餐等级** | 文本 | 如 `max`、`pro` |

**传感器属性**（在实体详情页可见）：

- Token 用量传感器：`by_model`（各模型明细）、`daily_history`（最近 30 天每日用量）
- 配额传感器：`used_percent`（已用百分比）、`used` / `total` / `remaining`、`next_reset_time`（重置时间）
- MCP 配额传感器：`usage_details`（search-prime / web-reader / zread 明细）

## 👥 多账号配置

本集成支持同时监控多个 GLM 账号。每个账号是独立的集成实例：

1. 添加集成 → 填入账号 A 的 Token，名称填「**工作号**」
2. 再次添加集成 → 填入账号 B 的 Token，名称填「**个人号**」

两个账号各自生成独立设备，互不干扰。建议名称填能区分的名字（默认为 "GLM Coding Plan"）。

> GLM 监控接口不返回用户名，故无法自动获取账号名称，需手动填写。

## 🛠 配置项

在集成卡片点「⚙ 配置」可随时修改：

| 配置项 | 说明 |
|--------|------|
| **名称** | HA 里的设备名（用于多账号区分）|
| **Token** | 留空则保留原值，输入新值会覆盖 |
| **端点** | 智谱国内 (open.bigmodel.cn) / Z.ai 国际 (api.z.ai) |

修改后自动重新校验并生效，无需重启 HA。

## 🔒 隐私与安全

- **Token 仅存本机**：保存在 HA 的 `.storage/core.config_entries`（与所有 HA 集成的凭证存储方式一致）
- **输入密码掩码**：配置界面 Token 以 `••••••` 显示
- **唯一 ID 加密**：集成唯一 ID 使用 Token 的 SHA-256 指纹，不含明文
- **options 不回显**：打开配置时 Token 输入框为空，不暴露旧值
- **无第三方上报**：仅向你选择的智谱/Z.ai 端点发起请求

> ⚠️ 注意：HA 架构上 config entry 不支持加密存储（所有官方集成的密码/Token 均为明文）。若要进一步降低风险：不要把 `.storage` 目录提交到公开仓库；GLM Token 可在智谱控制台随时吊销。

## 📐 数据源

直接调用智谱官方监控接口（需 GLM Coding Plan 订阅）：

| 接口 | 用途 |
|------|------|
| `…/api/monitor/usage/model-usage` | 模型 Token 用量、调用次数、时间序列 |
| `…/api/monitor/usage/tool-usage` | MCP 工具（联网搜索/Web读/Zread）用量 |
| `…/api/monitor/usage/quota/limit` | 配额上限（5h Token / 月度 MCP）|

认证头：`Authorization: <Token>`（直接传 Token，**不带 `Bearer ` 前缀**）

> **关键**：`model-usage` 的 `totalUsage` 是**时间窗口内用量**而非历史累计，故「今日/本周/本月」通过不同时间窗口分别查询得出。

## 🏗 技术栈

| 层 | 技术 |
|----|------|
| 配置流程 | `config_flow` + `TextSelector`（密码掩码）|
| 数据拉取 | `DataUpdateCoordinator`，5 分钟轮询 |
| HTTP | `requests`（在 executor 线程执行，不阻塞事件循环）|
| 图标 | 本地 `brand/` 目录（HA 2026.3+）|

## 📄 License

[MIT](LICENSE)，欢迎自行修改、分发、二次开发。
