# 中国列车时刻表与线路数据

此目录是中国铁路社区 GTFS 快照的静态编译结果，用于根据北京时间、明确的运行日期、停站时刻及路线形状估算列车位置。**它不包含车载 GPS 定位，也不包含实际晚点、实际停运或临时径路变化。** 页面上随时间移动的标记属于时刻表估算。

## 来源、许可与修改

- 发布者：`wensimehrp/chinese-railway-gtfs` 社区项目；[源仓库](https://github.com/wensimehrp/chinese-railway-gtfs)、[数据发布](https://github.com/wensimehrp/chinese-railway-gtfs/releases)。本次编译的精确发布标签、下载 URL 和 ZIP SHA-256 见 `index.json` 的 `meta`。
- GTFS 数据许可：[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。[源许可文件](https://github.com/wensimehrp/chinese-railway-gtfs/blob/main/LICENSE)的副本保存在 `SOURCE_LICENSE_CC_BY_4.0.txt`。
- 车站坐标来源：[OpenStreetMap 贡献者](https://www.openstreetmap.org/copyright)。线路与列车数据上游采集项目：[RailGo-Parser](https://github.com/RailGoApps/RailGo-Parser)。此处使用的是已发布的 GTFS，未调用 RailGo 实时 API，未爬取 12306。
- 本构建所做修改：中国范围筛选、时序校验、线路质量筛选、100 米容差的几何简化、polyline5 压缩、停站位置投影和静态索引格式转换。
- 推荐署名：“列车时刻表与线路数据：wensimehrp/chinese-railway-gtfs，CC BY 4.0；已作筛选、简化、压缩及格式转换。车站坐标来源 OpenStreetMap；上游列车数据由 RailGo-Parser 采集。”

GTFS 中的 `feed_info.txt` 与 `agency.txt` 使用了国铁名称、12306 网址。这不表示本数据是国铁发布的官方开放数据，也不表示存在官方实时列车位置接口。

## 更新

项目根目录执行，Python 3.10 或更高版本，无第三方依赖：

```bash
python scripts/build_trains.py --gtfs /path/to/output_gtfs.zip --release gtfs-20261012-065400
python scripts/build.py
```

也可以查询 GitHub 最新发布并仅下载一次 ZIP：

```bash
python scripts/build_trains.py --download
python scripts/build.py
```

`--download` 使用 GitHub Releases API，不请求任何售票账号，不爬取车票查询网页。脚本按下载资产的声明大小核验 ZIP，并记录 SHA-256。网络访问失败时可自行下载 ZIP，改用 `--gtfs`。

编译算法的关键风险回归测试：

```bash
python -m unittest discover -s tests -p test_build_trains.py -v
```

## 文件和接口

| 文件 | 用途 |
| --- | --- |
| `index.json` | 数据来源、质量统计、车站、明确的运行日期、全部中国范围旅程和路线文件映射 |
| `shapes/NN.json` | 去重后路线几何；每个 JSON 不超过 2,800,000 字节 |
| `quality.json` | 可阅读的质量报告、拒绝原因、各类异常的示例车次 |
| `SOURCE_LICENSE_CC_BY_4.0.txt` | GTFS 发布者的数据许可证副本 |

索引格式（示意，停站数字是索引与秒数，不是站台号）：

```json
{
  "schemaVersion": 1,
  "meta": {
    "feedStartDate": "20260927",
    "feedEndDate": "20261231",
    "timezone": "Asia/Shanghai",
    "mode": "timetable-estimate",
    "isLiveVehiclePositionFeed": false
  },
  "stops": [
    {"id": "STA", "name": "示例起点", "lon": 116.0, "lat": 39.0},
    {"id": "STB", "name": "示例终点", "lon": 116.1, "lat": 39.1}
  ],
  "services": {"S1": ["20261012", "20261013"]},
  "trips": [{
    "id": "example-trip",
    "number": "G示例",
    "serviceId": "S1",
    "shapeId": "s0123456789abcdef",
    "type": "G",
    "stops": [[0, 82800, 82800, 0.0], [1, 90000, 90000, 14000.0]],
    "renderable": true,
    "maxStopOffsetM": 20
  }],
  "shapeFiles": {"s0123456789abcdef": "shapes/00.json"}
}
```

每个 `trip.stops` 项为：

```text
[stopIndex, arrivalSeconds, departureSeconds, shapeDistanceMetres]
```

- `stopIndex` 引用顶层 `stops` 数组。
- 到发秒数从本旅程运行日的北京时间午夜起算，允许大于等于 86400。`25:00:00` 必须保留为 90000，不能变成当天 01:00。
- `services` 是明确列出的 `YYYYMMDD` 数组。旅程必须使用所属服务的日期，不能把过期班次重置为每天运行。计算当前运行列车也应检查前几日出发的跨夜旅程。
- 首站有效出发时刻作为起点；末站有效到达时刻作为终点。端点占位或矛盾的另一项归一为该有效时刻。
- `shapeDistanceMetres` 沿该旅程指定的**最终 polyline5 路线**累计，以地球半径 6,371,000 米的 Haversine 距离计算。精度为 0.1 米。浏览器必须使用相同半径，不能换用地图上的其他线网来计算插值。
- `renderable: false` 表示不能绘制运行位置；仍可展示有效的时刻表。其 `shapeId` 和距离为 `null`，`geometryNote` 给出原因。
- `timetableValid: false` 表示源时刻本身存在矛盾，保留源秒数供检查。核心必须跳过该旅程的运行估算，界面不得把原始错误到发时刻当成已验证数据。

几何分片为对象：

```json
{
  "s0123456789abcdef": {
    "p": "Google polyline5 encoded text",
    "bbox": [115.0, 38.0, 117.0, 40.0]
  }
}
```

`p` 使用 Google polyline 编码，编码顺序为纬度、经度；解码提供给地图时必须转成 `[longitude, latitude]`。`bbox` 顺序为西、南、东、北。路线 ID 为压缩几何的 SHA-256 前缀，因此多个源 shape 或多个车次使用相同路线时仅保存一次。

## 质量筛选与边界

默认阈值由编译器命令行控制，并记录在 `meta.qualityThresholds`：

| 检查 | 默认行为 |
| --- | --- |
| 上游没有路线 | 保留旅程，拒绝绘制位置；不补站间直线 |
| 源路线相邻坐标点间距超过 20 千米 | 保守排除该稀疏路线；这不证明真实铁路或隧道有错误 |
| 停站到路线最短投影超过 1,500 米 | 拒绝绘制位置 |
| 停站顺序与路线累计距离冲突 | 同时考虑回环中的多个投影候选和反向路线；无法得到单调顺序时拒绝 |
| 相邻站在时刻表内需要超过 450 千米/小时的路线速度 | 拒绝绘制位置 |
| 中间站出发早于到达、区间旅行时长非正、格式错误 | 保留源记录并标记时刻表无效；不推断“合理修正” |
| 运行日期在声明日历之外 | 忽略范围外日期；缺少明确有效日期的班次不可估算 |
| 已识别的境外停站 | 当前快照中的琅勃拉邦、万荣、万象排除；包含这些停站的整趟跨境旅程排除，不重造截短班次 |

中国范围包含香港西九龙。本快照的境外排除名单在编译器中明确列出；若未来源数据扩展到其他国家，应更新范围审核与境外站名单。

源线路可能包含上游插值或简化，本构建进一步采用 100 米容差简化。通过上述检查只意味着足以用于该尺度的路线估算，不证明路线逐段精确，也不说明列车实际正在该点。

`feedEndDate` 是源声明的整个数据集结束日期，各车次实际有效日期仍以 `services` 为准。某日没有可绘制班次时必须显示无数据，不得重复前一日或默认继续运行。

覆盖率、拒绝数量、下载快照标识与生成时间均以同目录最新 `quality.json` 为准。
