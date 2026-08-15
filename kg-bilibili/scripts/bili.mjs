#!/usr/bin/env node
/**
 * kg-bilibili CLI —— 封装 @renmu/bili-api，让 AI 通过 bash 操作 B站。
 *
 * stdout 只输出 JSON / 文本（给 AI 读）；进度、二维码、错误打 stderr（给人看）。
 * 用法：
 *   bili login            扫码登录（cookie 存 ~/.piko-config/credentials/bilibili.json）
 *   bili up <uid>         查某 UP 的信息 + 动态 + 投稿
 *   bili search <关键词>   搜视频 / UP / 番剧
 *   bili video <BV号>     视频详情
 *   bili subtitle <BV号>  下载字幕（srt，输出到 stdout）
 */
import { BcutASR, Client, TvQrcodeLogin, utils } from "@renmu/bili-api";
import QRCode from "qrcode";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

const COOKIE_FILE = join(homedir(), ".piko-config", "credentials", "bilibili.json");
const AUTHCODE_FILE = join(homedir(), ".piko-config", "state", "bili-authcode.json");

function out(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  process.stdout.write(text + "\n");
}

function err(msg) {
  process.stderr.write(String(msg) + "\n");
}

function fail(msg) {
  err(msg);
  process.exit(1);
}

/** 建一个 Client，有 cookie 就带上登录态（兼容新旧两种格式）。 */
async function getClient() {
  const client = new Client();
  if (existsSync(COOKIE_FILE)) {
    const raw = JSON.parse(readFileSync(COOKIE_FILE, "utf8"));
    if (raw?.cookie_info?.cookies) {
      // 新格式（本 skill 扫码登录写的 TV 端格式）
      await client.loadCookieFile(COOKIE_FILE);
    } else if (raw?.SESSDATA) {
      // 旧格式（扁平 cookie，之前 login.py 写的），转成 setAuth
      client.setAuth(
        {
          SESSDATA: raw.SESSDATA,
          bili_jct: raw.BILI_JCT ?? raw.bili_jct ?? "",
          DedeUserID: raw.DEDEUSERID ?? raw.DedeUserID ?? "",
          buvid3: raw.BUVID3 ?? raw.buvid3 ?? "",
        },
        Number(raw.DEDEUSERID ?? raw.DedeUserID ?? 0),
      );
    }
  }
  return client;
}

/** 生成二维码（不等待），保存 auth_code 到 state，方便两步式扫码。 */
async function qrcode() {
  const tv = new TvQrcodeLogin();
  const { url, auth_code } = await tv.getQrcode();
  mkdirSync(dirname(AUTHCODE_FILE), { recursive: true });
  writeFileSync(AUTHCODE_FILE, JSON.stringify({ auth_code, created_at: Date.now() }, null, 2), "utf8");
  const pngPath = join(homedir(), ".piko-config", "state", "bili-qrcode.png");
  mkdirSync(dirname(pngPath), { recursive: true });
  await QRCode.toFile(pngPath, url, { width: 400, margin: 1 });
  out({ ok: true, url, auth_code, png: pngPath });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/** 扫码登录：轮询直到扫码成功，写 cookie。可传 auth_code 复用已生成的二维码。 */
async function login(authCodeArg) {
  let authCode = authCodeArg;
  if (!authCode) {
    // 一体：先生成二维码再轮询（适合终端交互）
    const tv = new TvQrcodeLogin();
    const q = await tv.getQrcode();
    authCode = q.auth_code;
    const pngPath = join(homedir(), ".piko-config", "state", "bili-qrcode.png");
    mkdirSync(dirname(pngPath), { recursive: true });
    await QRCode.toFile(pngPath, q.url, { width: 400, margin: 1 });
    err("请用手机 B站 App 扫码登录：");
    err("二维码图片：" + pngPath);
    err("登录链接：" + q.url);
    err("");
  }

  const tv = new TvQrcodeLogin();
  const deadline = Date.now() + 300_000;
  while (Date.now() < deadline) {
    const res = await tv.poll(authCode);
    if (res.code === 0) {
      mkdirSync(dirname(COOKIE_FILE), { recursive: true });
      writeFileSync(COOKIE_FILE, JSON.stringify(res.data, null, 2), "utf8");
      out({ ok: true, msg: "登录成功，cookie 已保存", cookie: COOKIE_FILE });
      return;
    }
    if (res.code === 86038) fail("二维码已失效，重新 bili qrcode 再 bili login");
    if (res.code === 86039 || res.code === 86090) {
      await sleep(2000);
      continue;
    }
    fail("登录失败：" + (res.message || res.code));
  }
  fail("扫码超时（5 分钟）");
}

/** 查某 UP：信息 + 动态 + 投稿（三个接口独立，一个失败不影响其他）。 */
async function up(midStr) {
  const mid = Number(midStr);
  if (!Number.isFinite(mid) || mid <= 0) fail("uid 要是数字，例如：bili up 123456");
  const client = await getClient();
  const result = {};
  try {
    // getCardInfo 比 getUserInfo 稳（后者风控严）
    result.info = await client.user.getCardInfo(mid);
  } catch (e) {
    try {
      result.info = await client.user.getUserInfo(mid);
    } catch (e2) {
      result.info = { error: e instanceof Error ? e.message : String(e) };
    }
  }
  try {
    result.dynamics = await client.user.space(mid);
  } catch (e) {
    result.dynamics = { error: e instanceof Error ? e.message : String(e) };
  }
  try {
    const videos = await client.user.getVideos({ mid });
    result.videos = videos?.list?.vlist ?? videos?.vlist ?? [];
  } catch (e) {
    result.videos = { error: e instanceof Error ? e.message : String(e) };
  }
  out(result);
}

/** 综合搜索。 */
async function search(keyword) {
  if (!keyword) fail("要一个关键词，例如：bili search Flutter");
  const client = await getClient();
  const res = await client.search.all({ keyword });
  out(res);
}

/** 视频详情。 */
async function video(bvid) {
  if (!bvid) fail("要一个 BV 号，例如：bili video BV1xx411c7mD");
  const client = await getClient();
  const info = await client.video.getInfo({ bvid });
  out(info);
}

/** 下载字幕（srt），输出到 stdout。 */
async function subtitle(bvid) {
  if (!bvid) fail("要一个 BV 号，例如：bili subtitle BV1xx411c7mD");
  const client = await getClient();
  const info = await client.video.getInfo({ bvid });
  const cid = info?.data?.cid ?? info?.cid;
  if (!cid) fail("拿不到视频 cid（可能视频不存在，或需要登录）");

  const output = join(homedir(), ".piko-config", "state", `bili-subtitle-${bvid}.srt`);
  try {
    const path = await client.video.downloadSubtitle({ bvid, cid, output, useV2: true });
    out(readFileSync(path, "utf8"));
  } catch (e) {
    fail(`下载字幕失败：${e instanceof Error ? e.message : String(e)}`);
  }
}

/** 弹幕（protobuf → XML，输出到 stdout）。 */
async function danmaku(bvid) {
  if (!bvid) fail("要一个 BV 号，例如：bili danmaku BV1xx411c7mD");
  const client = await getClient();
  const info = await client.video.getInfo({ bvid });
  const cid = info?.data?.cid ?? info?.cid;
  const aid = info?.data?.aid ?? info?.aid;
  if (!cid) fail("拿不到视频 cid");
  const buf = await client.video.getAllDm({ aid, bvid, cid });
  const xml = await utils.protoBufToXml(buf);
  out(xml);
}

/** 整视频下载（dash 高清，ffmpeg 合并音视频）。 */
async function download(bvid, output, qnStr) {
  if (!bvid) fail("要一个 BV 号，例如：bili download BV1xx411c7mD");
  const dest = output || join(homedir(), "Downloads", `${bvid}.mp4`);
  const client = await getClient();
  // 默认要最低清晰度（240p）：提取字幕/ASR 只用到音频，视频画质无所谓，省流量省磁盘。
  // 有的视频没有 240p，自动降到它支持的最低清晰度（通常 360p）。
  // 想要更高清传第三个参数：16=360p 32=480p 64=720p 80=1080p
  const wanted = qnStr && [6, 16, 32, 64, 80, 112, 116].includes(Number(qnStr)) ? Number(qnStr) : 6;
  let qn = wanted;
  try {
    const { cid } = await getAidCid(client, bvid);
    if (cid) {
      const play = await client.video.playurl({ bvid, cid, fnval: 16 | 4048 });
      const accepts = (play?.accept_quality || play?.dash?.video?.map((v) => v.id) || []).filter(
        (n) => typeof n === "number",
      );
      if (accepts.length > 0) {
        qn = accepts.includes(wanted) ? wanted : Math.min(...accepts);
      }
    }
  } catch {
    // 拿不到清晰度就保持想要的档，库里没有这个档会报错，由调用方重试/换参数
  }
  const task = await client.video.download(
    { bvid, output: dest, ffmpegBinPath: "ffmpeg" },
    { qn },
    true,
  );
  await new Promise((resolve, reject) => {
    task.on("progress", (p) => {
      if (p.event === "download" && p.progress) {
        err(`下载进度：${Math.floor(p.progress.progress * 100)}%`);
      } else if (p.event === "merge-start") {
        err("下载完成，正在合并音视频…");
      }
    });
    task.on("completed", () => resolve());
    task.on("error", (msg) => reject(new Error(String(msg))));
  });
  out({ ok: true, output: dest });
}

/** 直播：房间信息 + 主播信息。 */
async function live(roomIdStr) {
  const roomId = Number(roomIdStr);
  if (!Number.isFinite(roomId) || roomId <= 0) fail("要一个直播间号，例如：bili live 12345");
  const client = await getClient();
  const result = {};
  try {
    result.room = await client.live.getRoomInfo(roomId);
  } catch (e) {
    result.room = { error: e instanceof Error ? e.message : String(e) };
  }
  const uid = result.room?.uid;
  if (uid) {
    try {
      result.master = await client.live.getMasterInfo(uid);
    } catch (e) {
      result.master = { error: e instanceof Error ? e.message : String(e) };
    }
  }
  out(result);
}

/** 评论列表（按点赞排序）。 */
async function comment(bvid, pageStr) {
  if (!bvid) fail("要一个 BV 号，例如：bili comment BV1xx411c7mD");
  const client = await getClient();
  const info = await client.video.getInfo({ bvid });
  const aid = info?.data?.aid ?? info?.aid;
  if (!aid) fail("拿不到视频 aid");
  const pn = pageStr ? Math.max(1, Number(pageStr) || 1) : 1;
  const res = await client.reply.list({ oid: aid, type: 1, sort: 1, ps: 20, pn });
  out(res);
}

/** ASR 语音转文字（B站必剪接口）。 */
async function asr(filePath) {
  if (!filePath) fail("要一个音频文件路径，例如：bili asr /path/to/audio.mp3");
  const asr = new BcutASR(filePath);
  const res = await asr.recognize();
  out(res.toSrt());
}

/** 稍后再看列表（B站 toview 接口，库没封装，直接 fetch，需登录态）。 */
async function toview() {
  const client = await getClient();
  const cookie = client.auth.cookie;
  if (!cookie) fail("需要先登录（bili qrcode + bili login <auth_code>）");
  // B站接口偶发不稳（限流），空结果/报错就重试，最多 3 次
  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await fetch("https://api.bilibili.com/x/v2/history/toview", {
      headers: {
        cookie,
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        Referer: "https://www.bilibili.com/",
      },
    });
    const data = await res.json();
    if (data?.code !== 0) {
      if (attempt < 3) {
        err(`第 ${attempt} 次获取失败（${data?.code || data?.message}），重试…`);
        await new Promise((r) => setTimeout(r, 1500));
        continue;
      }
      fail(`获取稍后再看失败：${data?.message || data?.code}`);
    }
    out(data.data);
    return;
  }
}

/** 拿视频的 aid + cid（多个子命令要用）。 */
async function getAidCid(client, bvid) {
  const info = await client.video.getInfo({ bvid });
  return {
    aid: info?.data?.aid ?? info?.aid,
    cid: info?.data?.cid ?? info?.cid,
  };
}

/** 我的信息。 */
async function me() {
  const client = await getClient();
  out(await client.user.getMyInfo());
}

/** 收藏夹列表。 */
async function favlist() {
  const client = await getClient();
  // 库的 listFavoriteBox 参数标了可选但实现里直接读 params.aid，不传会崩
  out(await client.video.listFavoriteBox({ type: 2 }));
}

/** 某 UP 的合集/系列列表。 */
async function collections(uidStr) {
  const mid = Number(uidStr);
  if (!Number.isFinite(mid) || mid <= 0) fail("要一个 uid，例如：bili collections 517327498");
  const client = await getClient();
  out(await client.user.getCollectionList({ mid }));
}

/** 合集-视频列表。 */
async function seriesvideos(uidStr, seriesIdStr) {
  const mid = Number(uidStr);
  const series_id = Number(seriesIdStr);
  if (!Number.isFinite(mid) || !Number.isFinite(series_id)) fail("用法：bili seriesvideos <uid> <series_id>");
  const client = await getClient();
  out(await client.user.getSeriesVideos({ mid, series_id }));
}

/** 合集-投稿列表（season）。 */
async function seasons(uidStr, seasonIdStr) {
  const mid = Number(uidStr);
  const season_id = Number(seasonIdStr);
  if (!Number.isFinite(mid) || !Number.isFinite(season_id)) fail("用法：bili seasons <uid> <season_id>");
  const client = await getClient();
  out(await client.user.getSeasons({ mid, season_id }));
}

/** 分P列表。 */
async function pages(bvid) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  out(await client.video.pagelist({ bvid }));
}

/** 播放地址。 */
async function playurl(bvid) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  const { cid } = await getAidCid(client, bvid);
  if (!cid) fail("拿不到 cid");
  out(await client.video.playurl({ bvid, cid, fnval: 16 | 4048 }));
}

/** 播放信息（含字幕列表）。 */
async function playerinfo(bvid) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  const { cid } = await getAidCid(client, bvid);
  if (!cid) fail("拿不到 cid");
  out(await client.video.playerInfo({ bvid, cid }));
}

/** 视频简介。 */
async function desc(bvid) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  out(await client.video.desc({ bvid }));
}

/** 舰长列表。 */
async function liveguard(roomIdStr) {
  const roomId = Number(roomIdStr);
  if (!Number.isFinite(roomId) || roomId <= 0) fail("要一个直播间号");
  const client = await getClient();
  const room = await client.live.getRoomInfo(roomId);
  const uid = room?.uid;
  if (!uid) fail("拿不到主播 uid");
  out(await client.live.getGuardTopList({ user_id: uid, room_id: roomId, page: 1, page_size: 20 }));
}

/** 直播回放列表。 */
async function liveslice(roomIdStr) {
  const roomId = Number(roomIdStr);
  if (!Number.isFinite(roomId) || roomId <= 0) fail("要一个直播间号");
  const client = await getClient();
  const room = await client.live.getRoomInfo(roomId);
  const uid = room?.uid;
  if (!uid) fail("拿不到主播 uid");
  out(await client.live.getSliceList({ live_uid: uid, time_range: 1, page: 1, page_size: 10 }));
}

/** 分类搜索。 */
async function searchtype(keyword, type) {
  if (!keyword || !type) fail("用法：bili searchtype <关键词> <类型: video|bili_user|media_bangumi|live_room>");
  const client = await getClient();
  out(await client.search.type({ keyword, search_type: type }));
}

/** 分区列表。 */
async function areas() {
  const client = await getClient();
  out(await client.common.getAreas());
}

/** 评论数。 */
async function replycount(bvid) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  const { aid } = await getAidCid(client, bvid);
  if (!aid) fail("拿不到 aid");
  out(await client.reply.count({ oid: aid, type: 1 }));
}

// ── 写操作（会改变账号状态，务必先 ask_master 确认）──

async function like(bvid) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  const { aid } = await getAidCid(client, bvid);
  if (!aid) fail("拿不到 aid");
  out(await client.video.like({ aid, like: true }));
}

async function coin(bvid, multiply) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  const { aid } = await getAidCid(client, bvid);
  if (!aid) fail("拿不到 aid");
  out(await client.video.coin({ aid, multiply: multiply === "2" ? "2" : "1" }));
}

async function three(bvid) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  const { aid } = await getAidCid(client, bvid);
  if (!aid) fail("拿不到 aid");
  out(await client.video.likeCoinShare({ aid }));
}

async function share(bvid) {
  if (!bvid) fail("要一个 BV 号");
  const client = await getClient();
  const { aid } = await getAidCid(client, bvid);
  if (!aid) fail("拿不到 aid");
  out(await client.video.addShare({ aid }));
}

async function replyadd(bvid, content) {
  if (!bvid || !content) fail("用法：bili replyadd <BV> <评论内容>");
  const client = await getClient();
  const { aid } = await getAidCid(client, bvid);
  if (!aid) fail("拿不到 aid");
  out(await client.reply.add({ oid: aid, type: 1, message: content, plat: 1 }));
}

const [command, ...args] = process.argv.slice(2);

try {
  switch (command) {
    case "qrcode":
      await qrcode();
      break;
    case "login":
      await login(args[0]);
      break;
    case "up":
      await up(args[0]);
      break;
    case "search":
      await search(args.join(" "));
      break;
    case "video":
      await video(args[0]);
      break;
    case "subtitle":
      await subtitle(args[0]);
      break;
    case "danmaku":
      await danmaku(args[0]);
      break;
    case "download":
      await download(args[0], args[1], args[2]);
      break;
    case "live":
      await live(args[0]);
      break;
    case "comment":
      await comment(args[0], args[1]);
      break;
    case "asr":
      await asr(args[0]);
      break;
    case "toview":
      await toview();
      break;
    case "me":
      await me();
      break;
    case "favlist":
      await favlist();
      break;
    case "collections":
      await collections(args[0]);
      break;
    case "seriesvideos":
      await seriesvideos(args[0], args[1]);
      break;
    case "seasons":
      await seasons(args[0], args[1]);
      break;
    case "pages":
      await pages(args[0]);
      break;
    case "playurl":
      await playurl(args[0]);
      break;
    case "playerinfo":
      await playerinfo(args[0]);
      break;
    case "desc":
      await desc(args[0]);
      break;
    case "liveguard":
      await liveguard(args[0]);
      break;
    case "liveslice":
      await liveslice(args[0]);
      break;
    case "searchtype":
      await searchtype(args[0], args[1]);
      break;
    case "areas":
      await areas();
      break;
    case "replycount":
      await replycount(args[0]);
      break;
    case "like":
      await like(args[0]);
      break;
    case "coin":
      await coin(args[0], args[1]);
      break;
    case "three":
      await three(args[0]);
      break;
    case "share":
      await share(args[0]);
      break;
    case "replyadd":
      await replyadd(args[0], args.slice(1).join(" "));
      break;
    case undefined:
      err("用法：bili qrcode | login [auth_code] | up <uid> | search <词> | video <BV> | subtitle <BV> | danmaku <BV> | download <BV> | live <房间号> | comment <BV> | asr <音频> | toview");
      process.exit(2);
      break;
    default:
      fail(`未知子命令：${command}`);
  }
} catch (e) {
  fail(e instanceof Error ? e.message : String(e));
}
