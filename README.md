# Rail Globe

中国与英国的铁路网，以及粤港澳大湾区、北京、西安的地铁，叠加在卫星影像的地球上。

在线查看：https://rail-globe.github.io/

## 图上有什么

- 中国：高速铁路（按时速分 350、250 两档）、城际与快速铁路、普速干线和支线、在建线路
- 英国：全国铁路，按主要客运运营公司上色，也可以切换为按线路等级
- 地铁：京津、江浙沪、成都、重庆、大湾区（含港铁、澳门轻轨）、西安，按线路官方色
- 市郊铁路：北京市郊铁路、上海金山铁路等跑在国铁线路上的服务，作为一条细线叠加在国铁线路旁，国铁线路本身的归属不变
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

需要 Python 3、`osmium` 和 `shapely`，以及 Geofabrik 的 `china`、`taiwan`、`united-kingdom` 三份 `.osm.pbf` 文件，放在 `data/raw/` 下。

```bash
python3 scripts/extract_osm.py        # 中国、港澳台
python3 scripts/extract_osm.py uk     # 英国
python3 scripts/process_osm.py        # 分类并写出 data/ 下的图层
python3 scripts/build_graph.py        # 两站寻路用的线路网络
python3 scripts/build_border.py       # 国界
python3 scripts/build.py              # 生成页面
```
