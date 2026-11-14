import concurrent.futures
import datetime
import http.client
import json
import random
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

AID = "845221"
APP_NAME = "pinedrama"
VERSION_CODE = "2024701040"
VERSION_NAME = "47.1.4"
DEFAULT_DEVICE_ID = "7693098646124299783"
DEFAULT_IID = "7696004969955362580"

API_HOSTS = [
    "api-h2.tiktokv.com",
    "api16-normal-c-alisg.tiktokv.com",
]

USER_AGENT = (
    f"com.ss.android.ttmd.video/{VERSION_CODE} "
    "(Linux; U; Android 13; vi_VN; Pixel; Build/TQ3A.230805.001; "
    "Cronet/TTNetVersion:b478d693 2024-07-18 QuicVersion:47946d2a 2020-10-14)"
)

VIDEO_PATH_RE = re.compile(r"/video/(\d{15,22})")
VIDEO_QUERY_RE = re.compile(r"(?:aweme_id|item_id|video_id)=(\d{15,22})")
BARE_ID_RE = re.compile(r"^(\d{15,22})$")
URL_EXTRACT_RE = re.compile(r"https?://[^\s\"'<>]+")
QUALITY_RE = re.compile(r"_(1[0-9]{3}|[1-9][0-9]{2})p_")
STAMP_RE = re.compile(r"/([0-9a-fA-F]{8})/")

_tls = threading.local()
DEVICE_ID, INSTALL_ID = DEFAULT_DEVICE_ID, DEFAULT_IID


def common_query(lang="vi", locale="vi-VN", region="VN", did=None, iid=None):
    use_did = did or DEVICE_ID
    use_iid = iid or INSTALL_ID
    return (
        f"aid={AID}&app_name={APP_NAME}&version_code={VERSION_CODE}&version_name={VERSION_NAME}"
        f"&manifest_version_code={VERSION_CODE}&update_version_code={VERSION_CODE}&ab_version={VERSION_NAME}"
        f"&device_platform=android&os=android&os_api=33&os_version=13"
        f"&device_type=Pixel+7+Pro&device_brand=google&resolution=1080*2400&dpi=420"
        f"&ac=wifi&channel=googleplay&ssmix=a"
        f"&device_id={use_did}&iid={use_iid}"
        f"&language={lang}&app_language={lang}&locale={locale}"
        f"&region={region}&sys_region={region}&carrier_region={region}&current_region={region}&op_region={region}&residence={region}"
        f"&is_play_h265=1&bytevc1=1"
    )


def _get_conn(host):
    conns = getattr(_tls, "conns", None)
    if conns is None:
        conns = {}
        _tls.conns = conns
    conn = conns.get(host)
    if conn is None:
        conn = http.client.HTTPSConnection(host, timeout=10)
        conns[host] = conn
    return conn


def _drop_conn(host):
    conns = getattr(_tls, "conns", None)
    if conns and host in conns:
        try:
            conns[host].close()
        except Exception:
            pass
        conns.pop(host, None)


def extract_clean_input(raw_text):
    if not raw_text:
        return ""
    raw_text = raw_text.strip()
    m_url = URL_EXTRACT_RE.search(raw_text)
    if m_url:
        return m_url.group(0)
    return raw_text


def find_video_id(text):
    if not text:
        return None
    text = text.strip()
    m = BARE_ID_RE.match(text)
    if m:
        return m.group(1)
    m = VIDEO_PATH_RE.search(text)
    if m:
        return m.group(1)
    m = VIDEO_QUERY_RE.search(text)
    if m:
        return m.group(1)
    return None


def resolve_share_url(raw_input):
    url = extract_clean_input(raw_input)
    vid = find_video_id(url)
    if vid:
        return url, vid

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    cur = url
    for _ in range(8):
        req = urllib.request.Request(
            cur,
            headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"
            },
        )
        try:
            resp = opener.open(req, timeout=10)
            final_url = resp.geturl()
            body = resp.read(32768).decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") or e.headers.get("location")
            if loc:
                cur = urllib.parse.urljoin(cur, loc)
                vid = find_video_id(cur)
                if vid:
                    return cur, vid
                continue
            body = e.read(32768).decode("utf-8", errors="ignore") if e.fp else ""
            final_url = cur
        vid = find_video_id(final_url) or find_video_id(body)
        if vid:
            return final_url, vid
        break
    return cur, None


def api_video_by_ids(video_ids, seed=0):
    ids_int = [int(x) for x in video_ids]
    payload = json.dumps({"video_ids": ids_int}).encode("utf-8")

    for attempt in range(8):
        host = API_HOSTS[(seed + attempt) % len(API_HOSTS)]
        if attempt == 0 and seed == 0:
            q = common_query()
        else:
            rdid = str(random.randint(7300000000000000000, 7699999999999999999))
            riid = str(random.randint(7300000000000000000, 7699999999999999999))
            q = common_query(did=rdid, iid=riid)
        path = f"/tiktok/v1/paid_content/mini_drama/video_by_ids?{q}"
        try:
            conn = _get_conn(host)
            conn.request(
                "POST",
                path,
                body=payload,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "User-Agent": USER_AGENT,
                    "Connection": "keep-alive",
                },
            )
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status == 200:
                data = json.loads(raw.decode("utf-8"))
                if data.get("status_code") == 0 and data.get("video_list") is not None:
                    return data
            _drop_conn(host)
        except Exception:
            _drop_conn(host)
        time.sleep(0.08 * (attempt + 1))
    return None


def api_episode_panel(collection_id):
    path = f"/tiktok/md/collection/episode_panel/v1/?collection_id={collection_id}&{common_query()}"
    for attempt in range(6):
        host = API_HOSTS[attempt % len(API_HOSTS)]
        try:
            conn = _get_conn(host)
            conn.request(
                "GET",
                path,
                headers={"User-Agent": USER_AGENT, "Connection": "keep-alive"},
            )
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status == 200:
                data = json.loads(raw.decode("utf-8"))
                if data.get("episode_list") is not None:
                    return data
            _drop_conn(host)
        except Exception:
            _drop_conn(host)
        time.sleep(0.1 * (attempt + 1))
    return None


def _quality_rank(url_key, height):
    if url_key:
        m = QUALITY_RE.search(url_key)
        if m:
            return int(m.group(1))
    if height >= 1600:
        return 1080
    if height >= 1200:
        return 720
    if height >= 900:
        return 540
    if height >= 500:
        return 360
    return height if height > 0 else 0


def _quality_name(rank):
    if rank >= 1080:
        return "1080p"
    if rank >= 720:
        return "720p"
    if rank >= 540:
        return "540p"
    if rank >= 480:
        return "480p"
    if rank >= 360:
        return "360p"
    return f"{rank}p" if rank > 0 else "HD"


def _expires_at(url):
    if not url:
        return None
    for m in STAMP_RE.finditer(url):
        ts = int(m.group(1), 16)
        if 0x6553F100 < ts < 0x83215600:
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def _addr_variant(play_addr, source, is_bytevc1, bitrate):
    if not isinstance(play_addr, dict):
        return None
    url_list = play_addr.get("url_list") or []
    if not url_list:
        return None
    url_key = str(play_addr.get("url_key") or "")
    height = int(play_addr.get("height") or 0)
    urls = []
    api_url = None
    for u in url_list:
        if not u:
            continue
        if "/aweme/v1/play/" in u:
            if api_url is None:
                api_url = u
        else:
            urls.append(u)
    if not urls and not api_url:
        return None
    rank = _quality_rank(url_key, height)
    codec = "h265" if (is_bytevc1 or "bytevc1" in url_key) else "h264"
    sample_url = urls[0] if urls else api_url
    return {
        "source": source,
        "urls": urls,
        "api_url": api_url,
        "quality": _quality_name(rank),
        "codec": codec,
        "bitrate": bitrate if bitrate > 0 else None,
        "expires_at": _expires_at(sample_url),
        "_q": rank,
    }


def _parse_video_item(vitem, only_best=False, episode_num=None):
    out = {"variants": [], "error": None}
    if episode_num is not None and episode_num > 0:
        out["episode"] = episode_num
    if not isinstance(vitem, dict):
        out["success"] = False
        out["error"] = "no raw video body"
        return out

    cid = str(vitem.get("collection_id") or "")
    out["collection_id"] = cid
    video_wrapper = vitem.get("video") or {}
    aweme = video_wrapper.get("aweme") if isinstance(video_wrapper, dict) else None
    if not isinstance(aweme, dict):
        out["success"] = False
        out["video_id"] = ""
        out["error"] = "no video"
        return out

    out["video_id"] = str(aweme.get("aweme_id") or "")
    out["desc"] = str(aweme.get("desc") or "")
    vobj = aweme.get("video") or {}
    cover_obj = vobj.get("cover") or vobj.get("origin_cover") or {}
    cover_list = cover_obj.get("url_list") or []
    out["cover"] = cover_list[0] if cover_list else ""

    variants = []
    if isinstance(vobj, dict):
        bit_rates = vobj.get("bit_rate") or []
        for br in bit_rates:
            if not isinstance(br, dict):
                continue
            pa = br.get("play_addr")
            is_bvc1 = int(br.get("is_bytevc1") or 0) == 1
            bval = int(br.get("bit_rate") or 0)
            v = _addr_variant(pa, "play", is_bvc1, bval)
            if v:
                variants.append(v)
        variants.sort(key=lambda x: (x.get("_q") or 0, x.get("bitrate") or 0), reverse=True)
        if only_best and variants:
            variants = variants[:1]
        for v in variants:
            v.pop("_q", None)

        if not variants:
            pa = vobj.get("play_addr")
            v = _addr_variant(pa, "play", False, 0)
            if v:
                v.pop("_q", None)
                variants.append(v)

    out["variants"] = variants
    out["success"] = len(variants) > 0
    if not variants:
        out["error"] = "no play url"
    return out


def fetch_video_one(url_or_id):
    _, vid = resolve_share_url(url_or_id)
    if not vid:
        raise ValueError("Không tìm thấy ID video từ đường link bạn dán.")
    data = api_video_by_ids([vid])
    vlist = (data or {}).get("video_list") or []
    if not vlist:
        return [{"variants": [], "error": "Không lấy được dữ liệu video (thử lại sau vài giây)", "success": False}]
    return [_parse_video_item(vlist[0], only_best=False)]


def fetch_full_series(url_or_id, max_workers=10):
    _, vid = resolve_share_url(url_or_id)
    if not vid:
        raise ValueError("Không tìm thấy ID video từ đường link bạn dán.")

    first = api_video_by_ids([vid])
    vlist = (first or {}).get("video_list") or []
    if not vlist:
        raise RuntimeError("Không lấy được thông tin tập gốc.")

    cid = str(vlist[0].get("collection_id") or "")
    if not cid:
        return [_parse_video_item(vlist[0], only_best=False, episode_num=1)]

    panel = api_episode_panel(cid)
    ep_list = (panel or {}).get("episode_list") or []
    if not ep_list:
        return [_parse_video_item(vlist[0], only_best=False, episode_num=1)]

    episodes = []
    for idx, ep in enumerate(ep_list):
        if not isinstance(ep, dict):
            continue
        ep_num = int(ep.get("num") or ep.get("seq_id") or (idx + 1))
        ep_vid = str(ep.get("video_id") or "")
        if ep_vid:
            episodes.append((ep_num, ep_vid))

    episodes.sort(key=lambda x: x[0])
    batches = [episodes[i : i + 5] for i in range(0, len(episodes), 5)]
    video_map = {}

    seed_item = vlist[0]
    seed_aweme = ((seed_item.get("video") or {}).get("aweme") or {})
    seed_vid = str(seed_aweme.get("aweme_id") or vid)
    video_map[seed_vid] = seed_item

    def _work(idx_batch):
        b_idx, batch = idx_batch
        need_ids = [evid for _, evid in batch if evid not in video_map]
        if not need_ids:
            return []
        resp = api_video_by_ids(need_ids, seed=b_idx)
        got = (resp or {}).get("video_list") or []
        out_pairs = []
        for item in got:
            aweme = ((item.get("video") or {}).get("aweme") or {})
            ivid = str(aweme.get("aweme_id") or "")
            if ivid:
                out_pairs.append((ivid, item))
        got_ids = {k for k, _ in out_pairs}
        for missing_id in need_ids:
            if missing_id not in got_ids:
                single = api_video_by_ids([missing_id], seed=b_idx + 3)
                slist = (single or {}).get("video_list") or []
                if slist:
                    out_pairs.append((missing_id, slist[0]))
        return out_pairs

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for pairs in ex.map(_work, enumerate(batches)):
            for k, v in pairs:
                video_map[k] = v

    results = []
    for ep_num, ep_vid in episodes:
        vitem = video_map.get(ep_vid)
        results.append(_parse_video_item(vitem, only_best=True, episode_num=ep_num))
    return results


INDEX_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0b12">
<title>PineDrama PRO · Dương Đình Hải</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0%25' stop-color='%232e1065'/%3E%3Cstop offset='100%25' stop-color='%231e1b4b'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='16' fill='url(%23g)'/%3E%3Cpath d='M32 16c-3-5-10-6-11-1 3 1 7 3 9 5 2-2 6-4 9-5-1-5-8-4-7 1z' fill='%2338bdf8'/%3E%3Cellipse cx='32' cy='36' rx='17' ry='15' fill='%23fb7185'/%3E%3Cpath d='M16 33c3-6 29-6 32 0 1 8-4 16-16 16S15 41 16 33z' fill='%23f43f5e'/%3E%3Crect x='21' y='34' width='17' height='11' rx='5.5' fill='%23ffe4e6'/%3E%3Crect x='25' y='36.5' width='2.6' height='5.5' rx='1.3' fill='%231e1b4b'/%3E%3Crect x='31' y='36.5' width='2.6' height='5.5' rx='1.3' fill='%231e1b4b'/%3E%3C/svg%3E">
<style>
:root{
  --bg:#0b0b12;
  --card:#13131f;
  --border:rgba(255,255,255,.08);
  --text:#f8fafc;
  --muted:#94a3b8;
  --purple:#8b5cf6;
  --pink:#ec4899;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{
  margin:0;
  min-height:100vh;
  background:radial-gradient(circle at 50% 0%, #23173d 0%, #0b0b12 62%);
  color:var(--text);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
}
a{color:inherit;text-decoration:none}

/* TOP NAVBAR */
.nav{
  position:sticky;top:0;z-index:40;
  background:rgba(11,11,18,.84);
  backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border);
}
.nav-in{
  max-width:1040px;margin:0 auto;padding:12px 18px;
  display:flex;align-items:center;justify-content:space-between;gap:12px;
}
.brand{display:flex;align-items:center;gap:11px}
.logo-box{
  width:42px;height:42px;border-radius:13px;flex-shrink:0;
  background:linear-gradient(135deg,#2e1065,#17153b);
  border:1.5px solid rgba(236,72,153,.55);
  box-shadow:0 0 16px rgba(236,72,153,.35);
  display:flex;align-items:center;justify-content:center;
}
.brand-title{font-weight:800;font-size:18px;letter-spacing:-.02em;display:flex;align-items:center}
.brand-title span{color:#e879f9}
.badge-pro{
  display:inline-block;margin-top:2px;font-size:10px;font-weight:800;letter-spacing:.04em;
  padding:2px 8px;border-radius:6px;
  background:linear-gradient(90deg,#ec4899,#8b5cf6);color:#fff;
}
.nav-links{display:flex;align-items:center;gap:8px}
.nav-pill{
  padding:7px 14px;border-radius:10px;font-size:13px;font-weight:600;color:#cbd5e1;
  transition:.2s;cursor:pointer;border:1px solid transparent;
}
.nav-pill:hover{color:#fff;background:rgba(255,255,255,.06)}
.nav-pill.active{
  background:linear-gradient(90deg,#9333ea,#6366f1);color:#fff;
  box-shadow:0 4px 14px rgba(147,51,234,.4);
}
.btn-admin{
  display:inline-flex;align-items:center;gap:7px;
  padding:7px 14px;border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;
  background:rgba(59,130,246,.14);color:#60a5fa;border:1px solid rgba(59,130,246,.35);
  transition:.2s;
}
.btn-admin:hover{background:rgba(59,130,246,.24);color:#93c5fd}

/* MAIN CONTAINER */
.wrap{max-width:840px;margin:0 auto;padding:22px 16px 96px}

/* MODE CARD */
.panel{
  background:rgba(19,19,31,.86);
  border:1px solid var(--border);
  border-radius:18px;
  padding:16px;
  box-shadow:0 12px 32px rgba(0,0,0,.35);
}
.panel-head{
  display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;
  margin-bottom:12px;
}
.panel-lbl{font-size:11px;font-weight:800;letter-spacing:.06em;color:var(--muted);text-transform:uppercase}
.pill-tag{
  font-size:11.5px;font-weight:600;padding:4px 11px;border-radius:999px;
  background:rgba(236,72,153,.14);color:#f472b6;border:1px solid rgba(236,72,153,.3);
}
.mode-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.mode-btn{
  display:flex;align-items:center;gap:10px;
  padding:12px 14px;border-radius:12px;cursor:pointer;
  background:#11111b;border:1px solid var(--border);color:#cbd5e1;
  font-weight:700;font-size:13.5px;text-align:left;transition:.2s;
}
.mode-btn.active{
  background:linear-gradient(90deg,rgba(147,51,234,.28),rgba(79,70,229,.18));
  border-color:#a855f7;color:#fff;
  box-shadow:0 0 0 1px rgba(168,85,247,.35);
}

/* HERO */
.hero{text-align:center;margin:28px 0 22px}
.hero h1{
  margin:0;font-size:30px;font-weight:800;letter-spacing:-.025em;
  background:linear-gradient(180deg,#ffffff 30%,#cbd5e1 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}
.hero p{
  margin:10px auto 0;max-width:650px;color:var(--muted);font-size:13.5px;line-height:1.55;
}

/* INPUT BOX */
.input-box{
  background:rgba(19,19,31,.92);
  border:1px solid var(--border);
  border-radius:20px;
  padding:16px;
  box-shadow:0 16px 40px rgba(0,0,0,.45);
}
.url-row{
  display:flex;align-items:center;gap:8px;
  background:#0c0c14;border:1px solid rgba(255,255,255,.1);
  border-radius:13px;padding:6px 8px 6px 14px;
  transition:.2s;
}
.url-row:focus-within{border-color:#8b5cf6;box-shadow:0 0 0 3px rgba(139,92,246,.18)}
.url-ico{color:#a855f7;flex-shrink:0;display:flex}
.url-row input{
  flex:1;min-width:0;border:0;outline:0;background:transparent;
  color:#fff;font-size:14px;padding:8px 4px;
}
.url-row input::placeholder{color:#64748b}
.btn-paste{
  border:1px solid rgba(255,255,255,.12);background:#1e1e2e;color:#e2e8f0;
  border-radius:9px;padding:7px 13px;font-size:12.5px;font-weight:700;cursor:pointer;
}
.btn-paste:hover{background:#2a2a3f}
.btn-clear{
  border:0;background:transparent;color:#64748b;font-size:16px;cursor:pointer;padding:4px 6px;display:none;
}
.btn-submit{
  width:100%;margin-top:12px;border:0;border-radius:13px;padding:14px 20px;
  font-size:15px;font-weight:800;color:#fff;cursor:pointer;
  background:linear-gradient(90deg,#fb923c 0%,#ec4899 52%,#8b5cf6 100%);
  box-shadow:0 10px 25px rgba(236,72,153,.32);
  transition:transform .12s,opacity .2s;
}
.btn-submit:hover{opacity:.95}
.btn-submit:active{transform:scale(.99)}
.btn-submit:disabled{opacity:.6;cursor:not-allowed}

/* STATS */
.stats{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
.stat-card{
  background:rgba(19,19,31,.82);border:1px solid var(--border);
  border-radius:15px;padding:16px;text-align:center;
}
.stat-num{font-size:21px;font-weight:800;color:#fff;letter-spacing:-.02em}
.stat-lbl{font-size:12px;color:var(--muted);margin-top:3px}

/* PC INFO SECTION */
.pc-box{
  display:none;text-align:center;
  background:rgba(19,19,31,.9);border:1px solid var(--border);
  border-radius:20px;padding:28px 20px;margin-top:16px;
}
.pc-logo{
  width:76px;height:76px;margin:0 auto 14px;border-radius:22px;
  background:linear-gradient(135deg,#2e1065,#17153b);
  border:2px solid #c084fc;box-shadow:0 0 28px rgba(192,132,252,.45);
  display:flex;align-items:center;justify-content:center;
}
.pc-badge{
  display:inline-block;padding:5px 14px;border-radius:999px;font-size:11.5px;font-weight:800;
  background:rgba(16,185,129,.15);color:#34d399;border:1px solid rgba(16,185,129,.35);
  margin-bottom:10px;
}

/* RESULTS AREA */
.res-wrap{margin-top:20px;display:none}
.res-head{
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;
  margin-bottom:12px;padding:0 4px;
}
.res-title{font-size:15px;font-weight:800;color:#fff}
.res-actions{display:flex;gap:8px}
.btn-mini{
  padding:7px 12px;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer;
  background:#1e1e2e;color:#e2e8f0;border:1px solid var(--border);
}
.btn-mini:hover{background:#29293d}

.ep-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.ep-card{
  background:var(--card);border:1px solid var(--border);border-radius:14px;padding:12px;
  display:flex;flex-direction:column;justify-content:space-between;gap:10px;
}
.ep-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.ep-name{font-weight:800;font-size:14px;color:#fff}
.ep-qual{
  font-size:11px;font-weight:800;padding:2px 8px;border-radius:6px;
  background:rgba(16,185,129,.16);color:#34d399;border:1px solid rgba(16,185,129,.3);
}
.ep-qual.err{background:rgba(239,68,68,.16);color:#f87171;border-color:rgba(239,68,68,.3)}
.ep-meta{font-size:11.5px;color:var(--muted)}
.ep-btns{display:flex;gap:7px}
.ep-btn{
  flex:1;text-align:center;padding:8px 10px;border-radius:9px;font-size:12.5px;font-weight:700;cursor:pointer;border:0;
}
.ep-btn.play{background:#232336;color:#e2e8f0;border:1px solid rgba(255,255,255,.08)}
.ep-btn.dl{background:linear-gradient(90deg,#ec4899,#8b5cf6);color:#fff}

/* MODAL */
.modal{
  position:fixed;inset:0;z-index:60;background:rgba(0,0,0,.85);backdrop-filter:blur(8px);
  display:none;align-items:center;justify-content:center;padding:16px;
}
.modal.open{display:flex}
.modal-box{
  width:100%;max-width:420px;background:#13131f;border:1px solid rgba(255,255,255,.12);
  border-radius:20px;padding:18px;box-shadow:0 20px 50px rgba(0,0,0,.6);
}
.modal-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.modal-close{background:#252538;border:0;color:#fff;border-radius:8px;padding:6px 11px;cursor:pointer;font-weight:700}
video{width:100%;max-height:70vh;border-radius:12px;background:#000}

/* ADMIN CARD IN MODAL */
.admin-card{
  background:#0d0d16;border:1px solid var(--border);border-radius:14px;padding:16px;text-align:center;
}
.admin-name{font-size:18px;font-weight:800;color:#fff;margin-top:8px}
.admin-phone{
  display:inline-block;margin:8px 0 14px;padding:6px 16px;border-radius:999px;
  background:rgba(59,130,246,.15);color:#60a5fa;font-weight:800;font-size:16px;letter-spacing:.03em;
}
.admin-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.btn-zalo-go{
  padding:11px;border-radius:11px;font-weight:800;font-size:13px;text-align:center;
  background:linear-gradient(90deg,#2563eb,#3b82f6);color:#fff;
}
.btn-copy-phone{
  padding:11px;border-radius:11px;font-weight:800;font-size:13px;border:1px solid var(--border);
  background:#1e1e2e;color:#fff;cursor:pointer;
}

/* FOOTER */
.footer{text-align:center;margin-top:26px;font-size:11.5px;color:#64748b;line-height:1.7}
.footer a{color:#60a5fa;font-weight:700}

/* BOTTOM BAR */
.bbar{
  position:fixed;bottom:0;left:0;right:0;z-index:40;
  background:rgba(13,13,22,.94);backdrop-filter:blur(12px);
  border-top:1px solid var(--border);
  display:flex;justify-content:center;gap:10px;padding:8px 12px;
}
.bitem{
  display:flex;flex-direction:column;align-items:center;gap:3px;
  padding:6px 18px;border-radius:12px;font-size:11.5px;font-weight:700;color:#94a3b8;cursor:pointer;
}
.bitem.active{background:rgba(139,92,246,.22);color:#fff;border:1px solid rgba(139,92,246,.38)}

.toast{
  position:fixed;left:50%;bottom:74px;transform:translateX(-50%);z-index:70;
  background:#fff;color:#0f172a;padding:9px 16px;border-radius:999px;
  font-size:13px;font-weight:700;box-shadow:0 8px 24px rgba(0,0,0,.4);
  opacity:0;pointer-events:none;transition:.2s;
}
.toast.show{opacity:1}

@media(max-width:680px){
  .nav-links .hide-m{display:none}
  .hero h1{font-size:23px}
  .mode-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<header class="nav">
  <div class="nav-in">
    <a class="brand" href="/">
      <div class="logo-box">
        <svg width="28" height="28" viewBox="0 0 64 64" fill="none">
          <path d="M32 16c-3-5-10-6-11-1 3 1 7 3 9 5 2-2 6-4 9-5-1-5-8-4-7 1z" fill="#38bdf8"/>
          <ellipse cx="32" cy="36" rx="18" ry="15" fill="#fb7185"/>
          <path d="M15 33c3-6 31-6 34 0 1 8-4 17-17 17S14 41 15 33z" fill="#f43f5e"/>
          <rect x="20" y="34" width="18" height="11" rx="5.5" fill="#ffe4e6"/>
          <rect x="24" y="36.5" width="2.8" height="5.5" rx="1.4" fill="#1e1b4b"/>
          <rect x="30.5" y="36.5" width="2.8" height="5.5" rx="1.4" fill="#1e1b4b"/>
        </svg>
      </div>
      <div>
        <div class="brand-title">Pine<span>Drama</span></div>
        <div class="badge-pro">PRO · VERCEL TURBO</div>
      </div>
    </a>
    <nav class="nav-links">
      <button type="button" class="nav-pill active" id="tabWeb" onclick="switchTab('web')">Tải Video Web</button>
      <button type="button" class="nav-pill hide-m" id="tabPc" onclick="switchTab('pc')">Bản Máy Tính</button>
      <button type="button" class="nav-pill hide-m" onclick="openAdmin()">Liên hệ Admin</button>
      <button type="button" class="btn-admin" onclick="openAdmin()">
        <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
        <span>Admin: Dương Đình Hải</span>
      </button>
    </nav>
  </div>
</header>

<main class="wrap">
  <div id="webSection">
    <section class="panel">
      <div class="panel-head">
        <span class="panel-lbl">Nền tảng &amp; Chế độ hỗ trợ tải</span>
        <span class="pill-tag">Chế độ tải video phim ngắn không logo</span>
      </div>
      <div class="mode-grid">
        <button type="button" class="mode-btn active" id="m-one" onclick="setMode('video')">
          <svg width="22" height="22" viewBox="0 0 64 64" fill="none" style="flex-shrink:0">
            <rect width="64" height="64" rx="16" fill="#2e1065"/>
            <path d="M32 16c-3-5-10-6-11-1 3 1 7 3 9 5 2-2 6-4 9-5-1-5-8-4-7 1z" fill="#38bdf8"/>
            <ellipse cx="32" cy="36" rx="18" ry="15" fill="#f43f5e"/>
            <rect x="20" y="34" width="18" height="11" rx="5.5" fill="#ffe4e6"/>
            <rect x="24" y="36.5" width="2.8" height="5.5" rx="1.4" fill="#1e1b4b"/>
            <rect x="30.5" y="36.5" width="2.8" height="5.5" rx="1.4" fill="#1e1b4b"/>
          </svg>
          <span>PineDrama (Tải 1 Tập 1080p)</span>
        </button>
        <button type="button" class="mode-btn" id="m-full" onclick="setMode('full')">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.2" style="flex-shrink:0"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
          <span>PineDrama Full Bộ (Tất Cả Tập)</span>
        </button>
      </div>
    </section>

    <section class="hero">
      <h1>Tải Video PineDrama Không Logo</h1>
      <p>Bóc tách video không logo chuẩn 1080p Full HD từ PineDrama (ShortDrama). Hỗ trợ link app, văn bản chia sẻ kèm chữ, link web máy tính và ID trần.</p>
    </section>

    <section class="input-box">
      <div class="url-row">
        <span class="url-ico">
          <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        </span>
        <input type="text" id="urlInput" placeholder="Dán link video PineDrama (shortdrama.tiktok.com/t/...)..." autocomplete="off">
        <button type="button" class="btn-clear" id="btnClear" onclick="clearInput()">✕</button>
        <button type="button" class="btn-paste" onclick="pasteClip()">Dán</button>
      </div>
      <button type="button" class="btn-submit" id="btnGo" onclick="fetchVideo()">Lấy video không logo</button>
    </section>

    <section class="stats">
      <div class="stat-card">
        <div class="stat-num" id="stViews">128.453</div>
        <div class="stat-lbl">Tổng lượt truy cập</div>
      </div>
      <div class="stat-card">
        <div class="stat-num" id="stToday">3.281</div>
        <div class="stat-lbl">Lượt tải hôm nay (GMT+7)</div>
      </div>
    </section>

    <section class="res-wrap" id="resWrap">
      <div class="res-head">
        <div class="res-title" id="resTitle">Danh sách video</div>
        <div class="res-actions">
          <button type="button" class="btn-mini" onclick="copyAllLinks()">📋 Copy tất cả link MP4</button>
          <button type="button" class="btn-mini" onclick="copyRawJson()">{} Copy JSON</button>
        </div>
      </div>
      <div class="ep-grid" id="epGrid"></div>
    </section>
  </div>

  <section class="pc-box" id="pcSection">
    <div class="pc-logo">
      <svg width="48" height="48" viewBox="0 0 64 64" fill="none">
        <path d="M32 16c-3-5-10-6-11-1 3 1 7 3 9 5 2-2 6-4 9-5-1-5-8-4-7 1z" fill="#38bdf8"/>
        <ellipse cx="32" cy="36" rx="18" ry="15" fill="#fb7185"/>
        <path d="M15 33c3-6 31-6 34 0 1 8-4 17-17 17S14 41 15 33z" fill="#f43f5e"/>
        <rect x="20" y="34" width="18" height="11" rx="5.5" fill="#ffe4e6"/>
        <rect x="24" y="36.5" width="2.8" height="5.5" rx="1.4" fill="#1e1b4b"/>
        <rect x="30.5" y="36.5" width="2.8" height="5.5" rx="1.4" fill="#1e1b4b"/>
      </svg>
    </div>
    <div class="pc-badge">● BẢN PHÁT HÀNH: v5.3.0 (CẬP NHẬT TỰ ĐỘNG)</div>
    <h2 style="margin:4px 0 10px;font-size:26px;font-weight:800">Pine Drama PRO</h2>
    <p style="max-width:560px;margin:0 auto 18px;color:var(--muted);font-size:13.5px;line-height:1.6">
      Bộ phần mềm chuyên dụng cho máy tính Windows &amp; Termux: Tự động quét và tải hàng loạt trọn bộ 50 - 150 tập phim ngắn không logo từ PineDrama.
    </p>
    <button type="button" class="btn-submit" style="max-width:340px" onclick="openAdmin()">Liên hệ Admin Dương Đình Hải để nhận bản PC</button>
  </section>

  <footer class="footer">
    <div>PineDrama Downloader PRO • Bảo mật &amp; Tốc độ cao © 2026</div>
    <div>Liên hệ hỗ trợ Admin: <a href="javascript:void(0)" onclick="openAdmin()">Dương Đình Hải - 0862732490</a></div>
    <div id="clockLine">Múi giờ Việt Nam (GMT+7) • Bản phát hành v5.3.0</div>
  </footer>
</main>

<div class="bbar">
  <button type="button" class="bitem active" id="bWeb" onclick="switchTab('web')" style="background:none;border:0">
    <span>🏠</span>
    <span>Tải video</span>
  </button>
  <button type="button" class="bitem" id="bPc" onclick="switchTab('pc')" style="background:none;border:0">
    <span>💻</span>
    <span>Bản máy tính</span>
  </button>
  <button type="button" class="bitem" onclick="openAdmin()" style="background:none;border:0">
    <span>📞</span>
    <span>Liên hệ Admin</span>
  </button>
</div>

<!-- VIDEO PLAYER MODAL -->
<div class="modal" id="playerModal" onclick="if(event.target===this)closePlayer()">
  <div class="modal-box">
    <div class="modal-top">
      <strong id="modalTitle">Xem trước video</strong>
      <button type="button" class="modal-close" onclick="closePlayer()">Đóng ✕</button>
    </div>
    <video id="videoPlayer" controls playsinline></video>
  </div>
</div>

<!-- ADMIN CONTACT MODAL -->
<div class="modal" id="adminModal" onclick="if(event.target===this)closeAdmin()">
  <div class="modal-box">
    <div class="modal-top">
      <strong>Thông tin liên hệ Admin</strong>
      <button type="button" class="modal-close" onclick="closeAdmin()">Đóng ✕</button>
    </div>
    <div class="admin-card">
      <div class="logo-box" style="margin:0 auto;width:54px;height:54px">
        <svg width="34" height="34" viewBox="0 0 64 64" fill="none">
          <path d="M32 16c-3-5-10-6-11-1 3 1 7 3 9 5 2-2 6-4 9-5-1-5-8-4-7 1z" fill="#38bdf8"/>
          <ellipse cx="32" cy="36" rx="18" ry="15" fill="#fb7185"/>
          <path d="M15 33c3-6 31-6 34 0 1 8-4 17-17 17S14 41 15 33z" fill="#f43f5e"/>
          <rect x="20" y="34" width="18" height="11" rx="5.5" fill="#ffe4e6"/>
          <rect x="24" y="36.5" width="2.8" height="5.5" rx="1.4" fill="#1e1b4b"/>
          <rect x="30.5" y="36.5" width="2.8" height="5.5" rx="1.4" fill="#1e1b4b"/>
        </svg>
      </div>
      <div class="admin-name">Dương Đình Hải</div>
      <div style="font-size:12px;color:var(--muted);margin-top:2px">Quản trị viên hệ thống PineDrama PRO</div>
      <div class="admin-phone">0862732490</div>
      <div class="admin-actions">
        <a class="btn-zalo-go" href="https://zalo.me/0862732490" target="_blank" rel="noopener">💬 Nhắn Zalo ngay</a>
        <button type="button" class="btn-copy-phone" onclick="copyPhone()">📋 Copy SĐT</button>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let currentMode = "video";
let lastData = [];

function $(id){ return document.getElementById(id); }

function toast(msg){
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(window._tt);
  window._tt = setTimeout(() => t.classList.remove("show"), 2000);
}

function switchTab(tab){
  const isWeb = tab === "web";
  $("webSection").style.display = isWeb ? "block" : "none";
  $("pcSection").style.display = isWeb ? "none" : "block";
  $("tabWeb").classList.toggle("active", isWeb);
  $("tabPc").classList.toggle("active", !isWeb);
  $("bWeb").classList.toggle("active", isWeb);
  $("bPc").classList.toggle("active", !isWeb);
}

function openAdmin(){ $("adminModal").classList.add("open"); }
function closeAdmin(){ $("adminModal").classList.remove("open"); }
function copyPhone(){
  navigator.clipboard.writeText("0862732490").then(() => toast("Đã copy SĐT: 0862732490"));
}

function setMode(m){
  currentMode = m;
  $("m-one").classList.toggle("active", m === "video");
  $("m-full").classList.toggle("active", m === "full");
  $("btnGo").textContent = m === "video" ? "Lấy video không logo" : "Lấy toàn bộ các tập phim";
}

$("urlInput").addEventListener("input", () => {
  $("btnClear").style.display = $("urlInput").value ? "block" : "none";
});

function clearInput(){
  $("urlInput").value = "";
  $("btnClear").style.display = "none";
  $("urlInput").focus();
}

async function pasteClip(){
  try{
    const txt = await navigator.clipboard.readText();
    if(txt){
      $("urlInput").value = txt;
      $("btnClear").style.display = "block";
      toast("Đã dán liên kết!");
    } else {
      toast("Bộ nhớ tạm đang trống");
    }
  }catch(e){
    toast("Hãy nhấn giữ ô nhập và chọn Dán");
  }
}

function updateClock(){
  const now = new Date();
  const s = now.toLocaleString("vi-VN", {timeZone:"Asia/Ho_Chi_Minh"});
  $("clockLine").textContent = "Múi giờ Việt Nam: " + s + " (GMT+7) • Bản phát hành v5.3.0";
}
setInterval(updateClock, 1000);
updateClock();

async function fetchVideo(){
  const raw = $("urlInput").value.trim();
  if(!raw){
    toast("Vui lòng dán link video PineDrama trước!");
    $("urlInput").focus();
    return;
  }
  const btn = $("btnGo");
  btn.disabled = true;
  btn.textContent = currentMode === "video" ? "⏳ Đang bóc tách video..." : "⏳ Đang tải danh sách toàn bộ tập...";

  const endpoint = currentMode === "video" ? "/api/video" : "/api/full";
  try{
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: raw})
    });
    const data = await res.json();
    if(!Array.isArray(data) || data.length === 0){
      toast("Không tìm thấy dữ liệu video!");
      return;
    }
    lastData = data;
    renderResults(data);
    const curToday = parseInt($("stToday").textContent.replace(/\./g,"")) || 3281;
    $("stToday").textContent = (curToday + 1).toLocaleString("vi-VN");
    toast("Bóc tách thành công " + data.length + " video!");
  }catch(err){
    toast("Lỗi kết nối: " + (err.message || "Thử lại sau"));
  }finally{
    btn.disabled = false;
    setMode(currentMode);
  }
}

function renderResults(items){
  const wrap = $("resWrap");
  const grid = $("epGrid");
  grid.innerHTML = "";
  wrap.style.display = "block";

  const okCount = items.filter(x => x.success && x.variants && x.variants.length).length;
  $("resTitle").textContent = `Kết quả: ${okCount}/${items.length} tập sẵn sàng tải`;

  items.forEach((item, idx) => {
    const epNum = item.episode || (idx + 1);
    const card = document.createElement("div");
    card.className = "ep-card";

    if(!item.success || !item.variants || !item.variants.length){
      card.innerHTML = `
        <div class="ep-top">
          <span class="ep-name">Tập ${epNum}</span>
          <span class="ep-qual err">Lỗi</span>
        </div>
        <div class="ep-meta">${item.error || "Không lấy được link"}</div>
      `;
      grid.appendChild(card);
      return;
    }

    const best = item.variants[0];
    const dlUrl = (best.urls && best.urls[0]) || best.api_url || "";
    const qual = best.quality || "HD";
    const codec = (best.codec || "h264").toUpperCase();

    card.innerHTML = `
      <div class="ep-top">
        <span class="ep-name">Tập ${epNum}</span>
        <span class="ep-qual">${qual} · ${codec}</span>
      </div>
      <div class="ep-meta">ID: ${item.video_id || "N/A"}</div>
      <div class="ep-btns">
        <button type="button" class="ep-btn play" onclick="openPlayer('Tập ${epNum} (${qual})', '${dlUrl}')">▶ Xem</button>
        <a class="ep-btn dl" href="${dlUrl}" target="_blank" rel="noopener" download="PineDrama_Tap_${epNum}.mp4">⬇ Tải MP4</a>
      </div>
    `;
    grid.appendChild(card);
  });

  wrap.scrollIntoView({behavior:"smooth", block:"start"});
}

function openPlayer(title, url){
  if(!url){ toast("Không có link phát"); return; }
  $("modalTitle").textContent = title;
  const v = $("videoPlayer");
  v.src = url;
  $("playerModal").classList.add("open");
  v.play().catch(()=>{});
}

function closePlayer(){
  const v = $("videoPlayer");
  v.pause();
  v.src = "";
  $("playerModal").classList.remove("open");
}

function copyAllLinks(){
  if(!lastData.length){ toast("Chưa có danh sách video nào!"); return; }
  const links = [];
  lastData.forEach(item => {
    if(item.success && item.variants && item.variants[0]){
      const u = (item.variants[0].urls && item.variants[0].urls[0]) || item.variants[0].api_url;
      if(u) links.push(u);
    }
  });
  if(!links.length){ toast("Không có link hợp lệ"); return; }
  navigator.clipboard.writeText(links.join("\\n")).then(() => {
    toast("Đã copy " + links.length + " link MP4!");
  });
}

function copyRawJson(){
  if(!lastData.length){ toast("Chưa có dữ liệu!"); return; }
  navigator.clipboard.writeText(JSON.stringify(lastData, null, 2)).then(() => {
    toast("Đã copy dữ liệu JSON!");
  });
}
</script>
</body>
</html>
"""


class handler(BaseHTTPRequestHandler):
    def _send_bytes(self, status, content_type, data):
        self.send_response(status)
        self.send_header("Server", "dlweb-vercel")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", raw)

    def _extract_url_param(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="ignore") if length > 0 else ""
        url_val = None
        if body:
            try:
                j = json.loads(body)
                if isinstance(j, dict):
                    url_val = j.get("url")
            except Exception:
                m = re.search(r'"url"\s*:\s*"([^"]+)"', body)
                if m:
                    url_val = m.group(1).replace("\\/", "/")
        if not url_val and "url" in qs:
            url_val = qs["url"][0]
        return (url_val or "").strip()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html", "/api", "/api/index"):
            self._send_bytes(200, "text/html; charset=utf-8", INDEX_HTML.encode("utf-8"))
            return
        if path == "/api/ping":
            self._send_json(200, {"ok": True, "t": int(time.time() * 1000), "engine": "vercel-python"})
            return
        if path == "/api/status":
            self._send_json(
                200,
                {
                    "ok": True,
                    "engine": "vercel-python",
                    "device_id": DEVICE_ID,
                    "install_id": INSTALL_ID,
                },
            )
            return
        if path == "/api/resolve":
            u = (qs.get("url") or [""])[0].strip()
            if not u:
                self._send_json(400, {"ok": False, "error": "missing url"})
                return
            try:
                final_u, vid = resolve_share_url(u)
                if not vid:
                    self._send_json(404, {"ok": False, "error": "no video id", "final_url": final_u})
                    return
                res = fetch_video_one(vid)
                item = res[0] if res else {}
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "video_id": vid,
                        "collection_id": item.get("collection_id"),
                        "final_url": final_u,
                    },
                )
            except Exception as e:
                self._send_json(500, {"ok": False, "error": str(e)})
            return
        self._send_json(404, {"error": f"not found: {path}"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in ("/api/video", "/api/full"):
            url_val = self._extract_url_param()
            if not url_val:
                self._send_json(400, [{"success": False, "variants": [], "error": "missing url"}])
                return
            try:
                if path == "/api/video":
                    data = fetch_video_one(url_val)
                else:
                    data = fetch_full_series(url_val)
                self._send_json(200, data)
            except Exception as e:
                self._send_json(500, [{"success": False, "variants": [], "error": str(e)}])
            return
        self._send_json(404, {"error": f"not found: {path}"})
