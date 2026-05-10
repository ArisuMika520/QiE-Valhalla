## QiE Valhalla(英灵殿)

<div align="center">
  <img src="static\CJLU_icon.png" width="400" alt="SoftPal-Sakura Background" />
</div>

QiE Valhalla 是一个本地运行的 QiE 群管理数据采集归档工具，用于定时保存群列表和群成员快照，方便在群聊异常、不可抗损坏或迁移时保留可核对的基础数据。

## PM2 进程管理

归档轮询间隔由 `.env` 中的 `QQ_VALHALLA_POLL_SECONDS` 控制，当前建议值为 `86400`，即 24 小时归档一次。

常用命令：

```bash
# 启动全部进程
pm2 start ecosystem.config.cjs

# 只启动归档或页面服务
pm2 start ecosystem.config.cjs --only qie-valhalla-watch
pm2 start ecosystem.config.cjs --only qie-valhalla-dashboard

# 查看状态与日志
pm2 status
pm2 logs qie-valhalla-watch
pm2 logs qie-valhalla-dashboard

# 重启、停止、移除
pm2 restart ecosystem.config.cjs --update-env
pm2 stop qie-valhalla-watch qie-valhalla-dashboard
pm2 delete qie-valhalla-watch qie-valhalla-dashboard

# 保存当前进程列表，配合 pm2 startup 做开机自启
pm2 save
pm2 startup
```

`.env` 或 PM2 配置变更后，请执行：

```bash
pm2 restart ecosystem.config.cjs --update-env
```

## 啥也没有，QiE你赢了