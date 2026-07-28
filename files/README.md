# 同步文件目录（全项目统一）

所有从共享盘同步过来的业务 Excel **只放这里**。同步脚本只需对准本目录。

## 宿主机路径

```text
/yida/dingtalk-bots/files/          # 服务器 monorepo 根下
├── 全站点地址.xlsx                 # CP 发货单核对 · 地址簿
└── 产品信息单证专用.xlsx           # 不分仓拼箱 · 产品箱规
```

本地开发同理：仓库根目录 `files/`。

## 容器内路径

Docker 挂载：`./files` → `/app/files`（只读）

| 文件 | 容器内完整路径 | 环境变量 |
|------|----------------|----------|
| 全站点地址.xlsx | `/app/files/全站点地址.xlsx` | `ADDRESS_BOOK_XLSX_PATH` |
| 产品信息单证专用.xlsx | `/app/files/产品信息单证专用.xlsx` | `PINXIANG_PRODUCT_INFO_PATH` |

## 同步建议

```bash
# 原子替换示例
rsync -az "全站点地址.xlsx" cloud:/yida/dingtalk-bots/files/全站点地址.xlsx.tmp
ssh cloud 'mv /yida/dingtalk-bots/files/全站点地址.xlsx.tmp /yida/dingtalk-bots/files/全站点地址.xlsx'

rsync -az "产品信息单证专用.xlsx" cloud:/yida/dingtalk-bots/files/产品信息单证专用.xlsx.tmp
ssh cloud 'mv /yida/dingtalk-bots/files/产品信息单证专用.xlsx.tmp /yida/dingtalk-bots/files/产品信息单证专用.xlsx'
```

文件名请保持上表固定，便于脚本与 env 约定。
