#!/usr/bin/env python3
"""vivo 健康数据采集库（kg-vivo-health skill 核心）

能力：
  - 纯命令行登录 vivo 账号（smsLogin/p1 发码 + p2 验证）拿 token，无需模拟器
  - 拉取健康数据（dashboard：步数/睡眠/心率/血氧/压力/运动）
  - 按天落盘到 <vault>/daily/YYYY-MM-DD/vivo-health.json
  - token 持久化（token.json），过期自动提示重新登录

sign 算法逆向自 libvivo_account_wave.so（已用 5 组 native 对照 + 真实请求验证）：
  MD5(361字节前缀 + 排序参数值冒号拼接) → hex 反转 → 两段循环累加 → "2|"+值

用法：
  import collect_vivo_health as vh
  vh.login(phone, code, random_num)   # 或 vh.send_code(phone) 先发码
  data = vh.fetch_dashboard(date)
"""
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request
import uuid

# ---------------------------------------------------------------- 路径

HERE = pathlib.Path(os.path.abspath(__file__)).parent
# 数据目录：可用 VIVO_HEALTH_DATA 覆盖（管家/skill 各自指定）
DEFAULT_DATA_DIR = pathlib.Path(os.environ.get("VIVO_HEALTH_DATA", str(HERE / "data")))
PREFIX_FILE = HERE / "wave_prefix.bin"        # sign 前缀（361 字节，从 so 提取）

BASE = "https://usrsys.vivo.com.cn"           # 账号服务
HEALTH_BASE = "https://health.vivo.com"       # 健康数据服务

# 通用参数（从 App 真实请求抓取）
VER_CODE = "sysapk_6.2.4.0"
VER_CODE_INT = "6240"
SDK_VER_CODE = "SysAccountSDK_1.1.1.2"
EC_VALUE = "0123456789012345678901234567890123456789012345678901"
IMEI = "123456789012345"
MODEL = "sdk_gphone64_arm64"
ANDROID_VER = "14"
FROM = "com.vivo.health_SysAccountSDK"
DETAIL = "vivo_account_manager"


# ---------------------------------------------------------------- sign

def load_prefix():
    return PREFIX_FILE.read_bytes()


def str_to_int(c):
    c = ord(c)
    if 0x61 <= c <= 0x66:
        return c - 0x57
    return c - 0x30


def wave_sign_value(inp):
    """native waveStringNet 算法（已 100% 验证）"""
    prefix = load_prefix()
    digest = hashlib.md5(prefix + inp.encode()).digest()
    rev = digest.hex()[::-1]
    chars17 = rev[7:24]
    x21 = 0
    for i in range(7):
        x21 = (x21 << 4) + str_to_int(chars17[i])
    x19 = 0
    for i in range(7, 17):
        x19 = (x19 << 4) + str_to_int(chars17[i])
    return (x19 + x21) & 0xFFFFFFFF


def wave_sign(param_values):
    """完整 sign：排序值 → 冒号拼接 → native 算法 → "2|" + 值"""
    sorted_vals = sorted(param_values)
    joined = "".join(":" + v for v in sorted_vals)
    return "2|" + str(wave_sign_value(joined))


# ---------------------------------------------------------------- token

def token_path():
    return DEFAULT_DATA_DIR / "token.json"


def save_token(tok):
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    token_path().write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")


def load_token():
    p = token_path()
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 登录 API

def build_common_params():
    ts = str(int(time.time() * 1000))
    return {
        "deviceOrigin": "2", "imei": IMEI, "ec": EC_VALUE, "model": MODEL,
        "timeStamp": ts, "androidVer": ANDROID_VER, "from": FROM,
        "nounce": str(uuid.uuid4()), "locale": "en_US", "countryCode": "CN",
        "verCode": VER_CODE, "verCodeInt": VER_CODE_INT,
        "sdkVerCode": SDK_VER_CODE, "sdkVerCodeInt": "1112",
        "apkVerCodeInt": "-1", "isBarrierFree": "0", "cs": "0",
        "detail": DETAIL, "sliderVersionType": "2",
        "oaid": "", "vaid": "", "aaid": "",
    }


def make_request(path, params):
    all_params = build_common_params()
    all_params.update(params)
    sign = wave_sign(list(all_params.values()))
    all_params["s"] = sign
    body = urllib.parse.urlencode(all_params).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "okhttp/3.12.1")
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "error": str(e)}
    except Exception as e:
        return {"code": -1, "error": str(e)}


def send_code(phone):
    """smsLogin/p1：发验证码。成功返回 randomNum。"""
    r = make_request("/usrprd/v5/smsLogin/p1", {
        "phone": phone, "areaCode": "86", "countryCode": "CN",
    })
    if r.get("code") == 0:
        return r, r.get("data", {}).get("randomNum")
    return r, None


def verify_code(phone, code, random_num):
    """smsLogin/p2：验证码登录。成功返回含 token 的完整响应。"""
    r = make_request("/usrprd/v5/smsLogin/p2", {
        "phone": phone, "code": code, "areaCode": "86", "countryCode": "CN",
        "randomNum": random_num, "bizCode": "BC0061", "supportReplay": "1",
    })
    if r.get("code") == 0 and r.get("data"):
        d = r["data"]
        save_token({
            "openId": d.get("openid"),
            "token": d.get("vivotoken"),
            "rawToken": d.get("authtoken"),
            "uuid": d.get("uuid"),
            "sk": d.get("sk"),
            "phone": phone,
            "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "via": "pure-cli-login",
        })
    return r


# ---------------------------------------------------------------- 健康数据 API

def health_headers(tok):
    ts = str(int(time.time() * 1000))
    return {
        "timestamp": ts,
        "appVersion": "65106",
        "androidVer": ANDROID_VER,
        "openId": tok.get("openId", ""),
        "appName": "health",
        "appVer": "65106",
        "platform": "android",
        "token": tok.get("token", ""),
        "app-locale": "zh_CN",
        "vendor": MODEL,
        "model": MODEL,
        "brand": "google",
        "Request-Id": ts,
        "Connection": "close",
        "User-Agent": "okhttp/3.12.1",
    }


def fetch_dashboard(date=None, tok=None):
    """拉取指定日期（默认今天）的健康 dashboard。"""
    tok = tok or load_token()
    if not tok:
        return {"code": -1, "error": "no token; run login first"}
    date = date or time.strftime("%Y-%m-%d")
    url = f"{HEALTH_BASE}/v2/dashboard?date={date}&maxPidDomestic=7&maxPidOversea=7"
    req = urllib.request.Request(url, headers=health_headers(tok))
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "error": str(e)}
    except Exception as e:
        return {"code": -1, "error": str(e)}


# ---------------------------------------------------------------- 落盘

def save_daily(data, date=None, vault=None):
    """落盘到 <vault>/daily/YYYY-MM-DD/vivo-health.json"""
    date = date or time.strftime("%Y-%m-%d")
    if vault is None:
        # 复用管家的 resolve_vault（KG_VAULT → 配置 → 报错）
        try:
            sys.path.insert(0, str(pathlib.Path(__file__).parent))
            from resolve_vault import resolve_vault
            vault = resolve_vault()
        except Exception:
            vault = None
    if not vault:
        # 回退到本 skill 数据目录
        daily = DEFAULT_DATA_DIR / "daily" / date
    else:
        daily = pathlib.Path(vault) / "daily" / date
    daily.mkdir(parents=True, exist_ok=True)
    out = daily / "vivo-health.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def summarize(data):
    """提取人类可读摘要（给 agent 的简洁字段）"""
    d = data.get("data") or {}
    out = {"date": None, "steps": None, "distance_m": None, "calories": None,
           "heart_rate": None, "spo2": None, "stress": None,
           "sleep_hours": None, "sleep_score": None, "sleep_detail": None}
    if d.get("step"): out["steps"] = d["step"].get("v")
    if d.get("distance"): out["distance_m"] = d["distance"].get("v")
    if d.get("calorie"): out["calories"] = d["calorie"].get("v")
    if d.get("rate"): out["heart_rate"] = d["rate"].get("v")
    if d.get("saO2"): out["spo2"] = d["saO2"].get("v")
    if d.get("pressure"): out["stress"] = d["pressure"].get("v")
    sleep = d.get("sleep") or {}
    if sleep.get("v"): out["sleep_hours"] = round(sleep["v"] / 3600000, 2)
    detail = d.get("sleepDetail") or []
    if detail:
        x = detail[0]
        out["sleep_score"] = x.get("score")
        total = x.get("total") or {}
        if total.get("duration"):
            out["sleep_detail"] = {
                "duration_ms": total.get("duration"),
                "start": total.get("startTime"),
                "end": total.get("endTime"),
            }
    return out
