# Rail Globe

中文 | [English](README.en.md)

中国、日本、韩国和英国的铁路、地铁和有轨电车，画在卫星影像的地球上。

**在线查看：https://rail-globe.github.io/**

![全国铁路网，画在卫星影像的地球上](docs/images/china.jpg)

## 能做什么

- **看线路**：四个国家的线路同时画在地球上，也可切成平面地图。放大到车站，能看到站台、每一股道和车辆段。
- **搜索**：车站、线路、城市、国家在一个框里搜，当地名、中文名、英文名都能搜到。
- **看一条线**：点一条线，整条高亮，卡片写它的类别和设计时速。
- **两站怎么走**(中国)：沿真实线路给出走法、里程和估算时间，铁路和地铁一起算，相邻车站可步行换乘。
- **列车**(中国)：按时刻表估算此刻或任一时刻全国列车的位置。选中一趟车，看整条路线、经停站和经由线路。位置不是实时定位。
- **中文 / English**：界面和地名写法一键切换。

## 怎么上色

四个国家用同一套规则，不按公司上色：

1. 动车组和高速线路按**设计时速**分七档：>350、350、300、250、200、160、<160 km/h。
2. 其余铁路有官方线路色的用线路色，没有的用中性浅色。
3. 地铁、轻轨和有轨电车用官方线路色。

![图例：动车组线路按设计时速分七档，普速铁路，未建成线路](docs/images/legend.png)

虚线是在建线路。每条线只画一条；几条线共用或紧贴同一段轨道时并排画，放大后回到各自的轨道。

## 截图

| ![华东的高铁网](docs/images/speed.jpg) | ![上海的地铁](docs/images/shanghai.jpg) | ![上海虹桥站](docs/images/hongqiao.jpg) |
|:-:|:-:|:-:|
| 华东的高铁，按设计时速上色 | 上海的地铁 | 上海虹桥站的股道 |
| ![长三角此刻在路上的列车](docs/images/trains.jpg) | ![选中一趟车，整条路线亮起来](docs/images/train-route.jpg) | ![香港和深圳](docs/images/hongkong.jpg) |
| 列车，按时刻表估算的位置 | 选中 Z328 长春→昆明 | 香港和深圳 |
| ![日本的铁路网](docs/images/japan.jpg) | ![东京的铁路和地铁](docs/images/tokyo.jpg) | ![首尔的地铁和铁路](docs/images/seoul.jpg) |
| 日本 | 东京 | 首尔 |
| ![韩国的铁路网](docs/images/korea.jpg) | ![英国的铁路网](docs/images/uk.jpg) | ![伦敦的地铁和铁路](docs/images/london.jpg) |
| 韩国 | 英国 | 伦敦 |

## 覆盖范围

| 国家 | 内容 |
|---|---|
| 中国 | 含港澳台。国铁按区段设计时速着色；各城市的地铁、轻轨·电车、市郊·城际；站场与车辆段；列车；两站寻路 |
| 日本 | 全国铁路，各城市的地铁、单轨和路面电车；新干线按已建成的设计标准分段着色 |
| 韩国 | 全国铁路，首尔、釜山、大邱、仁川、大田、光州的地铁与轻轨；高速线和准高速线按时速档，部分时速待核实 |
| 英国 | 全国铁路(含北爱尔兰)、遗产铁路、伦敦地铁、DLR 和各城市的有轨电车；High Speed 1 按 300 档 |

## 数据与许可

- 线路、车站、站场：© [OpenStreetMap](https://www.openstreetmap.org/copyright) 贡献者，ODbL。Geofabrik 快照：中国 2026-10-05，日本、韩国 2026-10-06，英国 2026-10-03。
- 设计时速：[中国动车组线路资料](https://www.china-emu.cn/RailRoads/)及各线的公开来源，逐段记出处；只查到运行速度的标为待核实。
- 列车时刻表：[Chinese Railway GTFS](https://github.com/wensimehrp/chinese-railway-gtfs)(wensimehrp)，[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，上游由 RailGo-Parser 采集。本站做了筛选、简化和格式转换，并把偏离本图线路的区段改为沿本图线路，见 `data/trains/README.md`。不是 12306 的官方数据。逐站正晚点在读者点“查询”时向 [RailGo](https://railgo.dev/) 查询。
- 卫星影像：Esri World Imagery(Esri, Maxar, Earthstar Geographics)，在线加载，不在本仓库中。
- 中国的营业里程数字来自交通运输部《2025年交通运输行业发展统计公报》。
- 软件：[MapLibre GL JS](https://maplibre.org/)，[PMTiles](https://github.com/protomaps/PMTiles) 读取库(BSD-3-Clause)，Open Sans 字体(SIL Open Font License)。

## 本地运行

```bash
python3 scripts/serve.py
```

打开 http://localhost:8765 。页面源码在 `src/app.html`，改完运行 `python3 scripts/build.py`。

重新生成数据需要 Python 3(`osmium`、`shapely`、`numpy`)、[tippecanoe](https://github.com/felt/tippecanoe)，以及 Geofabrik 的 `china`、`taiwan`、`japan-latest`、`south-korea-latest`、`united-kingdom` 五份 `.osm.pbf`，放在 `data/raw/`：

```bash
python3 scripts/build_border.py              # 国界
python3 scripts/extract_osm.py               # 提取中国；加 jp、kr、uk 提取其他国家
python3 scripts/process_jp.py                # 日本的图层；韩国、英国是 process_kr.py、process_uk.py
python3 scripts/extract_design_points.py     # 设计时速区段的分界点
python3 scripts/process_osm.py               # 中国的图层，按设计时速分段着色
python3 scripts/build_graph.py               # 两站寻路的线路网络
python3 scripts/build_trains.py --download   # 列车时刻表
python3 scripts/build_tiles.py               # 切成矢量瓦片 data/tiles/<国家>.pmtiles
python3 scripts/build.py                     # 生成页面
python3 scripts/check_layers.py              # 核查断线、重复和偏离轨道
python3 -m unittest discover -s tests
```

同样的数据和代码，每次生成的结果相同。

## 许可

代码、页面和文档使用 [PolyForm Noncommercial 1.0.0](LICENSE)：可以学习、研究、个人和教学使用，也可以修改和分享；**商用需要作者书面授权**，请在本仓库开 Issue 联系。数据按上面各自的许可。
