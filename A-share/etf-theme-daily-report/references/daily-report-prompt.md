# Daily Report Prompt

Use this prompt when creating a scheduled daily task after the user has built or started the ETF theme account.

## Recommended Scheduled Prompt

```text
使用 $etf-theme-daily-report 生成今天的 ETF 主题账户日报。

账户计划：
- 本金上限：{principal_cap} 元，若未填写则按 400,000 元默认。
- 标的与目标权重：159530 机器人 30%、159994 通信 25%、515260 电子 20%、159516 半导体设备材料国泰 15%、159538 信创 10%。
- 融资只在组合从阶段高点回撤 10%/15%/20% 时启用，不做日常加仓。

请完成：
1. 拉取或检索截至今天收盘后的最新市场数据；如果今天还未收盘，则明确标注为盘中版。
2. 分析宏观面：A 股整体风险偏好、流动性、人民币汇率、海外科技股/半导体隔夜影响、重要政策或监管因素。
3. 分析板块面：半导体、半导体设备材料、电子、通信/AI 硬件、机器人、信创的强弱、轮动和资金偏好。
4. 汇总重大利好和重大利空，按对本组合影响排序，不要堆砌无关新闻。
5. 判断主题是否过热、只是正常回调、还是进入恐慌/洗盘区间。
6. 检查 5 只 ETF 的价格表现、短期趋势、阶段回撤，以及若我提供持仓则检查当前权重。
7. 严格按 ETF 主题账户执行计划判断：今天是 no action、watch、ordinary principal add、rebalance review、margin eligible、de-risk/repay margin，还是 plan exception。
8. 给出明日观察清单：具体价格/回撤/权重/新闻触发点。

输出要求：
- 中文。
- 先给一句话结论。
- 明确区分事实、假设和判断。
- 如果数据不全，列出缺失项，不要硬凑。
- 不要因为单日大跌就建议融资；融资必须满足计划中的组合回撤阈值。
```

## Minimal Prompt

```text
使用 $etf-theme-daily-report 生成今天的 ETF 主题账户日报，按执行计划判断是否需要加仓、再平衡、观察或启用融资。
```

## Optional User Variables

Ask the user to fill these when setting up automation:

| Variable | Example |
|---|---|
| `{principal_cap}` | `400000` |
| `{report_time}` | `每个 A 股交易日 15:30` |
| `{holdings_source}` | `我每天手动贴持仓截图` / `使用 operation-log.csv` |
| `{delivery_channel}` | `当前 Codex 线程` / `邮件` / `Notion` |

## Report Title Format

```text
ETF 主题账户日报 - YYYY-MM-DD
```
