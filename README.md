# price-monitor

Gate.io USDT 永续合约行情分析、信号价格、建议仓位和 Telegram 通知工具。代码已在 `1` 分支迁移为 `src` 包结构；原根目录 Python 脚本保留为兼容入口。工具计算并通知，不执行下单。

## 实际目录树

```text
price/
├── .github/workflows/
│   ├── ci.yml                       # main / 1 分支与 PR 的离线测试
│   └── run.yml                      # 定时计算、通知、提交结果
├── .env.example                     # 环境变量示例
├── .gitattributes
├── .gitignore
├── pyproject.toml                   # 包元数据、依赖与 CLI
├── requirements.txt                 # 兼容安装入口：-e .
├── README.md
├── config/
│   ├── symbols.txt                  # 原 symbol.txt
│   └── chat_ids.txt                 # 原 id.txt，保留现有接收者
├── data/
│   └── price_steps.json             # 原 float.js
├── reports/
│   ├── sizes.txt                    # 原 size.txt，工作流主报告
│   └── signals.txt                  # 原 price.txt，历史报告保留
├── src/price_monitor/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                       # 统一命令入口
│   ├── settings.py                  # 路径、.env、环境变量与密钥加载
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── gate.py                  # 签名、合约杠杆与账户保证金请求
│   │   └── telegram.py              # 消息分段、发送与重试
│   ├── market/
│   │   ├── __init__.py
│   │   ├── candles.py               # 1h K 线更新与合并
│   │   ├── performance.py           # TradingView 月涨跌幅
│   │   └── precision.py             # 价格文本精度映射
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── structure.py             # Swing / Strong / Weak 状态计算
│   │   └── indicators.py            # ATR14、r 值与分类
│   ├── strategy/
│   │   ├── __init__.py
│   │   └── signals.py               # 信号条件、FINAL_PRICE 与分析编排
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── allocation.py            # 最大开仓、1% 仓位建议与 CLI
│   │   └── sizing.py                # 有符号张数、输入校验与仓位编排
│   └── reporting/
│       ├── __init__.py
│       └── text.py                  # 中文宽度与报告对齐
├── tests/
│   ├── test_monitor.py              # 离线行为及迁移回归测试
│   └── fixtures/
│       └── structure_expected.json  # 迁移前代码的合成行情基线
├── docs/
│   └── architecture.md              # 依赖树、迁移映射与后续边界
└── amount.py / float.py / kline.py / month.py /
    price.py / size.py / smc.py / tele_gate.py  # 兼容入口
```

运行时 K 线缓存写入 `data/candles/<SYMBOL>.json`，该目录已忽略。精度映射与报告继续跟踪和提交，保留原来的结果发布方式。

## 安装与使用

Python 3.10 或以上；CI 使用 Python 3.12。仓库根目录执行：

```powershell
python -m pip install -e .
python -m price_monitor --help
price-monitor candles BTC
price-monitor performance BTC
price-monitor structure BTC
price-monitor signals BTC ETH
price-monitor precision
price-monitor allocation --contract BTC_USDT
price-monitor sizes BTC ETH
```

`precision` 默认读取 `config/symbols.txt`，输出 `data/price_steps.json`；也可使用 `--file`、`--output`。`structure` 支持币种或本地 CSV/JSON/JS 文件。

根目录脚本调用仍可用，例如 `python size.py BTC ETH`、`python float.py`、`python smc.py BTC`。Python 导入旧模块会映射到包内实现；默认数据路径采用新目录。显式指定的路径不会自动转换，例如旧调用 `--output float.js` 仍会写该路径。

## 配置与通知

在根目录 `.env` 中配置，或设置同名环境变量；进程环境变量优先：

```dotenv
API_KEY=
API_SECRET=
TELEGRAM_BOT_TOKEN=
```

密钥只在调用签名账户接口时校验，导入模块和查看帮助无需密钥。Telegram 也支持根目录 `.env`。

`config/symbols.txt` 配置币种；`config/chat_ids.txt` 配置接收者。以下命令会向这些接收者发送报告：

```powershell
price-monitor notify
# 或显式指定文件
price-monitor notify reports/sizes.txt config/chat_ids.txt
```

默认运行根目录在源码安装时自动识别。打包安装或需要隔离运行数据时，设置 `PRICE_MONITOR_ROOT` 指向包含 `config/`、`data/`、`reports/` 和可选 `.env` 的目录。

## 自动化与验证

`run.yml` 保留每四小时一次的 UTC 定时和 `main` push 触发；手动执行可选分支。工作顺序已改成精度更新 → 仓位计算 → 通知 → 提交生成文件。凭据直接使用 Actions 环境变量，不再创建临时 `.env`。

`ci.yml` 在 `main`、`1` 分支及 PR 执行离线测试：

```powershell
python -m unittest discover -s tests -v
```

测试覆盖：无密钥导入/帮助、配置优先级、策略阈值、SMC 迁移基线、ATR、精度、模拟精度到仓位流程、多空符号、无信号跳过账户接口、K 线合并、消息分段和兼容导入。迁移时核对了五个配置/数据/报告文件，除 Git 换行规范外内容不变。

此次迁移没有执行真实账户查询或 Telegram 发送；外部服务可用性需要在配置凭据后验证。依赖版本锁定、K 线断档补齐和交易允许步长校验尚未加入，详见架构文档。
