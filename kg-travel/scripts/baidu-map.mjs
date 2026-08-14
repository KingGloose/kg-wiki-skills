#!/usr/bin/env node
import { closeSync, openSync, readFileSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { isFile, readJson } from "../../lib/fs.mjs";

const API = "https://api.map.baidu.com";
const COMMON_DISTRICTS = {
  110101: "东城区", 110102: "西城区", 110105: "朝阳区", 110106: "丰台区", 110107: "石景山区", 110108: "海淀区", 110109: "门头沟区", 110111: "房山区", 110112: "通州区", 110113: "顺义区", 110114: "昌平区", 110115: "大兴区", 110116: "怀柔区", 110117: "平谷区", 110118: "密云区", 110119: "延庆区",
  310101: "黄浦区", 310104: "徐汇区", 310105: "长宁区", 310106: "静安区", 310107: "普陀区", 310109: "虹口区", 310110: "杨浦区", 310112: "闵行区", 310113: "宝山区", 310114: "嘉定区", 310115: "浦东新区",
  440103: "荔湾区", 440104: "越秀区", 440105: "海珠区", 440106: "天河区", 440111: "白云区", 440112: "黄埔区", 440303: "罗湖区", 440304: "福田区", 440305: "南山区", 440306: "宝安区",
};
const CITY_NAMES = { beijing: "北京", shanghai: "上海", guangzhou: "广州", shenzhen: "深圳", chengdu: "成都", hangzhou: "杭州", wuhan: "武汉", xian: "西安", nanjing: "南京", tianjin: "天津", chongqing: "重庆", suzhou: "苏州", haidian: "海淀", chaoyang: "朝阳", dongcheng: "东城", xicheng: "西城", pudong: "浦东", changping: "昌平" };

function configDirectory(env = process.env) {
  return env.KG_AGENT_CONFIG_DIR?.trim() || join(homedir(), ".kg-agent-config");
}

export function loadAk({ env = process.env, credentials = join(configDirectory(env), "credentials.json") } = {}) {
  let ak = env.BAIDU_MAP_AK;
  if (isFile(credentials)) {
    let config;
    try { config = JSON.parse(readFileSync(credentials, "utf8")); }
    catch (error) { throw new Error(`${credentials} 不是合法 JSON：${error instanceof Error ? error.message : String(error)}`); }
    ak = config?.baidu_map?.ak || ak;
  }
  if (!ak) throw new Error('未找到百度地图 AK。请在 ~/.kg-agent-config/credentials.json 写入 {"baidu_map":{"ak":"..."}}，或设置 BAIDU_MAP_AK。');
  return ak;
}

function sleep(milliseconds) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));
}

export async function throttleBaidu({ env = process.env, now = () => Date.now(), sleepImpl = sleep } = {}) {
  const directory = configDirectory(env);
  const lock = join(directory, ".baidu_throttle.lock");
  const state = join(directory, ".baidu_throttle.state");
  const minimum = Number(env.BAIDU_MIN_INTERVAL ?? "0.4") * 1000;
  if (!Number.isFinite(minimum) || minimum < 0) throw new Error("BAIDU_MIN_INTERVAL 必须是非负数");
  const { mkdirSync } = await import("node:fs");
  mkdirSync(directory, { recursive: true });
  const deadline = now() + 15_000;
  let descriptor;
  while (descriptor == null) {
    try { descriptor = openSync(lock, "wx", 0o600); }
    catch (error) {
      if (error?.code !== "EEXIST") throw error;
      try { if (now() - statSync(lock).mtimeMs > 30_000) unlinkSync(lock); } catch {}
      if (now() >= deadline) throw new Error("等待百度地图限流锁超时");
      await sleepImpl(50);
    }
  }
  try {
    let last = 0;
    try { last = Number(readFileSync(state, "utf8")) || 0; } catch {}
    const wait = last + minimum - now();
    if (wait > 0) await sleepImpl(wait);
    writeFileSync(state, String(now()), { mode: 0o600 });
  } finally {
    closeSync(descriptor);
    try { unlinkSync(lock); } catch {}
  }
}

export async function httpGet(path, params, { fetchImpl = fetch, ak, throttle = throttleBaidu } = {}) {
  await throttle();
  const query = new URLSearchParams({ ...Object.fromEntries(Object.entries(params).map(([key, value]) => [key, String(value)])), output: "json", ak: ak || loadAk() });
  let response;
  try { response = await fetchImpl(`${API}${path}?${query}`, { signal: AbortSignal.timeout(15_000) }); }
  catch (error) { throw new Error(`请求失败：${error instanceof Error ? error.message : String(error)}`); }
  if (!response.ok) throw new Error(`请求失败：HTTP ${response.status}`);
  let data;
  try { data = await response.json(); } catch (error) { throw new Error(`百度地图返回的不是合法 JSON：${error instanceof Error ? error.message : String(error)}`); }
  if (data.status !== 0) throw new Error(`百度地图返回 status=${data.status}: ${data.message}`);
  return data;
}

export function parseCoordinate(text) {
  const parts = String(text).split(",").map((value) => value.trim());
  if (parts.length !== 2 || parts.some((value) => value === "" || !Number.isFinite(Number(value)))) return null;
  return { lng: Number(parts[0]), lat: Number(parts[1]) };
}

export function navigationLink(destination, { origin = "我的位置", mode = "transit", city = "北京" } = {}) {
  const coordinate = parseCoordinate(destination);
  const target = coordinate ? `latlng:${coordinate.lat},${coordinate.lng}|name:目的地` : destination;
  const params = new URLSearchParams({ origin, destination: target, mode, region: city, output: "html", src: "webapp.kgwiki.personal" });
  return `http://api.map.baidu.com/direction?${params}`;
}

function formatPoi(item) {
  const details = item.detail_info || {}; const parts = [`· ${item.name}`];
  if (details.overall_rating) parts.push(`评分${details.overall_rating}`);
  if (item.address) parts.push(item.address);
  if (details.price) parts.push(`参考价${details.price}`);
  return parts.join(" | ");
}

function parseCli(argv) {
  const command = argv[0]; const positionals = []; const options = {};
  const booleans = new Set(["--poi"]);
  for (let index = 1; index < argv.length; index += 1) {
    const value = argv[index];
    if (booleans.has(value)) options[value.slice(2)] = true;
    else if (value.startsWith("--")) { if (!argv[index + 1]) throw new Error(`${value} 缺少值`); options[value.slice(2)] = argv[++index]; }
    else positionals.push(value);
  }
  return { command, positionals, options };
}

function positiveInteger(value, fallback, name) {
  const number = value == null ? fallback : Number(value);
  if (!Number.isInteger(number) || number < 1) throw new Error(`${name} 必须是正整数`);
  return number;
}

export function createBaiduClient(request = httpGet) {
  const resolveCoordinate = async (value) => {
    const parsed = parseCoordinate(value);
    if (parsed) return { lat: parsed.lat, lng: parsed.lng };
    const data = await request("/geocoding/v3/", { address: value });
    const location = data.result?.location;
    if (!location) throw new Error(`无法解析地点：${value}`);
    return location;
  };
  const resolveDistrict = async (value) => {
    let city = String(value || "北京").trim();
    if (/^\d{6,}$/.test(city)) return city.slice(0, 6);
    city = CITY_NAMES[city.toLocaleLowerCase()] || city;
    const known = Object.entries(COMMON_DISTRICTS).find(([, name]) => name.includes(city) || city.includes(name));
    if (known) return known[0];
    const data = await request("/api_region_search/v1/", { keyword: city, sub_admin: 1, extensions_code: 1 });
    return data.districts?.find((district) => district.districts?.length)?.districts?.[0]?.code || "";
  };
  return { resolveCoordinate, resolveDistrict, request };
}

export async function main(argv = process.argv.slice(2), { request = httpGet } = {}) {
  const { command, positionals, options } = parseCli(argv);
  if (!command || ["--help", "-h"].includes(command)) {
    console.log("baidu-map.mjs weather|geocode|reverse|search|around|transit|driving|walk|bike|navlink ..."); return command ? 0 : 1;
  }
  const client = createBaiduClient(request);
  if (command === "navlink") {
    const destination = positionals[0]; if (!destination) throw new Error("navlink 需要目的地");
    const mode = options.mode || "transit"; if (!["transit", "driving", "walking"].includes(mode)) throw new Error("--mode 只支持 transit/driving/walking");
    const url = navigationLink(destination, { origin: options.origin, mode, city: options.city });
    console.log(`${url}\n\n[提示] 打开此链接即可导航到 ${destination}。（${mode} 方式，起点 ${options.origin || "我的位置"}）`); return 0;
  }
  if (command === "geocode") {
    const address = positionals[0]; if (!address) throw new Error("geocode 需要地名");
    const data = await request("/geocoding/v3/", { address }); const result = data.result || {}; const location = result.location || {};
    console.log(JSON.stringify({ name: address, lng: location.lng, lat: location.lat, level: result.level, confidence: result.confidence }, null, 2)); return 0;
  }
  if (command === "reverse") {
    const coordinate = parseCoordinate(positionals[0]); if (!coordinate) throw new Error("reverse 坐标必须是 lng,lat");
    const data = await request("/reverse_geocoding/v3/", { location: `${coordinate.lat},${coordinate.lng}`, extensions_poi: options.poi ? 1 : 0 }); const result = data.result || {};
    console.log(JSON.stringify({ formatted_address: result.formatted_address, province: result.province, city: result.city, district: result.district, pois: (result.pois || []).slice(0, 5).map((poi) => poi.name) }, null, 2)); return 0;
  }
  if (command === "search") {
    const query = positionals[0]; if (!query) throw new Error("search 需要关键词");
    const params = { query, scope: 2 }; if (options.region) { params.region = options.region; params.region_limit = true; } if (options.center) params.center = options.center; if (options.filter) params.filter = options.filter;
    const results = (await request("/place/v3/region", params)).results || []; console.log(`共 ${results.length} 条结果（关键词: ${query}）`); results.slice(0, positiveInteger(options.limit, 5, "--limit")).forEach((item) => console.log(formatPoi(item))); return 0;
  }
  if (command === "around") {
    const coordinate = parseCoordinate(positionals[0]); const query = positionals[1]; if (!coordinate || !query) throw new Error("around 需要 lng,lat 和关键词");
    const radius = positiveInteger(options.radius, 2000, "--radius"); const sort = options.sort || "overall_rating";
    const data = await request("/place/v3/around", { query, location: `${coordinate.lat},${coordinate.lng}`, radius, scope: 2, radius_limit: true, filter: `industry_type:${options.industry || "cater"}|sort_name:${sort}|sort_rule:${options.rule || "0"}` });
    const results = data.results || []; console.log(`坐标 ${positionals[0]} 周边 ${radius}m 内「${query}」共 ${results.length} 条（按${sort}排序）：`); results.slice(0, positiveInteger(options.limit, 5, "--limit")).forEach((item) => console.log(formatPoi(item))); return 0;
  }
  if (["transit", "driving", "walk", "bike"].includes(command)) {
    const origin = positionals[0]; const destination = positionals[1]; if (!origin || !destination) throw new Error(`${command} 需要起点和终点`);
    const [from, to] = await Promise.all([client.resolveCoordinate(origin), client.resolveCoordinate(destination)]);
    const mode = { walk: "walking", bike: "riding" }[command] || command; const params = { origin: `${from.lat},${from.lng}`, destination: `${to.lat},${to.lng}` };
    if (mode === "transit") params.city1 = params.city2 = options.city || "北京";
    const route = (await request(`/direction/v2/${mode}`, params)).result?.routes?.[0];
    if (!route) { console.log("[提示] 没有可用的路线方案。"); return 0; }
    console.log(`路线: ${origin} → ${destination}`); if (route.distance) console.log(`距离: ${route.distance} 米 | 预计: ${(route.duration / 60).toFixed(0)} 分钟`); if (route.traffic_condition) console.log(`路况: ${route.traffic_condition}`);
    for (let step of (route.steps || []).slice(0, 10)) {
      if (Array.isArray(step)) step = step[0] || {}; if (!step || typeof step !== "object") continue;
      if (step.vehicle) console.log(`  → 坐${step.vehicle.name || "公交"}(${step.vehicle.start_name || ""}→${step.vehicle.end_name || ""})${step.vehicle.stop_num ? ` ${step.vehicle.stop_num}站` : ""}`);
      else if (step.instructions) console.log(`  → ${step.instructions.replace(/<[^>]+>/g, "").slice(0, 60)}`);
    }
    if (route.walking_distance) console.log(`总步行: ${route.walking_distance} 米`); return 0;
  }
  if (command === "weather") {
    const district = options.district || await client.resolveDistrict(options.city || "北京"); if (!district) throw new Error(`无法确定行政区划编码：${options.city}`);
    const type = options.data || "all"; if (!["now", "fc", "index", "alert", "all"].includes(type)) throw new Error("--data 不支持");
    const result = (await request("/weather/v1/", { district_id: district, data_type: type })).result || {}; const location = result.location || {};
    console.log(`📍 ${[location.province, location.city, location.name].filter((value, index, all) => value && value !== all[index - 1]).join("")}（${district}）`);
    const current = result.now; if (current) console.log(`  现在: ${current.text} ${current.temp}°C 体感${current.feels_like}°C 湿度${current.rh}% ${current.wind_dir}${current.wind_class} AQI${current.aqi} 紫外线${current.uvi}`);
    (result.forecasts || []).slice(0, positiveInteger(options.days, 3, "--days")).forEach((forecast) => console.log(`  ${forecast.date || ""} ${forecast.text_day}/${forecast.text_night} ${forecast.high}°/${forecast.low || ""}° ${forecast.wd_day || ""}`));
    (result.indexes || []).slice(0, positiveInteger(options["index-limit"], 6, "--index-limit")).forEach((item) => console.log(`  · ${item.name}: ${item.brief} — ${(item.detail || "").slice(0, 40)}`));
    (result.alerts || []).forEach((alert) => console.log(`  ⚠️ ${alert.title || ""}: ${(alert.desc || "").slice(0, 60)}`)); return 0;
  }
  throw new Error(`未知命令: ${command}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().then((code) => { process.exitCode = code; }, (error) => { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; });
}
