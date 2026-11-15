# 巡检定位转路段序列服务

市政道路巡检车在路口记录的定位点 → 最优吸附路口序列 → 依次经过的单向路段 ID 序列，
用于路段通行量统计。Python + FastAPI 实现，Docker Compose 一键启动网页。

## 1. 业务规则

1. 上传三份 **UTF-8** CSV：
   - 路口文件（1～20 个）：`intersection_id,x,y`，平面米坐标；
   - 路段文件（0～40 条）：`edge_id,from_intersection_id,to_intersection_id,length_m`，
     单向路段，长度为正整数米；
   - 定位文件（2～8 个点）：`timestamp_utc,x,y`，UTC 秒时间戳严格递增。
2. 两个参数：
   - 吸附半径：**非负整数**米；每个定位点只能匹配半径内的路口（平方距离 ≤ 半径²，精确比较）；
   - 最高速度：**正整数**米/秒。
3. 相邻两个匹配路口之间必须存在**有向最短路**，且最短路长度不得超过
   `时间差（秒） × 最高速度（米/秒）`。
   - 相邻定位点匹配到同一路口时，经过 0 条路段、里程 0，天然满足速度约束。
4. 在所有可行方案中，取「各定位点到所选路口的平方距离总和」最小者。
5. **唯一性判定（决定是否导出）**：
   - 最优路口序列不唯一 → 标记 **待核**，页面展示并列序列，不产生结果文件；
   - 路口序列唯一，但任意相邻路口间的最短路段序列不唯一
     （含等长平行路段、等长多路径）→ 标记 **待核**，不产生结果文件；
   - 两者均唯一 → 展示并允许下载依次经过的路段 ID CSV。
6. 输入无效或问题不可行时，页面说明具体原因，**不产生结果文件**。

## 2. 目录结构

```
.
├── app/
│   ├── main.py          # FastAPI 入口（网页、/api/solve、结果下载）
│   ├── service.py       # 编排解析/求解/导出，短期结果存储
│   ├── solver.py        # Floyd 全源最短路 + 路径计数 + 动态规划
│   ├── parsing.py       # UTF-8 CSV 解析与全部输入校验
│   ├── models.py        # 领域模型（Fraction 精确坐标）
│   └── web/             # 原生 HTML/CSS/JS 页面与示例 CSV
├── tests/               # pytest：解析、求解器、HTTP 接口共 44 个用例
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 3. Docker Compose 启动（交付方式）

```bash
docker compose up --build
```

浏览器访问 <http://localhost:8000> ：

1. 选择三份 CSV（或点击「填充示例数据」）；
2. 填写吸附半径与最高速度，点击「求解」；
3. 唯一确定时出现「下载路段 ID CSV」按钮；待核/不可行时只给原因，无下载入口。

健康检查：`GET /healthz`。容器以非 root 用户运行，内置 HEALTHCHECK。

停止服务：`docker compose down`。

## 4. 本地开发运行（无需 Docker）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

运行测试（含 httpx 测试依赖）：

```bash
.venv/bin/pip install pytest httpx
.venv/bin/python -m pytest tests/ -q
```

## 5. 导出文件格式

仅唯一解产生，UTF-8 编码、带表头，按经过顺序排列：

```csv
sequence_no,edge_id,from_intersection_id,to_intersection_id,length_m
1,E1,A,B,100
2,E2,B,C,100
```

结果在服务端内存中保留 1 小时（最多 200 份），过期需重新求解；服务重启即清空。

## 6. 算法与精确性说明

- 坐标、平方距离、半径比较全部使用 `fractions.Fraction` 有理数精确运算，
  边界距离（如点 (3,4)、半径 5）不会因浮点误差产生歧义。
- Floyd-Warshall 同时计算全源最短距离矩阵与最短**有向边序列条数**矩阵，
  等长平行边各自计数；动态规划按点序维护最小累计平方距离与达到该代价的序列条数。
- 数据规模上限为 20 路口 / 40 路段 / 8 定位点，计算量有界；
  并列序列最多枚举展示 50 条，条数封顶 100 万用于展示，不影响唯一性判定。
