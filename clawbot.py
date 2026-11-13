# -*- coding: utf-8 -*-
"""微信 ClawBot 通知通道（官方 iLink 协议）。

设计目标：扫码绑定即可用，不注册任何第三方推送平台、不填写 API Key、
不新增 Python 依赖（复用项目已有的 requests）、凭证只存本机 SQLite。

主要流程：
1. 扫码：get_bot_qrcode -> 长轮询 get_qrcode_status -> 拿到 bot_token / ilink_user_id
2. 保活：后台长轮询 getupdates，持续收集 context_token
3. 推送：POST /ilink/bot/sendmessage 把到货提醒发进微信 ClawBot 对话

已知限制（微信侧）：bot 主动下发有 24 小时 / 10 条保活窗口，需要用户
在 24 小时内给 ClawBot 发过一条消息。窗口过期时本模块会返回明确提示，
由上层用邮件 / 系统通知兜底。
"""
import base64
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import quote

import requests

import database as db

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
# 与官方插件包 @tencent-weixin/openclaw-weixin 的协议保持一致
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = "132106"      # 2.4.10 -> (2<<16)|(4<<8)|10
CHANNEL_VERSION = "cigar-monitor-1.2.0"
BOT_TYPE = "3"
LOGIN_TTL = 5 * 60                        # 单次扫码会话有效期（秒）
TOKEN_POOL_SIZE = 20
POLL_TIMEOUT = 40                         # get_qrcode_status / getupdates 长轮询
API_TIMEOUT = 15

# 进行中的扫码会话（仅内存，进程重启后重新扫码即可）
_sessions = {}
_sessions_lock = threading.Lock()
_keepalive_started = False
# 会话状态读写锁：长轮询可能持有一份旧 state 数十秒，若直接整体回写，
# 会覆盖掉这期间其他路径刚收割的 token，或在解绑后把旧状态写回来。
_state_lock = threading.Lock()


# ---------------- 基础工具 ----------------
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json_load(raw, default):
    if not raw:
        return default
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else default
    except (ValueError, TypeError):
        return default


def _headers(token=None):
    uin = base64.b64encode(str(int.from_bytes(os.urandom(4), "little")).encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": uin,
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": ILINK_APP_CLIENT_VERSION,
    }
    if token:
        headers["Authorization"] = "Bearer %s" % token
    return headers


def _parse_response(resp):
    try:
        return resp.json()
    except ValueError:
        return {"_http": resp.status_code, "errmsg": (resp.text or "")[:200]}


def _post(base_url, path, payload, token=None, timeout=API_TIMEOUT):
    url = (base_url or DEFAULT_BASE_URL).rstrip("/") + path
    resp = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         headers=_headers(token), timeout=timeout)
    if resp.status_code >= 400:
        return {"_http": resp.status_code, "errmsg": (resp.text or "")[:200]}
    return _parse_response(resp)


def _get(base_url, path, timeout=POLL_TIMEOUT):
    url = (base_url or DEFAULT_BASE_URL).rstrip("/") + path
    resp = requests.get(url, headers=_headers(), timeout=timeout)
    if resp.status_code >= 400:
        return {"_http": resp.status_code, "errmsg": (resp.text or "")[:200]}
    return _parse_response(resp)


def _error_text(res):
    if not isinstance(res, dict):
        return "接口无响应"
    if res.get("_error"):
        return str(res["_error"])
    code = res.get("ret") or res.get("errcode") or res.get("_http")
    msg = res.get("errmsg") or res.get("message") or ""
    return ("[%s] %s" % (code, msg)).strip() if code else (msg or "未知错误")


# ---------------- 凭证与状态（存本地 SQLite settings 表） ----------------
def get_credential(settings=None):
    settings = settings if settings is not None else db.get_settings()
    return _json_load(settings.get("clawbot_cred"), {})


def get_state(settings=None):
    settings = settings if settings is not None else db.get_settings()
    state = _json_load(settings.get("clawbot_state"), {})
    state.setdefault("tokens", [])
    state.setdefault("buf", "")
    return state


def _save_binding(cred):
    """写入新凭证并清空会话状态（锁内原子完成，避免与收割线程交错）。"""
    with _state_lock:
        db.save_settings({
            "clawbot_cred": json.dumps(cred, ensure_ascii=False),
            "clawbot_state": json.dumps({"tokens": [], "buf": "", "last_token_at": ""}),
        })


def save_state(state):
    db.save_settings({"clawbot_state": json.dumps(state, ensure_ascii=False)})


def clear_binding():
    with _state_lock:
        db.save_settings({"clawbot_cred": "", "clawbot_state": ""})


def status():
    """供设置页展示的绑定/保活状态，不发起任何网络请求。"""
    settings = db.get_settings()
    cred = get_credential(settings)
    state = get_state(settings)
    if not cred.get("bot_token"):
        return {"bound": False, "ready": False, "enabled": False,
                "last_token_at": "", "token_count": 0, "bound_at": "", "tip": "尚未绑定"}
    token_count = len(state.get("tokens") or [])
    last_at = state.get("last_token_at") or ""
    if token_count:
        tip = "通道就绪，有货时会自动推送到微信"
    else:
        tip = "还差一步：请在微信里给 ClawBot 发任意一条消息，界面会自动变为「通道就绪」"
    return {
        "bound": True,
        "ready": bool(token_count),
        "enabled": True,
        "account_id": _mask(cred.get("account_id", "")),
        "bound_at": cred.get("bound_at", ""),
        "last_token_at": last_at,
        "token_count": token_count,
        "tip": tip,
    }


def _mask(value):
    value = str(value or "")
    return value[:6] + "..." + value[-4:] if len(value) > 14 else value


# ---------------- 扫码绑定 ----------------
def _fetch_qrcode():
    res = _post(DEFAULT_BASE_URL, "/ilink/bot/get_bot_qrcode?bot_type=%s" % BOT_TYPE,
                {"local_token_list": []})
    qrcode = res.get("qrcode")
    qr_url = res.get("qrcode_img_content")
    if not qrcode or not qr_url:
        raise RuntimeError("获取二维码失败：%s" % _error_text(res))
    return qrcode, qr_url


def start_login():
    """开始一次扫码绑定，返回二维码内容与会话 id。"""
    qrcode, qr_url = _fetch_qrcode()
    sid = uuid.uuid4().hex[:12]
    with _sessions_lock:
        # 同时只保留一个有效会话，避免重复扫码互相顶掉
        for old in list(_sessions):
            _sessions[old]["alive"] = False
        _sessions[sid] = {
            "alive": True, "qrcode": qrcode, "qr_url": qr_url,
            "base_url": DEFAULT_BASE_URL, "status": "wait",
            "message": "请用手机微信扫描二维码", "verify_code": "",
            "deadline": time.time() + LOGIN_TTL, "refresh_count": 0,
        }
        threading.Thread(target=_poll_login, args=(sid,), daemon=True).start()
    return {"session": sid, "qr_url": qr_url, "status": "wait",
            "message": "请用手机微信扫描二维码"}


def _poll_login(sid):
    while True:
        with _sessions_lock:
            s = _sessions.get(sid)
            if not s or not s["alive"] or time.time() > s["deadline"]:
                if s:
                    s["status"] = "timeout"
                    s["message"] = "二维码已超时，请重新扫码"
                return
            qrcode, base_url = s["qrcode"], s["base_url"]
            verify_code = s["verify_code"]
        path = "/ilink/bot/get_qrcode_status?qrcode=%s" % quote(qrcode, safe="")
        if verify_code:
            path += "&verify_code=%s" % quote(verify_code, safe="")
        try:
            res = _get(base_url, path)
        except Exception as e:
            time.sleep(1.5)
            continue
        step = res.get("status") if isinstance(res, dict) else None
        with _sessions_lock:
            s = _sessions.get(sid)
            if not s or not s["alive"]:
                return
            if step == "wait":
                pass
            elif step == "scaned":
                s["status"] = "scaned"
                s["message"] = "已扫码，正在微信端确认..."
                s["verify_code"] = ""
            elif step == "need_verifycode":
                s["status"] = "need_verifycode"
                s["message"] = "请在下方输入手机微信显示的配对数字"
            elif step == "scaned_but_redirect":
                host = res.get("redirect_host")
                if host:
                    s["base_url"] = "https://%s" % host
            elif step == "expired":
                s["refresh_count"] += 1
                if s["refresh_count"] > 3:
                    s["status"] = "timeout"
                    s["message"] = "二维码多次失效，请重新扫码"
                    return
                try:
                    qrcode, qr_url = _fetch_qrcode()
                    s["qrcode"], s["qr_url"] = qrcode, qr_url
                    s["status"] = "wait"
                    s["message"] = "二维码已刷新，请重新扫描"
                except Exception:
                    pass
            elif step == "verify_code_blocked":
                s["status"] = "need_verifycode"
                s["message"] = "配对码错误次数过多，请重新扫码后再试"
                s["verify_code"] = ""
            elif step == "binded_redirect":
                s["status"] = "error"
                s["message"] = "该微信已连接过此机器人，可直接在微信里发消息测试"
            elif step == "confirmed":
                if not res.get("bot_token") or not res.get("ilink_user_id"):
                    s["status"] = "error"
                    s["message"] = "绑定失败：服务端未返回完整凭证"
                    return
                _save_binding({
                    "bot_token": res["bot_token"],
                    "user_id": res["ilink_user_id"],
                    "account_id": res.get("ilink_bot_id", ""),
                    "base_url": res.get("baseurl") or s["base_url"],
                    "bound_at": _now(),
                })
                s["status"] = "confirmed"
                s["message"] = "绑定成功，请在微信里给 ClawBot 发一条消息激活推送"
                return
        time.sleep(0.6)


def login_status(sid):
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return {"status": "timeout", "message": "会话不存在或已过期，请重新扫码"}
        return {"status": s["status"], "message": s["message"],
                "qr_url": s["qr_url"], "expired": time.time() > s["deadline"]}


def submit_verify_code(sid, code):
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s or not s["alive"]:
            return False
        s["verify_code"] = str(code or "").strip()
        s["message"] = "配对码已提交，正在验证..."
    return True


# ---------------- 会话保活（后台长轮询 getupdates） ----------------
def _fetch_updates(cred, buf, timeout=POLL_TIMEOUT):
    """纯网络请求（长轮询），不碰数据库，因此可以在锁外等待数十秒。"""
    return _post(cred.get("base_url"), "/ilink/bot/getupdates", {
        "get_updates_buf": buf or "",
        "base_info": {"channel_version": CHANNEL_VERSION},
    }, token=cred["bot_token"], timeout=timeout)


def _merge_updates(res, token_used=None):
    """把一次 getupdates 响应合并进**最新**状态（锁内）。

    不能拿着请求前的旧 state 整体回写：那会覆盖掉这期间其他路径收割的 token。
    若等待期间已解绑或换了绑定，直接丢弃本次结果，不回写。
    返回当前可用 token 数。
    """
    with _state_lock:
        settings = db.get_settings()
        cred = get_credential(settings)
        if not cred.get("bot_token"):
            return 0
        state = get_state(settings)
        if token_used and cred.get("bot_token") != token_used:
            return len(state.get("tokens") or [])
        if isinstance(res, dict):
            pool = list(state.get("tokens") or [])
            for m in res.get("msgs") or []:
                tok = m.get("context_token") if isinstance(m, dict) else None
                if tok and tok not in pool:
                    pool.append(tok)
            if pool:
                state["last_token_at"] = _now()
            state["tokens"] = pool[-TOKEN_POOL_SIZE:]
            if res.get("get_updates_buf"):
                state["buf"] = res["get_updates_buf"]
            state["last_ret"] = res.get("ret", 0)
        state["last_poll"] = _now()
        save_state(state)
        return len(state.get("tokens") or [])


def _keepalive_loop():
    while True:
        settings = db.get_settings()
        cred = get_credential(settings)
        if not cred.get("bot_token"):
            time.sleep(5)          # 未绑定：轻量轮询，绑定后 5 秒内即开始保活
            continue
        try:
            res = _fetch_updates(cred, get_state(settings).get("buf"), timeout=POLL_TIMEOUT)
            _merge_updates(res, token_used=cred["bot_token"])
            ret = res.get("ret") if isinstance(res, dict) else None
            # 会话异常（-14 过期、-2 未激活等）时退避，避免每秒猛刷接口；
            # 用户在微信里重新发一条消息后会自动恢复。
            time.sleep(15 if ret not in (0, None) else 1)
        except requests.exceptions.ReadTimeout:
            # 长轮询超时是正常情况（这段时间没有新消息），立刻进入下一轮，
            # 不要 sleep，否则用户发消息后要等很久才会被收割。
            continue
        except Exception:
            time.sleep(8)


def start_keepalive():
    """由 app 启动时调用一次，持续维护 context_token。"""
    global _keepalive_started
    if _keepalive_started:
        return
    _keepalive_started = True
    threading.Thread(target=_keepalive_loop, daemon=True).start()


def refresh_tokens_once():
    """手动刷新一次（测试按钮）。

    getupdates 是长轮询，短超时读不到属于正常；后台保活线程会持续收割，
    所以超时后再读一次数据库，以后台线程的结果为准。
    """
    settings = db.get_settings()
    cred = get_credential(settings)
    if not cred.get("bot_token"):
        return 0
    try:
        res = _fetch_updates(cred, get_state(settings).get("buf"), timeout=5)
        return _merge_updates(res, token_used=cred["bot_token"])
    except Exception:
        return len(get_state().get("tokens") or [])


# ---------------- 消息发送 ----------------
def stock_message(product):
    """生成推送到微信的纯文本（链接在微信中自动可点）。"""
    from notifier import stock_greeting
    name = (product.get("name") or product.get("url") or "").strip()
    url = (product.get("url") or "").strip()
    checked = (product.get("last_checked") or _now()).strip()
    greet = stock_greeting(product)
    lines = [
        "【雪茄到货提醒】" + greet,
        "",
        "商品：" + name,
        "状态：有货 In Stock",
        "检查时间：" + checked,
    ]
    if url:
        lines.append("链接：" + url)
    lines += ["", "本地雪茄库存监控 · 自动推送"]
    return "\n".join(lines)


def test_message():
    return "\n".join([
        "【测试】雪茄库存监控",
        "",
        "如果你在微信里看到这条消息，说明 ClawBot 通知已配置成功。",
        "有货时会自动推送商品名与直达链接。",
        "",
        _now(),
    ])


def _send_once(cred, text, context_token):
    msg = {
        "from_user_id": "",
        "to_user_id": cred["user_id"],
        "client_id": "cigar-monitor-%s" % uuid.uuid4().hex,
        "message_type": 2,
        "message_state": 2,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }
    if context_token:
        msg["context_token"] = context_token
    payload = {"msg": msg, "base_info": {"channel_version": CHANNEL_VERSION}}
    return _post(cred.get("base_url"), "/ilink/bot/sendmessage", payload,
                 token=cred["bot_token"], timeout=API_TIMEOUT)


def _friendly_error(err, had_token):
    """把 iLink 原始错误码翻译成用户能照做的动作。"""
    low = (err or "").lower()
    if not had_token or "prepare failed" in low or "[-2]" in err:
        return ("会话还未激活：请在微信里给 ClawBot 发任意一条消息，"
                "等界面显示「通道就绪」后重试；有货提醒仍会由邮件与系统通知正常发出")
    if re.search(r"-14|session|timeout|expire", low):
        return "推送会话已过期，请在微信里给 ClawBot 发任意一条消息刷新后重试"
    return "ClawBot 推送失败：%s" % (err or "未知原因")


def send_text(text, auto_refresh=True):
    """发送一条微信消息，返回 (ok, message)。"""
    settings = db.get_settings()
    cred = get_credential(settings)
    if not cred.get("bot_token"):
        return False, "尚未绑定微信 ClawBot"
    if not cred.get("user_id"):
        return False, "绑定凭证不完整，请重新扫码"

    state = get_state(settings)
    tokens = list(reversed(state.get("tokens") or []))
    if not tokens and auto_refresh:
        try:
            res = _fetch_updates(cred, state.get("buf"), timeout=5)
            _merge_updates(res, token_used=cred["bot_token"])
        except Exception:
            pass
        tokens = list(reversed(get_state().get("tokens") or []))
    if not tokens:
        # 刚绑定、用户还没在微信里给 bot 发过消息时没有 context_token，
        # iLink 必然返回 -2 prepare failed。不再发注定失败的请求，
        # 直接给出可执行的指引，由邮件 / 系统通知兜底。
        return False, _friendly_error("", False)

    last_err = ""
    for token in tokens[:5]:
        try:
            res = _send_once(cred, text, token)
        except Exception as e:
            last_err = str(e)
            continue
        success = bool(res) and (
            bool(res.get("message_id"))
            or (res.get("ret") in (0, None) and not res.get("errmsg")
                and not res.get("_http") and not res.get("_error"))
        )
        if success:
            return True, "已送达微信 ClawBot"
        last_err = _error_text(res)
        if re.search(r"-14|session|timeout|expire", last_err, re.I):
            break

    return False, _friendly_error(last_err, True)


def send_stock_alert(product):
    return send_text(stock_message(product))
