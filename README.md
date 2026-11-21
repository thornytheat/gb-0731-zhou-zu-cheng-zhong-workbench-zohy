# 轴组称重工作台

园区地磅稽核员可复核两轮道触发、轴组和静态磅单。样例包含冲突标定、去抖回弹、多轮争配和最新磅单冲突。

## 启动

```sh
docker compose up --build
```

打开 `http://localhost:18420/`。接口文档在 `/docs`，健康检查在 `/api/health`。容器用命名卷保存历史。需要隔离新数据库时，可用其他 Compose 项目名启动，端口仍为 18420。

本地 Python 3.11 或 3.12 可执行下列命令。

```sh
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 18420
```

环境变量 `WEIGH_DB` 和 `WEIGH_SAMPLE_DIR` 可覆盖本地数据库和受信输入目录，默认使用 `var/weigh.sqlite3` 和 `sample_data/`。

## 演示

1. 首页默认读取晚班脏样例预览，点击「运行样例」归档。核对 50 原始、22 有效、3 重复、25 隔离。
2. 暂停触发日志滚动。点击「重跑」，批次号和计数保持一致。点击「继续滚动」，可见「重算核验一致」事件。
3. 左右轮载选择 `0007`，检查轴组及 10% 和 20% 的偏载。切到「整车磅单勾稽」，检查实际差额和复秤原因。`0023` 的差额为 0 kg，但仍需复秤。
4. 「导出复核包」下载归档 ZIP。切换「南门校验 · 对照采样」可查看 28 条全有效、7 车次全核平的对照结果。

## 模块入口

`GET /api/intake`、`/api/calibration`、`/api/debounce`、`/api/axles`、`/api/balance`、`/api/reconcile` 均支持 `sample=dirty` 或 `sample=clean`，也可传 `run_id` 读取归档。`POST /api/batches` 接收 `{"sample":"dirty"}`，`GET /api/batches` 列出归档。批次号下的 `/rerun` 和 `/export` 分别用于重算与下载。

定义在 [数据字典](docs/DATA-DICTIONARY.md)，模块与样例断言在 [深度登记](docs/DEPTH.md)。样例按文件做有界分析，轴距按车次档案恒速估计。

```sh
docker compose exec -T app pytest -q
```

## 冷存归档工作台（M8）

审计季容量不足时按完整批次转冷，抽查车次随时从验封冷包回读原轴组证据。页面在 `/archive`，
规则与接口见 [归档说明](docs/ARCHIVE.md)，端到端演练：

```sh
scripts/archive_demo.sh
```

边界与凭据要点：

- 保留单生效、含待复秤车次或流水未核平的批次禁止转冷；`plan` 只推荐整批，不拆车次。
- 冷包带逐文件 SHA-256 与 Merkle 根封条（可选 HMAC）；清理在线库前强制重新验封，失败则一行不删。
- 恢复按原 `run_id` 回灌并逐车次核对结论指纹；重复恢复只追加事件，绝不生成第二个批次。

CLI 入口：`python -m app.modules.m8_archive.cli --help`。环境变量 `WEIGH_ARCHIVE_DB`、
`WEIGH_COLD_ROOT`、`WEIGH_COLD_HMAC` 控制台账、冷包根目录与封条密钥。
