"""The city labels of the map and of the search: data/cities.json, from the Geofabrik extracts.

    python3 scripts/build_cities.py          every country
    python3 scripts/build_cities.py jp       one country; the entries of the others stay as they are

An entry is one line: {"n": the place's own name, "at": [lon, lat], "r": rank}, and where known
"nz", its name in simplified Chinese, and "ne", in English (the page puts the names together by
the reader's language: 서울 (首尔), 서울 (Seoul)). Outside China it also has "g", the country, and
"m", the name the country's metro list has for the city; and "side" ("left", "above", "below" or
"above-left") where its name is to stand on that side of its dot, not on the right or wherever
there is room (see the table of Japan). The page shows rank 1 at every zoom and
ranks 2 and 3 from further in; where labels would sit on each other the higher rank is drawn,
and within a rank the one that comes first in the file.

China. The entries of rank 1 and 2 were made by hand (the 70 the map began with): their names,
places and ranks are kept as they are, at the head of the file; only their English names are
looked up. Rank 3 is the seat of every other prefecture-level unit.
The units are the level-5 administrative relations that a province or an autonomous region lists
as its parts: 293 cities, 30 autonomous prefectures, 7 prefectures and 3 leagues, 333 in all, and
the script stops if that is not what it finds. The label is the name a traveller knows the place
by: a city's own name without 市, and for a prefecture or a league the name of its seat (恩施,
锡林浩特, not 恩施土家族苗族自治州), which is the relation's admin_centre. Where the extract has
no seat for a unit, or an old one, SEATS says which it is. The place is the seat's place node:
the admin_centre, else the unit's label node if that is the town itself, else the city or town
of that name nearest to the unit's label point.

Abroad the cities are few, and COUNTRIES names every one of them (owner, 2026-10-09): rank 1 is
the capital and the cities the world knows, rank 2 the other seats of the first-level regions
(Japan's prefectures, Korea's provinces and its special and metropolitan cities, the nations of
the United Kingdom), and there is no rank 3. The extract gives only where each place is. The
Chinese names are in the table, each with where it is from; the English ones are the extract's
name:en. A country added later is a table like these.
"""
import json
import math
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "cities.json"
TAGS = ("name", "name:zh", "name:zh-Hans", "name:en", "place", "population", "admin_level", "boundary")
SETTLED = ("city", "town", "suburb", "quarter", "borough", "municipality")     # a node that is a place people live in
KEPT = SETTLED + ("region", "county", "district", "state", "province")       # what an admin_centre or a label may point at

# file: the extract in data/raw. metro: the country's metro list, whose cities the labels are
# matched with by their Chinese names. Abroad also:
# first: the places of rank 1, the capital and the cities the world knows (the owner's list of
#   2026-10-09); every other place of the table is of rank 2.
# places: every labelled place, by the name of its place node in the extract: its own name as
#   it is to be written, and its Chinese name.
# count: how many places the country has, so that a slip in the table stops the run.
COUNTRIES = {
    "cn": {"file": "china.osm.pbf", "metro": "metro_cities.json"},
    # Japan: the seats of the 47 prefectures. The list is https://ja.wikipedia.org/wiki/都道府県庁所在地
    # and the Chinese names are those of https://zh.wikipedia.org/zh-cn/都道府縣廳所在地 (both read
    # 2026-10-09). Tokyo's seat (東京都区部, 新宿区) is the place 東京都, 东京.
    "jp": {"file": "japan-latest.osm.pbf", "metro": "jp_metro_cities.json", "count": 47,
           "first": ["東京都", "大阪市", "京都市", "名古屋市", "札幌市", "福岡市"],
           # 京都 lies just above and to the right of 大阪, with 名古屋 to its right: with every name
           # on the right of its dot, as each tries first, 京都's ring has no room beside 大阪's
           # name, or 京都's name runs into 名古屋's ring, and a city of rank 1 is lost at the
           # country's view, in English (京都(Kyoto)) even more. 大阪's name goes to the left of its
           # dot and 京都's above it and to the left, clear of 名古屋.
           "side": {"大阪市": "left", "京都市": "above-left"},
           "places": {name: (name[:-1], zh) for name, zh in (pair.split("=") for pair in (
               "札幌市=札幌 青森市=青森 盛岡市=盛冈 仙台市=仙台 秋田市=秋田 山形市=山形 福島市=福岛 水戸市=水户 宇都宮市=宇都宫 前橋市=前桥 "
               "さいたま市=埼玉 千葉市=千叶 東京都=东京 横浜市=横滨 新潟市=新潟 富山市=富山 金沢市=金泽 福井市=福井 甲府市=甲府 長野市=长野 "
               "岐阜市=岐阜 静岡市=静冈 名古屋市=名古屋 津市=津市 大津市=大津 京都市=京都 大阪市=大阪 神戸市=神户 奈良市=奈良 和歌山市=和歌山 "
               "鳥取市=鸟取 松江市=松江 岡山市=冈山 広島市=广岛 山口市=山口 徳島市=德岛 高松市=高松 松山市=松山 高知市=高知 福岡市=福冈 "
               "佐賀市=佐贺 長崎市=长崎 熊本市=熊本 大分市=大分 宮崎市=宫崎 鹿児島市=鹿儿岛 那覇市=那霸").split())}},
    # Korea: the seats of the 16 first-level divisions, https://zh.wikipedia.org/zh-cn/韩国行政区划
    # (read 2026-10-09): the special city, the five metropolitan cities, 光州 for 全南光州统合特别市
    # (one division since 2026-07-01), 世宗, and the eight provinces' 水原, 春川, 清州, 洪城郡 (内浦
    # 新都市), 全州, 安东, 昌原 and 济州. The Chinese names are that page's and those of
    # https://zh.wikipedia.org/zh-cn/韩国城市列表. South Chungcheong's offices stand in 홍북읍 (洪北
    # 邑), a town of 홍성군: the place is the town, the name the county's.
    "kr": {"file": "south-korea-latest.osm.pbf", "metro": "kr_metro_cities.json", "count": 16,
           "first": ["서울특별시", "부산광역시"],
           "places": {"서울특별시": ("서울", "首尔"), "부산광역시": ("부산", "釜山"), "대구광역시": ("대구", "大邱"), "인천광역시": ("인천", "仁川"),
                      "광주": ("광주", "光州"), "대전광역시": ("대전", "大田"), "울산광역시": ("울산", "蔚山"), "세종특별자치시": ("세종", "世宗"),
                      "수원시": ("수원", "水原"), "춘천시": ("춘천", "春川"), "청주시": ("청주", "清州"), "홍북읍": ("홍성", "洪城", "Hongseong"),
                      "전주시": ("전주", "全州"), "안동시": ("안동", "安东"), "창원시": ("창원", "昌原"), "제주시": ("제주", "济州")}},
    # The United Kingdom: the capitals of the four nations (London, Edinburgh, Cardiff, Belfast,
    # https://en.wikipedia.org/wiki/Countries_of_the_United_Kingdom) and the three other cities of
    # rank 1. The Chinese names are the titles of the cities' pages on zh.wikipedia in mainland
    # usage (zh-cn, read 2026-10-09); the extract's name:zh says the same but for Cardiff, 卡迪夫.
    "uk": {"file": "united-kingdom.osm.pbf", "metro": "uk_metro_cities.json", "count": 7,
           "first": ["London", "Edinburgh", "Manchester", "Birmingham", "Glasgow"],
           "places": {"London": ("London", "伦敦"), "Edinburgh": ("Edinburgh", "爱丁堡"), "Manchester": ("Manchester", "曼彻斯特"),
                      "Birmingham": ("Birmingham", "伯明翰"), "Glasgow": ("Glasgow", "格拉斯哥"), "Cardiff": ("Cardiff", "加的夫"),
                      "Belfast": ("Belfast", "贝尔法斯特")}},
}
# Laos: the seats of the 18 first-level divisions (17 provinces and the prefecture of Vientiane),
# with the Chinese names of https://zh.wikipedia.org/zh-cn/老挝行政区划 (read 2026-10-19): the
# capital 万象, and 阿速坡, 会晒, 北汕 (Pakxan), 巴色, 桑怒 (Xam Neua), 他曲, 琅南塔, 琅勃拉邦,
# 芒赛 (Muang Xay), 丰沙里, 沙拉湾, 凯山丰威汉 (Savannakhet, the page's 凯山丰威汉市 without 市),
# 丰洪 (Phonhong), 沙耶武里, 塞公, 丰沙湾 (Phonsavan) and 阿努翁 (Anouvong, the page gives 阿努翁／
# 班蒙查). The places are the extract's place nodes of those Lao names. The China–Laos railway's
# stations have names of their own (孟赛 for the station of Muang Xay, 蓬洪 for Phonhong's):
# data/la_names.tsv.
COUNTRIES["la"] = {"file": "laos-latest.osm.pbf", "metro": "la_metro_cities.json", "count": 18,
                   "first": ["ວຽງຈັນ"],
                   "places": {name: (name, zh) for name, zh in (
                       ("ວຽງຈັນ", "万象"), ("ອັດຕະປື", "阿速坡"), ("ຫ້ວຍຊາຍ", "会晒"), ("ປາກຊັນ", "北汕"), ("ປາກເຊ", "巴色"),
                       ("ຊຳເໜືອ", "桑怒"), ("ທ່າແຂກ", "他曲"), ("ຫຼວງນ້ຳທາ", "琅南塔"), ("ຫຼວງພະບາງ", "琅勃拉邦"), ("ເມືອງໄຊ", "芒赛"),
                       ("ຜົ້ງສາລີ", "丰沙里"), ("ສາລະວັນ", "沙拉湾"), ("ສະຫວັນນະເຂດ", "凯山丰威汉"), ("ໂພນໂຮງ", "丰洪"),
                       ("ໄຊຍະບູລີ", "沙耶武里"), ("ເຊກອງ", "塞公"), ("ໂພນສະຫວັນ", "丰沙湾"), ("ອະນຸວົງ", "阿努翁"))}}
# Malaysia: the capital, the two other federal territories' seats (Putrajaya, Victoria on Labuan)
# and the capitals of the 13 states. The Chinese names are the zh-cn titles of the zh.wikipedia
# articles that the en.wikipedia articles of these cities link to (read 2026-10-19): 吉隆坡, 布城,
# 维多利亚 (马来西亚), 乔治市, 亚罗士打, 加央, 怡保, 莎阿南, 芙蓉 (森美兰), 马六甲市, 新山, 关丹,
# 瓜拉登嘉楼, 哥打峇鲁, 亚庇, 古晋 (the bracket that tells two articles apart taken off). The own
# name is the place node's, without Bandar / Bandaraya ("city").
COUNTRIES["my"] = {"file": "malaysia-singapore-brunei-latest.osm.pbf", "metro": "my_metro_cities.json", "count": 16,
                   "first": ["Kuala Lumpur", "George Town", "Johor Bahru"],
                   "places": {"Kuala Lumpur": ("Kuala Lumpur", "吉隆坡"), "Putrajaya": ("Putrajaya", "布城"), "Bandar Victoria": ("Victoria", "维多利亚"),
                              "George Town": ("George Town", "乔治市"), "Alor Setar": ("Alor Setar", "亚罗士打"), "Kangar": ("Kangar", "加央", "Kangar"),
                              "Ipoh": ("Ipoh", "怡保"), "Shah Alam": ("Shah Alam", "莎阿南"), "Seremban": ("Seremban", "芙蓉"),
                              "Bandaraya Melaka": ("Melaka", "马六甲市", "Malacca City"), "Johor Bahru": ("Johor Bahru", "新山"),
                              "Kuantan": ("Kuantan", "关丹"), "Kuala Terengganu": ("Kuala Terengganu", "瓜拉登嘉楼"),
                              "Kota Bharu": ("Kota Bharu", "哥打峇鲁"), "Kota Kinabalu": ("Kota Kinabalu", "亚庇"), "Kuching": ("Kuching", "古晋")}}
# Singapore: the city, 新加坡 (the zh-cn title of the article that en.wikipedia "Singapore" links to).
COUNTRIES["sg"] = {"file": "malaysia-singapore-brunei-latest.osm.pbf", "metro": "sg_metro_cities.json", "count": 1,
                   "first": ["Singapore"], "places": {"Singapore": ("Singapore", "新加坡")}}
# Thailand: Bangkok and the seats of the provinces (the admin_centre of each admin_level=4 relation
# of the extract) that have a Chinese name: the zh-cn title of the zh.wikipedia article that the
# en.wikipedia article of the town links to (read 2026-10-19; the article found within 4 km of the
# place node, or by the town's English name), without the bracket that tells two articles apart:
# 曼谷 (Bangkok); 北榄 (Samut Prakan); 暖武里 (Nonthaburi); 大城 (Phra Nakhon Si Ayutthaya (city)); 红统 (Ang Thong); 华富里 (Lopburi); 猜纳 (Chai Nat); 春武里 (Chonburi); 罗勇市 (Rayong); 庄他武里 (Chanthaburi); 达叻 (Trat); 差春骚 (Chachoengsao); 沙缴市 (Sa Kaeo); 那空叻差是玛 (Nakhon Ratchasima); 武里南 (Buriram); 乌汶叻差他尼 (Ubon Ratchathani); 猜也蓬 (Chaiyaphum); 安纳乍伦 (Amnat Charoen); 汶干 (Bueng Kan); 农磨兰普 (Nong Bua Lamphu); 孔敬 (Khon Kaen); 乌隆他尼 (Udon Thani); 廊开 (Nong Khai); 马哈沙拉堪 (Maha Sarakham); 黎逸 (Roi Et); 沙功那空 (Sakon Nakhon); 那空拍侬 (Nakhon Phanom); 穆达汉 (Mukdahan); 清迈 (Chiang Mai); 南奔 (Lamphun); 南邦 (Lampang); 程逸 (Uttaradit); 清莱 (Chiang Rai); 夜丰颂 (Mae Hong Son); 那空沙旺 (Nakhon Sawan); 乌泰他尼 (Uthai Thani); 彭世洛 (Phitsanulok); 披集 (Phichit); 干乍那武里 (Kanchanaburi); 佛统 (Nakhon Pathom); 那空是贪玛叻 (Nakhon Si Thammarat); 甲米 (Krabi); 普吉市 (Phuket (city)); 素叻他尼 (Surat Thani); 拉廊 (Ranong); 宋卡 (Songkhla); 董里市 (Trang, Thailand); 北大年 (Pattani, Thailand); 那拉提瓦 (Narathiwat).
# 49 of the 77; the other 28 seats have no such pair and no label (none made up).
COUNTRIES["th"] = {"file": "thailand-latest.osm.pbf", "metro": "th_metro_cities.json", "count": 49,
                   "first": ["กรุงเทพมหานคร", "เชียงใหม่", "ภูเก็ต"],
                   "places": {"กรุงเทพมหานคร": ("กรุงเทพมหานคร", "曼谷"), "สมุทรปราการ": ("สมุทรปราการ", "北榄"), "นนทบุรี": ("นนทบุรี", "暖武里"), "พระนครศรีอยุธยา": ("พระนครศรีอยุธยา", "大城"), "อ่างทอง": ("อ่างทอง", "红统"), "ลพบุรี": ("ลพบุรี", "华富里"), "ชัยนาท": ("ชัยนาท", "猜纳"), "ชลบุรี": ("ชลบุรี", "春武里"), "ระยอง": ("ระยอง", "罗勇市"), "จันทบุรี": ("จันทบุรี", "庄他武里"), "ตราด": ("ตราด", "达叻"), "ฉะเชิงเทรา": ("ฉะเชิงเทรา", "差春骚"), "สระแก้ว": ("สระแก้ว", "沙缴市"), "นครราชสีมา": ("นครราชสีมา", "那空叻差是玛"), "บุรีรัมย์": ("บุรีรัมย์", "武里南"), "อุบลราชธานี": ("อุบลราชธานี", "乌汶叻差他尼"), "ชัยภูมิ": ("ชัยภูมิ", "猜也蓬"), "อำนาจเจริญ": ("อำนาจเจริญ", "安纳乍伦"), "บึงกาฬ": ("บึงกาฬ", "汶干"), "หนองบัวลำภู": ("หนองบัวลำภู", "农磨兰普"), "ขอนแก่น": ("ขอนแก่น", "孔敬"), "อุดรธานี": ("อุดรธานี", "乌隆他尼"), "หนองคาย": ("หนองคาย", "廊开"), "มหาสารคาม": ("มหาสารคาม", "马哈沙拉堪"), "ร้อยเอ็ด": ("ร้อยเอ็ด", "黎逸"), "สกลนคร": ("สกลนคร", "沙功那空"), "นครพนม": ("นครพนม", "那空拍侬"), "มุกดาหาร": ("มุกดาหาร", "穆达汉"), "เชียงใหม่": ("เชียงใหม่", "清迈"), "ลำพูน": ("ลำพูน", "南奔"), "ลำปาง": ("ลำปาง", "南邦"), "อุตรดิตถ์": ("อุตรดิตถ์", "程逸"), "เชียงราย": ("เชียงราย", "清莱"), "แม่ฮ่องสอน": ("แม่ฮ่องสอน", "夜丰颂"), "นครสวรรค์": ("นครสวรรค์", "那空沙旺"), "อุทัยธานี": ("อุทัยธานี", "乌泰他尼"), "พิษณุโลก": ("พิษณุโลก", "彭世洛"), "พิจิตร": ("พิจิตร", "披集"), "กาญจนบุรี": ("กาญจนบุรี", "干乍那武里"), "นครปฐม": ("นครปฐม", "佛统"), "นครศรีธรรมราช": ("นครศรีธรรมราช", "那空是贪玛叻"), "กระบี่": ("กระบี่", "甲米"), "ภูเก็ต": ("ภูเก็ต", "普吉市"), "สุราษฎร์ธานี": ("สุราษฎร์ธานี", "素叻他尼"), "ระนอง": ("ระนอง", "拉廊"), "สงขลา": ("สงขลา", "宋卡"), "ตรัง": ("ตรัง", "董里市"), "ปัตตานี": ("ปัตตานี", "北大年"), "นราธิวาส": ("นราธิวาส", "那拉提瓦")}}
# Indonesia: Jakarta and the capitals of the 38 provinces (the admin_centre of each admin_level=4
# relation of the extract). The Chinese names are the zh-cn titles of the zh.wikipedia articles
# that the en.wikipedia articles of these cities link to (read 2026-10-19; found within 6 km of the
# place node, or by the city's English name), without the bracket that tells two articles apart:
# 班达亚齐 (Banda Aceh); 丹帕沙 (Denpasar); 邦加槟港 (Pangkalpinang); 明古鲁 (Bengkulu (city)); 西冷 (Serang); 哥伦打洛 (Gorontalo (city)); 占碑 (Jambi (city)); 万隆 (Bandung); 泗水 (Surabaya); 雅加达 (Jakarta); 三宝垄 (Semarang); 坤甸 (Pontianak); 沙马林达 (Samarinda); 班贾尔巴鲁 (Banjarbaru); 帕朗卡拉亚 (Palangka Raya); 丹戎施乐 (Tanjung Selor); 班达楠榜 (Bandar Lampung); 安汶 (Ambon, Maluku); 索菲菲 (Sofifi); 马塔兰 (Mataram (city)); 古邦 (Kupang); 查亚普拉 (Jayapura); 马诺夸里 (Manokwari); 索龙 (Sorong); 瓦梅纳 (Wamena); 纳比雷 (Nabire); 北干巴鲁 (Pekanbaru); 万鸦老 (Manado); 巴东 (Padang); 肯达里 (Kendari); 望加锡 (Makassar); 马穆朱 (Mamuju (city)); 巨港 (Palembang); 帕卢 (Palu); 棉兰 (Medan); 日惹 (Yogyakarta); 丹戎槟榔 (Tanjungpinang); 马老奇 (Merauke).
COUNTRIES["id"] = {"file": "indonesia-latest.osm.pbf", "metro": "id_metro_cities.json", "count": 38,
                   "first": ["Jakarta", "Surabaya", "Bandung", "Medan"],
                   "places": {"Banda Aceh": ("Banda Aceh", "班达亚齐"), "Denpasar": ("Denpasar", "丹帕沙"), "Pangkalpinang": ("Pangkalpinang", "邦加槟港"), "Bengkulu": ("Bengkulu", "明古鲁"), "Serang": ("Serang", "西冷"), "Gorontalo": ("Gorontalo", "哥伦打洛"), "Jambi": ("Jambi", "占碑"), "Bandung": ("Bandung", "万隆"), "Surabaya": ("Surabaya", "泗水"), "Jakarta": ("Jakarta", "雅加达"), "Semarang": ("Semarang", "三宝垄"), "Pontianak": ("Pontianak", "坤甸"), "Samarinda": ("Samarinda", "沙马林达"), "Banjarbaru": ("Banjarbaru", "班贾尔巴鲁"), "Palangka Raya": ("Palangka Raya", "帕朗卡拉亚"), "Tanjung Selor": ("Tanjung Selor", "丹戎施乐"), "Bandar Lampung": ("Bandar Lampung", "班达楠榜"), "Ambon": ("Ambon", "安汶"), "Sofifi": ("Sofifi", "索菲菲"), "Mataram": ("Mataram", "马塔兰"), "Kupang": ("Kupang", "古邦"), "Jayapura": ("Jayapura", "查亚普拉"), "Manokwari": ("Manokwari", "马诺夸里"), "Sorong": ("Sorong", "索龙"), "Wamena": ("Wamena", "瓦梅纳"), "Nabire": ("Nabire", "纳比雷"), "Pekanbaru": ("Pekanbaru", "北干巴鲁"), "Manado": ("Manado", "万鸦老"), "Padang": ("Padang", "巴东"), "Kendari": ("Kendari", "肯达里"), "Makassar": ("Makassar", "望加锡"), "Mamuju": ("Mamuju", "马穆朱"), "Palembang": ("Palembang", "巨港"), "Palu": ("Palu", "帕卢"), "Medan": ("Medan", "棉兰"), "Yogyakarta": ("Yogyakarta", "日惹"), "Tanjungpinang": ("Tanjungpinang", "丹戎槟榔"), "Merauke": ("Merauke", "马老奇")}}
EUROPE_CITY_NAMES = json.loads((ROOT / "data/europe_city_names.json").read_text())
# Of a continental European country's table, seven labels in ten are drawn (owner, 2026-10-22:
# "现在欧洲（除了uk）其他国家城市显示太多，减少30%"): every city of rank 1, then the cities of the
# metro lists, then the largest, by their Wikidata population (data/europe_city_populations.json;
# the extract's own population where Wikidata has none: OSM's tag can be a district's, Perugia's
# reads 69,000 against 162,000).
EUROPE_LABEL_SHARE = 0.7
# Every place of a European table, drawn or not, for scripts/process_europe.py: it hands a tram
# line across a border to the country of its nearest place (Saarbrücken's Saarbahn to Germany),
# and a place left off the map is still the nearest (without Saarbrücken the Saarbahn went to
# France, nearest Strasbourg: 2026-10-22). [own name, lon, lat], as cities.json writes them.
PLACES = ROOT / "data" / "europe_places.json"
ALL_PLACES = {}
EUROPE_POPULATIONS = json.loads((ROOT / "data/europe_city_populations.json").read_text())["cities"]
EUROPE_FILES = {"de": "germany", "fr": "france", "ch": "switzerland", "es": "spain",
                "nl": "netherlands", "be": "belgium", "it": "italy", "at": "austria", "hu": "hungary"}
for code in EUROPE_CITY_NAMES["label_cities"]:
    filename = EUROPE_FILES[code]
    locals_ = EUROPE_CITY_NAMES["label_cities"][code]
    sourced = EUROPE_CITY_NAMES["countries"][code]
    COUNTRIES[code] = {
        "file": f"{filename}-latest.osm.pbf", "metro": f"{code}_metro_cities.json",
        "count": len(locals_), "first": EUROPE_CITY_NAMES["rank1"][code],
        "places": {local: (sourced[local]["n"], sourced[local]["nz"],
                           *([sourced[local]["ne"]] if sourced[local]["ne"] != sourced[local]["n"] else []))
                   for local in locals_},
    }
COUNTRIES["es"]["files"] = ["spain-latest.osm.pbf", "canarias-latest.osm.pbf",
                           "ceuta-latest.osm.pbf", "melilla-latest.osm.pbf"]
# China: the seat of a unit where the extract names none (its admin_centre is missing, or is the
# unit's own label) or an old one: 红河's seat moved from 个旧 to 蒙自 in 2003.
SEATS = {"红河哈尼族彝族自治州": "蒙自", "凉山彝族自治州": "西昌", "大兴安岭地区": "加格达奇", "大理白族自治州": "大理",
         "海西蒙古族藏族自治州": "德令哈", "阿坝藏族羌族自治州": "马尔康", "巴音郭楞蒙古自治州": "库尔勒", "阿里地区": "狮泉河",
         "博尔塔拉蒙古自治州": "博乐"}
UNIT = re.compile(r"[一-鿿]+(市|自治州|地区|盟)")
UNITS = {"市": 293, "自治州": 30, "地区": 7, "盟": 3}

def km(a, b):
    return math.hypot((a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2)) * 111.3, (a[1] - b[1]) * 111.3)


def number(text):
    m = re.match(r"\d+", (text or "").replace(",", "").replace(" ", ""))
    return int(m.group()) if m else 0


def read(g):
    """One pass over a country's extract: its place nodes {id: (tags, lon, lat)} of the kinds KEPT
    and its administrative relations of level 4 and 5 [(id, tags, members)]."""
    paths = [RAW / name for name in COUNTRIES[g].get("files", [COUNTRIES[g]["file"]])]
    missing = [str(file_path) for file_path in paths if not file_path.exists()]
    if missing:
        sys.exit("missing input, nothing written: " + ", ".join(missing))
    nodes, relations = {}, []
    wanted = osmium.filter.KeyFilter("place", "admin_level")
    for file_path in paths:
        t0 = time.time()
        for o in osmium.FileProcessor(str(file_path), osmium.osm.NODE | osmium.osm.RELATION).with_filter(wanted):
            t = o.tags
            if o.is_node():
                if t.get("place") in KEPT and t.get("name"):
                    nodes[o.id] = ({k: t.get(k) for k in TAGS if t.get(k)}, o.location.lon, o.location.lat)
            elif t.get("boundary") == "administrative" and t.get("admin_level") in ("4", "5"):
                relations.append((o.id, {k: t.get(k) for k in TAGS if t.get(k)}, [(m.type, m.ref, m.role) for m in o.members if m.type != "w"]))
        print(f"{file_path.name}: {len(nodes)} place nodes, {len(relations)} regions, {time.time() - t0:.0f}s", flush=True)
    return nodes, relations


def english(tags):
    """A place's English name as the extract has it, without the word for the kind of place."""
    name = re.sub(r"\s+(City|Shi|Prefecture|Municipality|Town|County|District)$", "", (tags.get("name:en") or "").split(";")[0].strip())
    return name if re.fullmatch(r"[A-Za-z][A-Za-z .'’-]*", name) else ""


def entry(name, x, y, rank, **more):
    """One entry of the file; what is empty is left out."""
    return {"n": name, "at": [round(x, 2), round(y, 2)], "r": rank, **{k: v for k, v in more.items() if v}}


def zh(tags):
    """A Chinese name as the extract has it (in China name:zh and name are simplified)."""
    return re.split(r"\s", tags.get("name:zh-Hans") or tags.get("name:zh") or tags.get("name") or "")[0]


def china(nodes, relations, hand):
    """The seats of the prefecture-level units that the hand-made entries do not hold, as
    (label, lon, lat, size, unit, province, how the place was found)."""
    named = defaultdict(list)                   # the cities and towns of a name
    for tags, x, y in nodes.values():
        if tags.get("place") in ("city", "town"):
            for name in {tags.get(k) for k in ("name:zh-Hans", "name:zh", "name")} - {None}:
                named[name].append((tags, x, y))
    province = {}
    for _, tags, members in relations:
        if tags.get("admin_level") == "4" and re.search(r"(省|自治区)$", zh(tags)):
            for kind, ref, _ in members:
                if kind == "r":
                    province.setdefault(ref, zh(tags))
    units = [(i, t, m) for i, t, m in relations if t.get("admin_level") == "5" and i in province and UNIT.fullmatch(zh(t))]
    kinds = Counter(UNIT.fullmatch(zh(t)).group(1) for _, t, _ in units)
    if dict(kinds) != UNITS:
        sys.exit(f"nothing written: the extract has {dict(kinds)} prefecture-level units, the country has {UNITS}")
    have = {e["n"]: e for e in hand}
    found, covered = [], []
    for i, tags, members in sorted(units, key=lambda u: zh(u[1])):
        unit = zh(tags)
        role = defaultdict(list)
        for kind, ref, r in members:
            if kind == "n" and ref in nodes:
                role[r].append(nodes[ref])
        centre = next((n for n in role["admin_centre"] if n[0].get("place") in SETTLED), None)
        label = next(iter(role["label"]), None)
        anchor = next(((n[1], n[2]) for n in (centre, label, next(iter(role["admin_centre"]), None)) if n), None)
        nearest = lambda names: min((n for name in names for n in named.get(name, [])), key=lambda n: km((n[1], n[2]), anchor) if anchor else 0, default=None)
        if unit.endswith("市"):
            name = unit[:-1]
            seat, how = (centre, "admin_centre") if centre else (label, "label") if label and label[0].get("place") in ("city", "town") and zh(label[0]) == unit \
                else (nearest([unit, name]), "the city of that name")
        elif unit in SEATS:
            name = SEATS[unit]
            seat, how = nearest([name + end for end in ("市", "县", "区", "镇", "")]), "SEATS" + (f" (the extract: {zh(centre[0])})" if centre else "")
        else:
            seat, how = centre, "admin_centre"
            name = re.sub(r"(?<=..)(市|县|区|镇)$", "", zh(centre[0])) if centre else None        # (芒市 is 芒市)
        if not seat:
            sys.exit(f"nothing written: no seat found for {unit}")
        at = (round(seat[1], 2), round(seat[2], 2))
        if name in have:
            covered.append((unit, name, km(at, have[name]["at"])))
            continue
        close = [e["n"] for e in hand if km(at, e["at"]) < 5]
        if close:
            sys.exit(f"nothing written: {name} ({unit}) is on the spot of {close[0]}, which the file already has")
        # the English name of the unit when the label is the unit's, else of the seat when it is the place named
        en = (english(tags) if unit.endswith("市") else "") or (english(seat[0]) if re.sub(r"(?<=..)(市|县|区|镇)$", "", zh(seat[0])) == name else "")
        found.append((name, *at, number(tags.get("population")) or number(seat[0].get("population")), unit, province[i], how, en))
    twice = [n for n, c in Counter(f[0] for f in found).items() if c > 1]
    if twice:
        sys.exit(f"nothing written: two units would be labelled {twice}")
    found.sort(key=lambda f: (-f[3], f[0]))
    print(f"cn: {len(units)} prefecture-level units ({', '.join(f'{n} {k}' for k, n in kinds.items())}); {len(covered)} are among the {len(hand)} hand-made entries, {len(found)} added as rank 3")
    for prov in sorted({f[5] for f in found}):
        print(f"  {prov}: " + " ".join(f[0] for f in found if f[5] == prov))
    other = [f"{f[0]} ({f[4]}: {f[6]})" for f in found if f[6] != "admin_centre" or not f[4].startswith(f[0])]
    print("  seats not simply the unit's admin_centre under its own name: " + "; ".join(other))
    print("  hand-made entries more than 10 km from the seat found: " + ", ".join(f"{name} {d:.0f} km" for _, name, d in covered if d > 10))
    # the hand-made cities: the English name of the city or town of that name on the spot (40 km)
    for e in hand:
        there = min((n for name in (e["n"], e["n"] + "市", e["n"] + "区") for n in named.get(name, [])), key=lambda n: km((n[1], n[2]), e["at"]), default=None)
        e.pop("ne", None)
        if there and km((there[1], there[2]), e["at"]) < 40 and english(there[0]):
            e["ne"] = english(there[0])
    made = [entry(f[0], f[1], f[2], 3, ne=f[7]) for f in found]
    print("  without an English name in the extract: " + (" ".join(e["n"] for e in hand + made if "ne" not in e) or "none"))
    return made


def abroad(g, nodes):
    """The labelled places of a country other than China: rank 1 in the order of its list, then
    the others in the order of the table."""
    conf = COUNTRIES[g]
    evidence_file = ROOT / "data" / "europe_city_names.json"
    evidence = json.loads(evidence_file.read_text())["countries"].get(g, {}) if evidence_file.exists() else {}
    if g in EUROPE_FILES and not set(conf["places"]) <= set(evidence):
        sys.exit(f"nothing written: {g} needs a complete sourced city-name table")
    if len(conf["places"]) != conf["count"] or not set(conf["first"]) <= set(conf["places"]):
        sys.exit(f"nothing written: the table of {g} has {len(conf['places'])} places and is to have {conf['count']}, its rank 1 among them")
    metro = [c["n"] for c in json.loads((ROOT / "data" / conf["metro"]).read_text())] if (ROOT / "data" / conf["metro"]).exists() else []
    out, differs, people = [], [], {}
    for local in conf["first"] + [name for name in conf["places"] if name not in conf["first"]]:
        own, zh_name, *en = conf["places"][local]          # (an English name where the extract's is another place's)
        source = evidence.get(local, {})
        if source and (source["n"] != own or source["nz"] != zh_name):
            sys.exit(f"nothing written: {g} {local} differs from its sourced name")
        # the place node of that name: a city or a town, and of two the one with more people
        found = [n for n in nodes.values() if n[0]["name"] == local and n[0].get("place") in ("city", "town")]
        if not found or not own or not zh_name:
            sys.exit(f"nothing written: {local} ({g}) is not a city or town of the extract, or the table gives it no name")
        tags, x, y = max(found, key=lambda n: number(n[0].get("population")))
        theirs = re.split(r"\s*[/;；]\s*", tags.get("name:zh-Hans") or tags.get("name:zh") or "")[0]
        if theirs and not theirs.startswith(zh_name):
            differs.append(f"{local}: {theirs}, here {zh_name}")
        # (an English name that is only the own name without its accents, where the sourced English
        # name keeps them, is none: OSM's name:en of Győr is "Gyor", of Düsseldorf "Dusseldorf", the
        # letters a keyboard lacked; Zurich and Valencia are English names of their own)
        ne = next(iter(en), english(tags))
        bare = lambda text: unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
        if ne and ne != own and bare(ne) == bare(own) and source.get("ne") == own:
            ne = ""
        out.append(entry(own, x, y, 1 if local in conf["first"] else 2, g=g, side=conf.get("side", {}).get(local, ""), nz=zh_name, ne=ne if ne != own else "", m=zh_name if zh_name in metro else "", name_ref=source.get("ref")))
        people[own] = number(tags.get("population"))
    if len(out) != conf["count"] or len({e["n"] for e in out}) != len(out):
        sys.exit(f"nothing written: {g} is to have {conf['count']} labels, each of a name of its own")
    if g in EUROPE_FILES:
        ALL_PLACES[g] = [[e["n"], float(f"{e['at'][0]:.2f}"), float(f"{e['at'][1]:.2f}")] for e in out]
        population = lambda e: EUROPE_POPULATIONS.get((e.get("name_ref") or "").rsplit("/", 1)[-1], {}).get("population") or people[e["n"]]
        ranked = sorted(out, key=lambda e: (e["r"] != 1, not e.get("m"), -population(e)))
        drawn = {e["n"] for e in ranked[:round(EUROPE_LABEL_SHARE * len(out))]}
        print(f"  {g}: {len(drawn)} of {len(out)} drawn; left out: " + " ".join(f"{e['n']} ({population(e)})" for e in ranked[len(drawn):]))
        out = [e for e in out if e["n"] in drawn]
    known = {e.get("m") for e in out}
    print(f"{g}: {len(out)} labels (rank 1: {sum(e['r'] == 1 for e in out)}, rank 2: {sum(e['r'] == 2 for e in out)})")
    for rank in (1, 2):
        print(f"  rank {rank}: " + " ".join(f"{e['n']}/{e['nz']}/{e.get('ne', '-')}" for e in out if e["r"] == rank))
    print("  metro cities that are none of these (no label): " + (" ".join(n for n in metro if n not in known and not re.search(r"(其他|城际)$", n)) or "none"))
    print("  the extract's Chinese name is another: " + ("; ".join(differs) or "nowhere"))
    return out


def write(entries):
    """One entry to a line, numbers to two places."""
    line = lambda e: "{" + ",".join(f'"at":[{e["at"][0]:.2f},{e["at"][1]:.2f}]' if k == "at" else f'"{k}":{json.dumps(v, ensure_ascii=False)}' for k, v in e.items()) + "}"
    OUT.write_text("[\n" + ",\n".join(line(e) for e in entries) + "\n]\n")


def main(only):
    # (the file as it was before it held more than one name to a place was lists: [name, lon, lat, rank, country])
    old = [e if isinstance(e, dict) else entry(e[0], e[1], e[2], e[3], g=e[4] if len(e) > 4 else "") for e in json.loads(OUT.read_text())]
    country = lambda e: e.get("g", "cn")
    hand = [e for e in old if country(e) == "cn" and e["r"] in (1, 2)]
    wanted = [g for g in COUNTRIES if not only or g == only]
    made = {g: [e for e in old if country(e) == g and e not in hand] for g in COUNTRIES}
    for g in wanted:
        nodes, relations = read(g)
        made[g] = china(nodes, relations, hand) if g == "cn" else abroad(g, nodes)
    before = OUT.stat().st_size
    write(hand + [e for g in COUNTRIES for e in made[g]])
    if ALL_PLACES:
        places = json.loads(PLACES.read_text()) if PLACES.exists() else {}
        places.update(ALL_PLACES)
        PLACES.write_text(json.dumps({g: places[g] for g in sorted(places)}, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"wrote {OUT}: {len(hand)} hand-made and {sum(len(v) for v in made.values())} more entries, {before} -> {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    if len(sys.argv) > 2 or (sys.argv[1:] and sys.argv[1] not in COUNTRIES):
        sys.exit(__doc__)
    main(sys.argv[1] if sys.argv[1:] else None)
