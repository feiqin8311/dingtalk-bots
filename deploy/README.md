# Deploy

## 日常发版（改业务代码）

```bash
./deploy/deploy.sh
```

流程：`rsync` 源码 → `docker compose up --force-recreate --no-build`  
**不跑 pip**，通常十几秒。容器通过 volume 挂载 `apps/` 与 `shared/`。

## 依赖变更（改了 requirements.txt）

```bash
./deploy/deploy.sh --rebuild
```

走服务器代理 `http://172.17.0.1:20171`（sing-box）装包。

## 配置

```bash
cp deploy/deploy.env.example deploy/deploy.env
# 填 DEPLOY_SSH_PASS 或配置 SSH key
```

| 变量 | 默认 |
|------|------|
| `DEPLOY_HOST` | `121.41.4.126` |
| `DEPLOY_PATH` | `/yida/dingtalk-bots` |
| `BUILD_HTTP_PROXY` | `http://172.17.0.1:20171` |

## 保留项（不同步覆盖）

- 各 app 的 `.env`
- `files/*.xlsx`
- `**/.bot-workspace`、`downloads`、`.state`
