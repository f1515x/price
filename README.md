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
│   │   ├── infisical.py             # Universal Auth 与 Gate 凭证读取
│   │   ├── supabase.py              # 保留的 Supabase REST 工具
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
│   ├── architecture.md              # 依赖树、迁移映射与后续边界
│   ├── supabase_secret.sql          # 历史凭证表脚本，新部署不使用
│   └── supabase_sizes.sql           # 新建或升级订单表的报告字段
└── amount.py / float.py / kline.py / month.py /
    price.py / size.py / smc.py / tele_gate.py  # 兼容入口
```

运行时 K 线缓存写入 `data/candles/<SYMBOL>.json`，该目录已忽略。精度映射仅作为兼容报告，仓位计算不再读取该文件；精度映射与报告继续跟踪和提交，保留原来的结果发布方式。

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
INFISICAL_CLIENT_ID=
INFISICAL_CLIENT_SECRET=
INFISICAL_PROJECT_ID=
INFISICAL_ENV=prod
INFISICAL_URL=https://us.infisical.com
INFISICAL_SECRET_PATH=/
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_KEY=
TELEGRAM_BOT_TOKEN=
```

Gate 凭证只从 Infisical 读取 `GATE_API_KEY` 和 `GATE_API_SECRET`，默认路径为 `/`。`settings.credentials()` 仍返回 `(API_KEY, API_SECRET)`，清理首尾空格及配对的外层引号；Gate 签名和请求格式保持不变。认证失败、权限错误、请求超时或密钥缺失/无效时直接报错，绝不回退到 Supabase、环境变量或 `.env` 中的旧 Gate 密钥。导入模块和查看帮助不连接外部服务。Telegram 也支持根目录 `.env`。

本地现有 `INFISICAL_ENVIRONMENT` 明确映射为 `INFISICAL_ENV` 的别名；同一来源同时配置时优先使用 `INFISICAL_ENV`，进程环境中的任一名称优先于文件中的配置。`INFISICAL_URL` 是服务根地址，默认使用官方美国云 `https://us.infisical.com`，欧洲云或自托管实例需填写实际地址（生产环境使用 HTTPS）。`INFISICAL_SECRET_PATH` 是密钥所在文件夹，必须与 Machine Identity 的读取权限一致。代码仅解析 Infisical 相关配置项，不输出配置值。

客户端复用现有 `requests`，不增加依赖。每次获取凭证都重新认证并只读取指定的两个共享密钥，不缓存或落盘 Access Token；请求有 20 秒超时，拒绝自动重定向，异常不包含请求体、响应体或敏感值。接口依据 [Universal Auth 登录文档](https://infisical.com/docs/api-reference/endpoints/universal-auth/login)与 [Secrets v4 读取文档](https://infisical.com/docs/api-reference/endpoints/secrets/read)。

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
创建 `orders` 表（尚不存在时），或为已有表补齐 `contract`、`activation_price`、`side`、`amount`、`value`、`timestamp`、`quanto_multiplier`、`order_price_round` 列。SQL 可重复执行，保留已有字段、约束和记录；新增数值参数采用不限制小数位数的 `numeric`。
每次非空写入直接删除目标表的全部旧记录（包括 `contract` 为 NULL 的历史记录），再批量插入报告中的新记录。价格和价值使用 `numeric`，张数保留多空正负号，
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
避免解析时丢失小数精度。没有 Order Alert、只有 `Timestamp`（可带 `none`）时，也先清空目标表，
再写入一条保留 `timestamp` 的记录，`contract`、`activation_price`、`side`、`amount`、`value`、`quanto_multiplier`、`order_price_round` 全部为 NULL，避免旧订单残留。
这些订单列需要允许 NULL；仓库提供的 SQL 新增列默认允许 NULL。真正的空报告或只有 `none` 时仍跳过写入；格式错误时终止整个批次。
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
| `INFISICAL_CLIENT_ID` | 必填 | Machine Identity 的 Universal Auth Client ID。 |
| `INFISICAL_CLIENT_SECRET` | 必填 | Machine Identity 的 Universal Auth Client Secret。 |
| `INFISICAL_PROJECT_ID` | 必填 | 存储 Gate 密钥的项目 ID。 |
| `INFISICAL_ENV` | 必填 | 环境标识，例如 `prod`；兼容已有 `INFISICAL_ENVIRONMENT` Secret，优先使用标准名称。 |
| `INFISICAL_URL` | 可选 | 实例根地址，默认 `https://us.infisical.com`。 |
| `INFISICAL_SECRET_PATH` | 可选 | 密钥路径，默认 `/`。 |
| `SUPABASE_URL` | 新增，必填 | Supabase 项目地址，例如 `https://<项目>.supabase.co`，不包含表名。 |
| `SUPABASE_KEY` | 新增，必填 | Supabase API key，必须能读取/新增/删除订单表全部行；可使用服务端 secret key 或 legacy `service_role` key。 |
| `SUPABASE_TABLE` | 新增，可选 | 目标表名；不配置时使用 `orders`。 |
| `SUPABASE_ACCESS_TOKEN` | 新增，可选 | 使用登录用户权限时填写用户 JWT；使用服务端密钥时无需配置。 |
| `TELEGRAM_BOT_TOKEN` | 原有，必填 | Telegram Bot token，用于发送 sizes 报告。 |

生产工作流首次运行前，需在 Infisical 配置两个 Gate 密钥与 Machine Identity 权限，并在 Supabase 执行上面的订单 SQL；使用自定义表名时，确保该表具备相同列结构及写入权限。离线 Checks 无需真实凭据。

`run.yml` 保留每四小时一次的 UTC 定时和 `main` push 触发；手动执行可选分支。feature 分支 push 不运行真实数据库写入和通知，PR 只运行离线 Checks；合并到 main 或手动执行时才运行完整计算流程。工作顺序为精度更新 → 仓位和信号计算 → 写入 Supabase → Telegram 通知 → 提交生成文件。上传命令为 `python supabase.py --sizes-file reports/sizes.txt --minimal`：没有订单但有时间戳时，清空旧数据并写入一条订单字段为 NULL 的时间戳记录；上传失败时工作流失败并停止后续步骤。每次非空上传先清空目标表，再插入当前报告，重复执行不再追加重复记录。凭据直接使用 Actions 环境变量，不再创建临时 `.env`。部署时需一并提交 `supabase.py`，确保远端 checkout 后可以运行上传脚本。

`ci.yml` 在 `main`、`1` 分支及 PR 执行离线测试：

报告提交由 `scripts/commit_generated_files.sh` 处理：先保存本次生成的三个文件，再取目标分支最新提交，只替换 `reports/sizes.txt`、`reports/signals.txt` 和 `data/price_steps.json`，保留远端代码和其他文件。推送时若分支再次更新，最多尝试三次，始终使用普通推送；三次仍失败则明确报错。远端已有相同报告时不重复提交。相同分支的计算工作流排队执行，避免已有任务在写库或通知后被新任务取消。重试只涉及 Git 提交，不重复写库或发送通知。

远端 Checks 通过临时 Git 仓库验证旧 checkout、报告冲突、推送前并发更新、未跟踪报告、相同报告及持续拒绝推送的处理，不访问真实数据库或发送通知。

```powershell
python -m unittest discover -s tests -v
```

测试仅在远端 CI 运行，不做本地编译验证。Infisical 测试模拟认证和 Secret 响应，覆盖配置别名及优先级、自托管地址和路径、凭证清理、签名兼容、认证/权限/连接/超时错误、无效响应、隐藏或缺失密钥、禁止旧密钥回退和敏感信息不泄露，不使用真实 Gate 密钥。原有测试覆盖：无密钥导入/帮助、配置优先级、策略阈值、SMC 迁移基线、ATR、精度、模拟精度到仓位流程、多空符号、无信号跳过账户接口、K 线合并、消息分段和兼容导入。迁移时核对了五个配置/数据/报告文件，除 Git 换行规范外内容不变。

此次迁移没有执行真实账户查询或 Telegram 发送；外部服务可用性需要在配置凭据后验证。依赖版本锁定和 K 线断档补齐尚未加入，详见架构文档。


### Gate 凭证和合约参数

1. 在 Infisical 项目目标环境及路径创建 `GATE_API_KEY` 和 `GATE_API_SECRET`，填写真实 Gate 凭证，不提交至 Git。
2. 创建启用 Universal Auth 的 Machine Identity，并授予目标项目、环境、路径的密钥读取权限（含读取密钥值权限）。
3. 按上表在 Actions 配置四项必填 Infisical Secrets；自托管、不同云区域或非根路径还需配置可选项。本地开发在仓库根 `.env` 配置同样信息；本机父目录 `.env` 只作参考，不会自动加载。
4. Supabase 只负责订单数据，保留原有订单配置、权限和上传步骤；无需再为本项目创建或查询 `public.secret`。历史 SQL 保留供旧部署参考，不自动删除数据库中的旧记录；确认其他应用不再使用后，可人工清理旧 Gate 凭证。

`precision` 和仓位计算直接从 Gate 公开合约接口读取参数。价格步长、合约乘数和最大杠杆保留数字字符串，计算时转为 Decimal；价格按实际步长向下取整（包括 `0.25`），再换算张数，保持 1% 建议仓位、多空符号和无信号返回 none 的规则。

每条新订单在原有展示字段之后追加 `quanto_multiplier` 和 `order_price_round`，原样保留 Gate 数字字符串。一次仓位计算只获取一次该合约参数，复用于最大杠杆、张数、价格处理和报告；`getorder_price_round(contract_name=None, session=None)` 与 `getquanto_multiplier()` 一样支持指定合约及复用会话。上传从报告解析相同的参数字符串并交给 `numeric` 列保存，不再次查询 Gate，也不查询合约参数表。旧报告允许同时省略这两个字段，上传时写入 NULL；仅包含一个参数或参数非正数时，在删除旧订单前拒绝整个报告。Supabase 数据库只需订单表。工具仍不执行真实下单。

### 从 PR #8 的版本升级

PR #8 已合并的版本把 Supabase `contracts` 表设为运行依赖；该表返回 HTTP 404 时，计算流程会提前退出，订单上传不会执行。本次修复删除这张表的读写和建表脚本，合约参数改由 Gate 公开接口提供。

已有部署升级时，先完成上面的 Infisical 配置，再更新代码并确认订单表权限。新部署在 Infisical 准备凭证，在 Supabase 准备订单表。无需创建或同步 `contracts` 表；已执行过旧 SQL 的数据库不会被本次代码更新自动删除表或列。issue #10 增加报告参数入库后，上线新代码前请再次执行 `docs/supabase_sizes.sql`，补齐两个 `numeric` 列；已有这两列时保持原定义。为兼容旧报告和只有时间戳的报告，这两列需允许 NULL。

修复后的远端 Checks 使用模拟接口验证精度、仓位换算及订单上传，不会访问真实账户、数据库或发送通知。真实业务流程仍依赖 Gate 行情接口、账户权限及现有订单表权限。
