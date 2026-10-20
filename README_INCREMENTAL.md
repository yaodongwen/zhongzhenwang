# v3.2 增量补爬说明

- 保留每日期 state_by_year/YYYY/YYYY-MM-DD.json 中已成功的文章和 non_articles。
- 重新读取每日版面列表，跳过已有URL，只抓列表中新发现的缺失文章。
- 已成功文章按content_hash保留；以URL跳过已知内容。
- 每年一个独立JSONL，按日期状态原子重建。
- 如果此前某日没有成功文章，仍然需要抓取当日全部文章。
- `--force-date` 会覆盖增量模式，强制全量重建指定日期。
- 不修改旧历史失败日志；每次最新失败数以新的日期状态为准。
- 请先Ctrl+C停止旧任务，备份data目录，安装新脚本，再以原命令重新运行。
- 新增DATE日志的reused（复用）/fetched（新抓）数。
- 本版仍是按版面重新发现URL，不支持在不请求版面页面的前提下获取完整失效URL。

## v3.3 新增：实时进度

- `run_parallel.py` 默认每20秒输出一行 `PROGRESS` 总体进度，可用 `--progress-interval 10` 调整；不改变爬虫请求间隔。
- 不停止现有任务也能在新终端使用 `python progress.py --watch 10 --start 2016-01-01 --end 2017-12-31` 查看状态。
- 查看全部2016—2024范围：`python progress.py --start 2016-01-01 --end 2024-06-30`。
- 进度按 `data/raw/cs/state_by_year/YYYY/YYYY-MM-DD.json` 计数，不以日志行数估计。已处理含失败和 unavailable，因此另列 complete 日期。
- 单日JSONL仍逐日保存；状态有历史遗留时也计入当前统计。该监控不会篡改数据。
- 如果抓取任务已经运行，不必立刻停止：复制 `progress.py` 单文件即可即时查看进度。只有下次启动才会看到主终端进度条。
