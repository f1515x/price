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

`signals` 和 `sizes` 使用 `market/quarterly.py` 的月度综合均值作为动态阈值：
`T = (Perf.1M + 最近一个完整 UTC 自然月振幅) / 2`，单位为百分数。
当 `Perf.1M > T`、`ratio > T / 100` 且 weak 类型为 `high` 时，挂单价为 weak price 的 1.01 倍；
当 `Perf.1M < -T`、`ratio < -T / 100` 且 weak 类型为 `low` 时，挂单价为 weak price 的 0.99 倍。
比较使用严格不等式，保留综合均值的符号及完整精度，两位小数仅用于展示；月度数据获取失败时报告错误。
Python 调用需显式传入阈值：`price(perf_1m, structure, combined_average)`。

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

### 将 Sizes 写入 Supabase

`supabase.py` 通过 REST API 连接数据库，使用 Python 标准库，无需额外安装依赖。
在根目录 `.env` 填写 `SUPABASE_URL`（项目地址）、`SUPABASE_KEY` 和
`SUPABASE_TABLE=orders`，参考 `.env.example`。环境变量优先于 `.env`。

首次使用，在 Supabase SQL Editor 执行 [`docs/supabase_sizes.sql`](docs/supabase_sizes.sql)，
为现有 `orders` 表添加 `contract`、`activation_price`、`side`、`amount`、`value`、`timestamp` 列。
每次非空写入前，脚本先删除目标表的全部旧记录（包括 `contract` 为 NULL 的历史记录），再批量插入新记录。价格和价值使用 `numeric`，张数保留多空正负号，
`timestamp` 保存报告末尾的 Unix 毫秒时间戳；没有时间戳时写入 NULL。

```powershell
python supabase.py --check-only
# 预览解析结果，不连接数据库
python supabase.py --dry-run
# 默认读取 reports/sizes.txt，先清空目标表，再一次请求批量插入所有订单
python supabase.py
# 显式指定 Sizes 文件
python supabase.py --sizes-file reports/sizes.txt --minimal
# 兼容显式 JSON 对象或对象数组
python supabase.py --data-file test_order.json
```

每个 Order Alert 对应一条记录，单位和图标不会写入数据库。数字字符串由数据库转为 numeric，
避免解析时丢失小数精度。空报告或只有 `none` / 时间戳时跳过写入；格式错误时终止整个批次。
重复运行同一文件会替换旧记录，不再追加重复记录。删除失败时立即终止，不执行插入。
删除和插入是两次独立请求，并非原子事务；插入失败时目标表可能为空，需修复原因后重新运行。避免并发上传到同一张表。
成功时输出条数、HTTP 状态及插入记录，失败时输出原因并以退出码 1 结束。
`--minimal` 可以避免返回插入记录；清空旧记录始终不返回数据，连接检查需要 SELECT 权限。
如果提示 `42501` 或 `row-level security`，说明数据库拒绝当前身份读写：
需要配置表的 SELECT / INSERT / DELETE 权限及策略，或在本地 `.env` 配置服务端 secret key。
启用 RLS 时，DELETE 只能删除 SELECT 策略可见且 DELETE 策略允许的行；要清空整表，须允许当前身份删除全部行，或使用服务端密钥。
服务端密钥不要提交到 Git。使用登录用户权限时可配置 `SUPABASE_ACCESS_TOKEN` 为用户 JWT。

### GitHub Actions 的 Repository secrets

在 GitHub 仓库的 **Settings → Secrets and variables → Actions → Repository secrets → New repository secret** 中添加以下配置。远端 CI 不读取本地 `.env`，凭据由工作流通过环境变量传入。

| Secret 名称 | 是否必填 | 内容 |
| --- | --- | --- |
| `SUPABASE_URL` | 新增，必填 | Supabase 项目地址，例如 `https://<项目>.supabase.co`，不包含表名。 |
| `SUPABASE_KEY` | 新增，必填 | Supabase API key，必须具有目标表的 INSERT / DELETE 权限，并能删除全部行；可使用服务端 secret key 或 legacy `service_role` key。 |
| `SUPABASE_TABLE` | 新增，可选 | 目标表名；不配置时使用 `orders`。 |
| `SUPABASE_ACCESS_TOKEN` | 新增，可选 | 使用登录用户权限时填写用户 JWT；使用服务端密钥时无需配置。 |
| `API_KEY` | 原有，必填 | Gate.io API key，用于仓位计算中的账户请求。 |
| `API_SECRET` | 原有，必填 | Gate.io API secret。 |
| `TELEGRAM_BOT_TOKEN` | 原有，必填 | Telegram Bot token，用于发送 sizes 报告。 |

CI 首次运行前，也需在 Supabase 执行上面的 SQL 脚本；使用自定义表名时，确保该表具备相同列结构及写入权限。

`run.yml` 保留每四小时一次的 UTC 定时和 `main` push 触发；手动执行可选分支。工作顺序为精度更新 → 仓位和信号计算 → 写入 Supabase → Telegram 通知 → 提交生成文件。上传命令为 `python supabase.py --sizes-file reports/sizes.txt --minimal`：没有订单时跳过写入，上传失败时工作流失败并停止后续步骤；每次非空上传先清空目标表，再插入当前报告，重复执行不再追加重复记录。凭据直接使用 Actions 环境变量，不再创建临时 `.env`。部署时需一并提交 `supabase.py`，确保远端 checkout 后可以运行上传脚本。

`ci.yml` 在 `main`、`1` 分支及 PR 执行离线测试：

```powershell
python -m unittest discover -s tests -v
```

测试覆盖：无密钥导入/帮助、配置优先级、策略阈值、SMC 迁移基线、ATR、精度、模拟精度到仓位流程、多空符号、无信号跳过账户接口、K 线合并、消息分段和兼容导入。迁移时核对了五个配置/数据/报告文件，除 Git 换行规范外内容不变。

此次迁移没有执行真实账户查询或 Telegram 发送；外部服务可用性需要在配置凭据后验证。依赖版本锁定、K 线断档补齐和交易允许步长校验尚未加入，详见架构文档。
