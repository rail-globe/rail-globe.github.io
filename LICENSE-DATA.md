# 数据的许可 / Licence of the map data

`data/` 目录下的地图数据（线路、车站、站场、城市、寻路网络和瓦片）是从 OpenStreetMap 的数据提取、加工得到的衍生数据库，
按 **Open Database License (ODbL) 1.0** 提供：<https://opendatacommons.org/licenses/odbl/1-0/>。

- 使用这些数据要署名：`© OpenStreetMap contributors`（<https://www.openstreetmap.org/copyright>）。
- 你再做出来的衍生数据库要同样以 ODbL 开放（相同方式共享）。
- ODbL 允许商业使用，所以数据部分不受根目录 `LICENSE`（非商用）的限制；非商用的限制只适用于代码、页面和文档。
- 我们自己加进数据里的内容（设计时速的归档、名称表、各项覆盖规则）随同一个衍生数据库一起按 ODbL 提供。

The files under `data/` are a derived database built from OpenStreetMap and are provided under the ODbL 1.0.
Attribution: © OpenStreetMap contributors. The non-commercial terms of the code licence in `LICENSE` do not apply to them.

## 不属于本项目授权的内容

- 卫星影像（Esri World Imagery）不在仓库里，页面在浏览时在线取用，按 Esri 的条款使用。
- `vendor/` 下的第三方文件（`pmtiles.js`、`maplibre-gl.css`、字体等）各按它们自己的许可（BSD-3-Clause 等）。
- 设计时速的参考资料（`data/` 下由公开网页整理的目录）来自公开出处，用于核对，不因本项目的许可而改变它们原来的权利。
- README 里的截图含 Esri 影像，仅作说明用途。
