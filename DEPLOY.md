# WorldCupPredictor 云端持续更新部署

本项目当前在 `D:\WorldCupPredictor`。如果电脑关机，本地的 `127.0.0.1:4173`、实时比分桥接、新闻桥接都会停止。要在电脑关机后继续更新，必须把项目放到云服务器、NAS、家里另一台常开电脑、GitHub Actions、云函数等外部运行环境。

## 推荐方案：VPS + Docker（15 秒级）

这是最接近“比赛开始后仍实时更新”的方案。云服务器不断电，网页和数据采集器都在云端跑。

最省事的部署方式是在 Ubuntu VPS 上运行：

```bash
curl -fsSL https://raw.githubusercontent.com/CHNDANG/WorldCupPredictor/main/deploy-vps.sh -o deploy-vps.sh
sudo bash deploy-vps.sh
```

部署完成后打开：

```text
http://服务器IP:4173/worldcup-predictions.html
```

健康检查：

```text
http://服务器IP:4173/healthz
http://服务器IP:4173/api/status.json
```

查看日志：

```bash
docker compose logs -f
```

如果有 The Odds API 密钥，在 `docker-compose.yml` 里配置：

```yaml
ODDS_API_KEY: "你的密钥"
```

## 备选方案：GitHub Actions

`.github/workflows/refresh-data.yml` 会每 5 分钟刷新一次数据并提交到仓库。优点是免费、简单；缺点是延迟高，不能做到 15 秒级赛中更新。

适合：

- 新闻和赛程校验
- 已完赛结果回写
- 非秒级赔率/比分刷新

不适合：

- 进球后马上更新
- 需要 15 秒轮询的赛中预测

## 本机方案

只要电脑开机，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File D:\WorldCupPredictor\start-site.ps1
```

本机地址：

```text
http://127.0.0.1:4173/worldcup-predictions.html
```

## 数据保护

实时桥接已经增加保护：如果 ESPN scoreboard 临时返回空比赛列表，不会覆盖上一份有效 `live-feed.json`，而是保留上一份有效数据并标记：

```json
"sourceStatus": "empty-scoreboard-retained-last-valid"
```

## 准确性原则

- 比赛时间应以 `kickoffUtc` 为锚点，再统一换算北京时间显示。
- 赛中预测应优先使用真实比分、分钟、红黄牌、射门/射正/角球/xG代理、换人、盘口与赔率变化。
- 新闻和赔率只能使用可验证来源；抓不到时不编造。
