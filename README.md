# Rail Globe

中文 | [English](README.en.md)

中国、日本、韩国、英国，欧洲的德国、法国、瑞士、西班牙、荷兰、比利时、意大利、奥地利、匈牙利，东南亚的老挝、泰国、马来西亚、新加坡、印度尼西亚：铁路、地铁和有轨电车画在卫星影像的地球上。

**在线查看：https://rail-globe.github.io/**

![全国铁路网，画在卫星影像的地球上](docs/images/china.jpg)

## 能做什么

- **看线路**：十六个国家的线路同时画在地球上，也可切成平面地图。放大到车站，能看到站台、每一股道和车辆段。线路按当前视野渐进加载。
- **搜索**：车站、线路、城市、国家在一个框里搜，当地名、中文名、英文名都能搜到。
- **看一条线**：点一条线，整条高亮，卡片写它的类别和设计时速。
- **两站怎么走**(中国)：沿真实线路给出走法、里程和估算时间，铁路和地铁一起算，相邻车站可步行换乘。
- **列车**(中国)：按时刻表估算此刻或任一时刻全国列车的位置。选中一趟车，看整条路线、经停站和经由线路。位置不是实时定位。
- **中文 / English**：界面和地名写法一键切换。

## 怎么上色

每个国家用同一套规则，不按公司上色：

1. 动车组和高速线路按**设计时速**分七档：>350、350、300、250、200、160、<160 km/h。
2. 其余铁路有官方线路色的用线路色，没有的用中性浅色。
3. 地铁、轻轨和有轨电车用官方线路色。

![图例：动车组线路按设计时速分七档，普速铁路，未建成线路](docs/images/legend.png)

虚线是在建线路。每条铁路只画一条，欧洲和东南亚的国铁不做横向排座，各画在自己的轨道上；城市轨道共线时并排画，放大后回到各自的轨道。

只有运行限速、没有设计标准的区段，按速度档绘制并标为待核实；卡片写“最高时速”。欧洲新增线路保留 OSM 来源轨道和原始速度标签，不把 ICE、TGV 或 AVE 的列车品牌当作设计标准。

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
| 德国 | 铁路干线、支线与遗产铁路，城市地铁、轻轨和电车；车站、在建线路、站场与车辆基地 |
| 法国 | 法国本土与科西嘉的铁路及城市轨道，含 LGV、地铁、轻轨和电车；车站、在建线路、站场与车辆基地 |
| 瑞士 | 铁路与常规窄轨铁路、遗产铁路，洛桑地铁及各城市电车；车站、在建线路、站场与车辆基地 |
| 西班牙 | 伊比利亚半岛、巴利阿里和加那利群岛，及休达、梅利利亚源范围；铁路、地铁、轻轨和电车，含特内里费电车；车站、在建线路、站场与车辆基地 |
| 荷兰 | 欧洲领土的铁路、地铁、轻轨和电车；车站、在建线路、站场与车辆基地 |
| 比利时 | 铁路、地铁、轻轨和电车，含沿海电车；车站、在建线路、站场与车辆基地 |
| 意大利 | 意大利半岛、西西里和撒丁岛的铁路、地铁、轻轨和电车；车站、在建线路、站场与车辆基地 |
| 奥地利 | 铁路与遗产铁路，Koralmbahn、维也纳至圣珀尔滕、下因河谷三条新建高速线；维也纳地铁，维也纳、格拉茨、林茨、因斯布鲁克的电车；车站、在建线路、站场与车辆基地 |
| 匈牙利 | 铁路与遗产铁路；布达佩斯地铁、HÉV 和电车，塞格德、德布勒森、米什科尔茨的电车；车站、在建线路、站场与车辆基地 |
| 老挝 | 中老铁路(160 档)和从泰国过境到 Khamsavath 的铁路；车站、站场与车辆基地 |
| 泰国 | 全国铁路，曼谷的地铁、轻轨、单轨、红线和机场线；中泰高铁等在建线路；车站、站场与车辆基地 |
| 马来西亚 | 半岛和沙巴的铁路，吉隆坡的地铁、轻轨、单轨、KTM 通勤线和机场快线，槟城的 KTM 通勤线；东海岸铁路等在建线路；车站、站场与车辆基地 |
| 新加坡 | 地铁和轻轨；跨岛线、裕廊区域线、新柔捷运等在建线路；车站、站场与车辆基地 |
| 印度尼西亚 | 爪哇、苏门答腊和苏拉威西的铁路，雅加达至万隆高铁(350 档)；雅加达的 KRL 通勤线、地铁和轻轨，日惹、梭罗、棉兰、巴东的通勤和机场线，巨港轻轨；车站、站场与车辆基地 |

S-Bahn、RER、Cercanías 使用的铁路轨道包含在铁路层。欧洲线路与站名保留当地写法；有来源的中文、英文名字随语言切换并可搜索，缺名轨道保留显示但不编造线路名。铁路范围依 OSM 已绘制对象，法国海外地区不在当前源范围内。泰国、老挝的名字写当地文字，后面括号里是有出处的中文名，没有中文名的写英文名；马来西亚、新加坡、印度尼西亚写当地名，有出处的中文名随语言切换。奥地利、匈牙利只画本国国界以内的部分；地图标注没有 ő、ű 等字形，写成最近的 ö、ü，卡片照原样显示。

## 数据与许可

- 线路、车站、站场：© [OpenStreetMap](https://www.openstreetmap.org/copyright) 贡献者，ODbL。Geofabrik 快照：中国 2026-10-05，日本、韩国 2026-10-06，英国 2026-10-03。
- 欧洲快照：德国使用 [GWDG 的 Geofabrik 镜像](https://ftp5.gwdg.de/pub/misc/openstreetmap/download.geofabrik.de/)，法国、瑞士、西班牙、荷兰、比利时、意大利使用 [OSM France](https://download.openstreetmap.fr/extracts/)；西班牙另合并 `africa/spain` 的加那利、休达、梅利利亚；奥地利、匈牙利使用 Geofabrik 的 `austria`、`hungary`，2026-10-20。逐源时间、校验值及范围见 `data/europe_sources.json`。
- 东南亚快照：Geofabrik 的 `laos`、`thailand`、`malaysia-singapore-brunei`、`indonesia`，2026-10-18。中文名逐条记出处，见 `data/<国家>_names.tsv`(中文维基条目名、新华社等)。
- 新加坡车站中文名：Contains information from Train Station Chinese Names accessed on 19 October 2026 from [data.gov.sg](https://data.gov.sg/datasets/d_d312a5b127e1ae74299b8ae664cedd4e/view) which is made available under the terms of the [Singapore Open Data Licence version 1.0](https://data.gov.sg/open-data-licence).
- 城市的中英文别名：[Wikidata](https://www.wikidata.org/)，CC0，逐条出处见 `data/europe_city_names.json`。车辆基地的补充名称在 `data/depot_names.json` 中逐条记出处，OSM 已有名字优先。
- 设计时速：[中国动车组线路资料](https://www.china-emu.cn/RailRoads/)及各线的公开来源，逐段记出处；只查到运行速度的标为待核实。
- 列车时刻表：[Chinese Railway GTFS](https://github.com/wensimehrp/chinese-railway-gtfs)(wensimehrp)，[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，上游由 RailGo-Parser 采集。本站做了筛选、简化和格式转换，并把偏离本图线路的区段改为沿本图线路，见 `data/trains/README.md`。不是 12306 的官方数据。逐站正晚点在读者点“查询”时向 [RailGo](https://railgo.dev/) 查询。
- 卫星影像：Esri World Imagery(Esri, Maxar, Earthstar Geographics)，在线加载，不在本仓库中。
- 中国的营业里程数字来自交通运输部《2025年交通运输行业发展统计公报》。
- 软件：[MapLibre GL JS](https://maplibre.org/)，[PMTiles](https://github.com/protomaps/PMTiles) 读取库(BSD-3-Clause)，Open Sans、Noto Sans Thai、Noto Sans Lao 字体(SIL Open Font License)。

## 本地运行

```bash
python3 scripts/serve.py
```

打开 http://localhost:8765 。页面源码在 `src/app.html`，改完运行 `python3 scripts/build.py`。

重新生成数据需要 Python 3(`osmium`、`shapely`、`numpy`)、[tippecanoe](https://github.com/felt/tippecanoe)，以及 Geofabrik 的 `china`、`taiwan`、`japan-latest`、`south-korea-latest`、`united-kingdom` 五份 `.osm.pbf`(东南亚另需 `laos`、`thailand`、`malaysia-singapore-brunei`、`indonesia` 四份)，放在 `data/raw/`：

```bash
python3 scripts/build_border.py              # 国界
python3 scripts/extract_osm.py               # 提取中国；加 jp、kr、uk 提取其他国家
python3 scripts/process_jp.py                # 日本的图层；韩国、英国是 process_kr.py、process_uk.py
python3 scripts/fetch_europe.py de fr ch es nl be it # 欧洲源文件，包含西班牙的非欧洲部分
python3 scripts/extract_osm.py it            # 欧洲逐国提取：de、fr、ch、es、nl、be、it
python3 scripts/process_europe.py de fr ch es nl be it # 欧洲图层；可只指定一个国家
python3 scripts/build_cities.py es           # 同一组原始文件中的城市名与位置
python3 scripts/extract_osm.py th            # 东南亚逐国提取：la、th、my、sg、id
python3 scripts/process_sea.py la th my sg id # 东南亚图层
python3 scripts/sea_glyphs.py                # 泰文、老挝文的地图字形
python3 scripts/extract_design_points.py     # 设计时速区段的分界点
python3 scripts/process_osm.py               # 中国的图层，按设计时速分段着色
python3 scripts/build_graph.py               # 两站寻路的线路网络
python3 scripts/clip_neighbours.py cn        # 中国的线路只画到国境，不画进已画的邻国
python3 scripts/build_trains.py --download   # 列车时刻表
python3 scripts/build_tiles.py               # 切成矢量瓦片 data/tiles/<国家>.pmtiles
python3 scripts/build.py                     # 生成页面
python3 scripts/check_layers.py              # 核查断线、重复和偏离轨道
python3 -m unittest discover -s tests
```

同样的数据和代码，每次生成的结果相同。

## 许可

代码、页面和文档使用 [PolyForm Noncommercial 1.0.0](LICENSE)：可以学习、研究、个人和教学使用，也可以修改和分享；**商用需要作者书面授权**，请在本仓库开 Issue 联系。数据按上面各自的许可。
