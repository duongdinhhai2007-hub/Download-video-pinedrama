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
        f"&is_play_h265=1&bytevc1=1&enable_dubbing=1&dubbing_language=vie"
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
    payload = json.dumps({
        "video_ids": ids_int,
        "dubbing_language": "vie",
        "enable_dubbing": True
    }).encode("utf-8")

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


def _addr_variant(play_addr, source, is_bytevc1, bitrate, lang_tag="orig"):
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
    is_vi = lang_tag == "vi" or "vie" in url_key.lower() or "dub" in url_key.lower()
    return {
        "source": source,
        "lang": "vi" if is_vi else "orig",
        "urls": urls,
        "api_url": api_url,
        "quality": _quality_name(rank),
        "codec": codec,
        "bitrate": bitrate if bitrate > 0 else None,
        "expires_at": _expires_at(sample_url),
        "_q": rank,
    }


def _extract_vi_dub_urls(aweme, vobj):
    """Tìm luồng video hoặc audio thuyết minh tiếng Việt từ dub_infos / cla_info / bit_rate_audio."""
    vi_urls = []
    vi_audio_urls = []

    def _scan_dub_list(dub_list):
        if not isinstance(dub_list, list):
            return
        for d in dub_list:
            if not isinstance(d, dict):
                continue
            lang = str(d.get("language") or d.get("lang") or d.get("language_code") or "").lower()
            if "vi" in lang:
                for k in ("play_addr", "video_play_addr", "main_play_addr"):
                    pa = d.get(k)
                    if isinstance(pa, dict) and pa.get("url_list"):
                        vi_urls.extend(pa["url_list"])
                for k in ("audio_play_addr", "play_audio_addr", "audio_addr"):
                    aa = d.get(k)
                    if isinstance(aa, dict) and aa.get("url_list"):
                        vi_audio_urls.extend(aa["url_list"])
                if d.get("url"):
                    vi_audio_urls.append(d["url"])

    _scan_dub_list(vobj.get("dub_infos"))
    _scan_dub_list(aweme.get("dub_infos"))

    cla = aweme.get("cla_info") or vobj.get("cla_info") or {}
    if isinstance(cla, dict):
        _scan_dub_list(cla.get("dub_infos") or cla.get("caption_infos"))

    br_audio = vobj.get("bit_rate_audio") or []
    if isinstance(br_audio, list):
        for ba in br_audio:
            if not isinstance(ba, dict):
                continue
            meta = str(ba.get("audio_meta") or ba.get("language") or "").lower()
            if "vi" in meta or "dub" in meta:
                pa = ba.get("play_addr") or {}
                if isinstance(pa, dict) and pa.get("url_list"):
                    vi_audio_urls.extend(pa["url_list"])

    return vi_urls, vi_audio_urls


def _parse_video_item(vitem, only_best=False, episode_num=None):
    out = {"variants": [], "vi_variants": [], "vi_audio": [], "error": None}
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

    vi_direct_urls, vi_audio_urls = _extract_vi_dub_urls(aweme, vobj)
    out["vi_audio"] = vi_audio_urls

    orig_variants = []
    vi_variants = []

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
                if v.get("lang") == "vi":
                    vi_variants.append(v)
                else:
                    orig_variants.append(v)

        orig_variants.sort(key=lambda x: (x.get("_q") or 0, x.get("bitrate") or 0), reverse=True)
        vi_variants.sort(key=lambda x: (x.get("_q") or 0, x.get("bitrate") or 0), reverse=True)

        if not vi_variants and vi_direct_urls:
            vi_variants.append({
                "source": "dub_vi",
                "lang": "vi",
                "urls
