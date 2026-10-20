# CS电子报按年份并行采集 v3

基于 v2.4 解析器。一个工作进程负责一年，每天完成后原子重建该年份 JSONL；每天的状态独立保存在 `data/raw/cs/state_by_year/YEAR/YYYY-MM-DD.json`。按 Ctrl+C 停止；重新运行相同命令会跳过 complete 日期，重新采集 partial/failed/unavailable 日期。注意：失败日期的重试是按整天重抓，不是按单篇重抓。`--force-date` 会重新采集所有日期，请勿日常使用。

先备份原有数据，不要把旧版 v2.3 产生的错误 `complete` 状态文件复制到新年份状态目录中。

```bash
pip install -r requirements.txt
python run_parallel.py --start 2024-06-28 --end 2024-06-28 --workers 1 --delay 3
python check_years.py
# 版面归属通过且抽查正常之后
python run_parallel.py --start 2016-01-01 --end 2024-06-30 --workers 2 --delay 3
python check_years.py
```

测试可用 `--limit-days 2`（每个年份最多处理2天）。建议从2个进程开始，不要一上来开9个，以免触发429/403。两进程各自按 `--delay` 控速，参数不是全局频率限制。运行日志 `logs/cs/cs_YEAR.log`。保存到 `data/raw/cs/cs_epaper_YEAR.jsonl`，每行是一天。若中途强制断电，最后一天可能没有状态或尚未保存，重启后会重试。

**提醒：** 输出 `status=complete` 是程序层状态，不代表历史内容已人工核验。v2.4 版面过滤对 2016 老模板仍需核验。注意仅处理所在版面的文章链接，且默认跳过信息披露版面。
