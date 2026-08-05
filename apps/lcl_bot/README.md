# 分仓拼箱（lcl_bot）

原独立项目 `dingtalk-lcl-bot`，现作为物流部机器人菜单 **4. 分仓拼箱**。

## 入口

统一 Stream：`apps/logistics_bot` → 回复 `4`。

## 流程（与原 lcl 一致）

1. 物流上传发货单 Excel（需「发货单详情」等）→ **不做发票号登记**
2. 机器人拼箱 + 生成 Amazon Manifest 模板1
3. 物流 **确认** → **选择运营** → 只转发给该运营（拼箱结果 + 模板）
4. 运营可回【模板2】；可上传包装信息表回填
5. 后续领星删单 / 发货单号 / 清关等步骤仍走原逻辑（依赖登记的步骤会提示未登记）

## 配置

见 `env.example`。钉钉凭证可复用 logistics/cp `.env` 的 `DINGTALK_*` / `CLIENT_*`。

| 变量 | 说明 |
|------|------|
| `LCL_LOGISTICS_USERS` / `LOGISTICS_USERS` | 物流白名单（空=开放） |
| `PINXIANG_OPS_USERS` | 运营名单（与流程三不分仓共用） |
| `LCL_BASE_DIR` | 默认本 app 目录 |
| 登记表 UNC | `LCL_REGISTER_EXCEL_PATH` 等 |

## 依赖

- monorepo `requirements.txt` 已含 `pandas`
- 领星登记/删单/清关依赖宿主机上的 `Common` 包（`LCL_COMMON_ROOT`，默认 monorepo 上级 `yida/`）

## 注意

- **全局单工作流**（`Workflow_State/workflow_state.json`），同一时间只跑一单分仓流程
- 与菜单 **3. 不分仓拼箱** 算法/状态完全独立
