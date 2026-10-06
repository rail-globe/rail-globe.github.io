# Rail Globe

中国的铁路网，以及京津、江浙沪、成渝、大湾区、西安的地铁，叠加在卫星影像的地球上。

`main` 分支是线上版本，只含中国。含英国铁路（按运营公司上色）的版本在 `with-uk` 分支，没有发布成网页。两者的差别只有 `site.json` 里的开关和据此生成的数据。

在线查看：https://rail-globe.github.io/

## 图上有什么

- 中国：高速铁路（按时速分 350、250 两档）、城际与快速铁路、普速干线和支线、在建线路
- 英国（仅 `with-uk` 分支）：全国铁路，按主要客运运营公司上色，也可以切换为按线路等级
- 地铁：京津、江浙沪、成都、重庆、大湾区（含港铁、澳门轻轨）、西安，按线路官方色
- 城际和市郊按运营方归类：地铁公司运营的城际、市域线归入“地铁 / 市郊”；铁路局运营、借国铁线路跑的市郊列车单列一行，作为细线叠在国铁线路旁，国铁线路本身的归属不变
- 站场与车辆基地、车站、国界
- 地球和平面两种视图，线路搜索，快速定位
- 两站之间怎么走（仅中国）：点两个车站或输入站名，给出沿真实线路的走法、里程和估算运行时间。不是车次和时刻表

每条线路只有一个等级和一种颜色，按其多数轨道的等级整条归类。虚线只表示在建线路。

## 数据与许可

- 线路、车站、站场：© [OpenStreetMap](https://www.openstreetmap.org/copyright) 贡献者，ODbL。Geofabrik 2026-10-03 提取。
- 卫星影像：Esri World Imagery（Esri, Maxar, Earthstar Geographics），在线加载，不包含在本仓库中。
- 标注字形：Open Sans，SIL Open Font License。
- 地图引擎：[MapLibre GL JS](https://maplibre.org/)。

顶部的营业里程数字来自交通运输部《2025年交通运输行业发展统计公报》，不是从地图数据计算的。

## 本地运行

```bash
python3 scripts/serve.py
```

然后打开 http://localhost:8765 。页面源码在 `src/app.html`，修改后运行 `python3 scripts/build.py` 重新生成 `index.html`。

## 重新生成数据

需要 Python 3、`osmium` 和 `shapely`，以及 Geofabrik 的 `china`、`taiwan` 两份 `.osm.pbf` 文件（含英国的版本还需要 `united-kingdom`），放在 `data/raw/` 下。`site.json` 里的 `uk` 决定是否包含英国。

```bash
python3 scripts/build_border.py       # 国界，同时缓存省界（process_osm.py 用它划分地铁所属地区）
python3 scripts/extract_osm.py        # 中国、港澳台
python3 scripts/extract_osm.py uk     # 英国（仅 with-uk 分支需要）
python3 scripts/process_osm.py        # 分类并写出 data/ 下的图层
python3 scripts/build_graph.py        # 两站寻路用的线路网络
python3 scripts/build.py              # 生成页面
```
