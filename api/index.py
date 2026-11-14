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


def resolve_share_url(url):
    vid = find_video_id(url)
    if vid:
        return url, vid

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    cur = url.strip()
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
        time.sleep(0.1 * (attempt + 1))
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
        time.sleep(0.15 * (attempt + 1))
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
    return f"{rank}p" if rank > 0 else None


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
    vobj = aweme.get("video") or {}
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
        raise ValueError("missing or invalid video url/id")
    data = api_video_by_ids([vid])
    vlist = (data or {}).get("video_list") or []
    if not vlist:
        return [{"variants": [], "error": "no raw video body", "success": False}]
    return [_parse_video_item(vlist[0], only_best=True)]


def fetch_full_series(url_or_id, max_workers=6):
    _, vid = resolve_share_url(url_or_id)
    if not vid:
        raise ValueError("missing or invalid video url/id")

    first = api_video_by_ids([vid])
    vlist = (first or {}).get("video_list") or []
    if not vlist:
        raise RuntimeError("no raw video body for seed video")

    cid = str(vlist[0].get("collection_id") or "")
    if not cid:
        raise RuntimeError("no collection_id found")

    panel = api_episode_panel(cid)
    ep_list = (panel or {}).get("episode_list") or []
    if not ep_list:
        return [{"variants": [], "error": "no collection", "success": False}]

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
        results.append(_parse_video_item(vitem, only_best=False, episode_num=ep_num))
    return results


INDEX_HTML = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#09090d">
<title>Pine PRO · Python</title>
<link rel="icon" id="favicon" href="https://raw.githubusercontent.com/haicon22/Pine_Pro/refs/heads/main/app.jpg">
<style>
:root{--bg:#09090d;--p1:#12121a;--p2:#1a1a24;--line:rgba(255,255,255,.08);--tx:#f6f3ec;--dim:#a8a3b3;--ac:#e23d5b;--ok:#3dbe86;--bad:#ff6d7a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.45 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
body{padding:18px 16px 40px;max-width:720px;margin:0 auto}
.head{display:flex;gap:14px;align-items:center;margin-bottom:16px}
.logo{width:72px;height:72px;border-radius:22px;object-fit:cover;background:#0b1a33;border:1px solid var(--line)}
h1{margin:0;font-size:26px;letter-spacing:-.03em}
.sub{color:var(--dim);font-size:13px;margin-top:2px}
.card{background:var(--p1);border:1px solid var(--line);border-radius:18px;padding:14px;margin-bottom:12px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.btn{border:0;border-radius:999px;padding:12px 18px;font-weight:750;letter-spacing:.01em;background:linear-gradient(180deg,#ff5b78,#e11d48);color:#fff;cursor:pointer;box-shadow:0 8px 18px rgba(225,29,72,.28)}
.btn.sec{background:#1c1c28;color:var(--tx);border:1px solid rgba(255,255,255,.12);box-shadow:none}
.btn.on{background:#fff;color:#14141c;box-shadow:none}
.path{font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#9ec1ff}
.dgrp{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);font-weight:700;margin:12px 0 6px}
.note{color:var(--dim);font-size:13px}
.dguide{background:#101018;border:1px solid var(--line);border-radius:14px;padding:12px;margin-top:10px}
pre.json{margin:4px 0 0;padding:12px;background:#0c0c12;border:1px solid var(--line);border-radius:14px;overflow:auto;max-height:28vh;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word;color:#d9d4e4}
pre.out{max-height:52vh}
textarea{width:100%;min-height:96px;margin-top:8px;border-radius:14px;border:1px solid var(--line);background:#0c0c12;color:var(--tx);padding:12px;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;resize:vertical}
.dst{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:800;background:#2c2c3a;color:var(--dim)}
.dst.ok{background:#0f3a26;color:var(--ok)}.dst.bad{background:#3b1a1a;color:var(--bad)}
.jk{color:#9ec1ff}.js{color:#8ee0bf}.jn{color:#f0b36a}.jb{color:#d7b0ff}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#fff;color:#111;padding:8px 14px;border-radius:999px;font-weight:700;opacity:0;pointer-events:none}
.toast.on{opacity:1}
</style>
</head>
<body>
<div class="head">
<img class="logo" id="logo" alt="Pine PRO" src="https://raw.githubusercontent.com/haicon22/Pine_Pro/refs/heads/main/app.jpg">
<div><h1>Pine PRO <span style="font-size:13px;color:#3dbe86;font-weight:700">[Vercel Cloud]</span></h1><div class="sub">Chạy trực tuyến trên Vercel (Batch 5x + Multi-host Retry, lấy 100% tập không lỗi). Dán link một tập vào body rồi bấm Gửi.</div></div>
</div>
<div class="card">
<div class="row"><span class="path" id="method">POST</span><span class="path" id="showpath">/api/video</span></div>
<div class="row" style="margin-top:10px">
<button class="btn on" id="bvideo" type="button">Video gốc</button>
<button class="btn sec" id="bfull" type="button">Full tập</button>
</div>
<div class="dguide">
<div class="dgrp" style="margin-top:0">Hướng dẫn</div>
<div class="note" id="guide"></div>
<div class="dgrp">Body mẫu</div>
<pre class="json" id="sample"></pre>
</div>
<div class="dgrp">Body sẽ gửi</div>
<pre class="json" id="live"></pre>
<textarea id="body" spellcheck="false"></textarea>
<div class="row" style="margin-top:10px">
<button class="btn" id="send" type="button">Gửi</button>
<button class="btn sec" id="fmt" type="button">Định dạng</button>
<button class="btn sec" id="copyb" type="button">Sao chép body</button>
</div>
</div>
<div class="card">
<div class="row"><span class="dst" id="st">Chưa gửi</span><span class="note" id="meta"></span></div>
<pre class="json out" id="out"></pre>
<div class="row" style="margin-top:10px"><button class="btn" id="copyr" type="button">Sao chép kết quả</button></div>
</div>
<div class="toast" id="toast"></div>
<script>
var URLV="https://shortdrama.tiktok.com/t/ZSb4jBFrW/";
var SAMPLE='{\\n  "url": "'+URLV+'"\\n}';
var PRE={
  video:["/api/video","Gửi POST /api/video. Body là JSON, khóa url là link một tập. Kết quả trả về bản nét cao nhất (ưu tiên 1080p -> 720p)."],
  full:["/api/full","Gửi POST /api/full với cùng body. Gom nhóm 5 tập/lượt + tự động retry nên lấy đủ 100% số tập cực nhanh."]
};
var mode="video", last="";
function $(id){return document.getElementById(id)}
function toast(t){var n=$("toast");n.textContent=t;n.className="toast on";setTimeout(function(){n.className="toast"},1600)}
function colorJson(s){
  var i=0,out="";
  function esc(t){return t.replace(/&/g,"&amp;").replace(/</g,"&lt;")}
  while(i<s.length){
    var c=s.charAt(i);
    if(c==='"'){
      var j=i+1;
      while(j<s.length){if(s.charAt(j)==="\\\\"){j+=2;continue}if(s.charAt(j)==='"'){j++;break}j++}
      var k=j;while(k<s.length&&/\\s/.test(s.charAt(k)))k++;
      out+='<span class="'+(s.charAt(k)===":"?"jk":"js")+'">'+esc(s.slice(i,j))+"</span>";
      i=j;
    }else if(/[\\d-]/.test(c)&&(i===0||/[\\s,:\\[{]/.test(s.charAt(i-1)))){
      var m=s.slice(i).match(/^-?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?/);
      if(m){out+='<span class="jn">'+m[0]+"</span>";i+=m[0].length;continue}
      out+=esc(c);i++;
    }else if(s.startsWith("true",i)||s.startsWith("false",i)||s.startsWith("null",i)){
      var w=s.startsWith("true",i)?"true":s.startsWith("false",i)?"false":"null";
      var nx=s.charAt(i+w.length);
      if(!nx||/[\\s,\\]}]/.test(nx)){out+='<span class="jb">'+w+"</span>";i+=w.length;continue}
      out+=esc(c);i++;
    }else{out+=esc(c);i++}
  }
  return out;
}
function paint(node,text){
  try{node.innerHTML=colorJson(JSON.stringify(JSON.parse(text),null,2))}catch(e){node.textContent=text}
}
function show(which){
  mode=which;
  $("bvideo").className="btn"+(which==="video"?" on":" sec");
  $("bfull").className="btn"+(which==="full"?" on":" sec");
  $("showpath").textContent=PRE[which][0];
  $("guide").textContent=PRE[which][1];
  paint($("sample"), SAMPLE);
  if(!$("body").value)$("body").value=SAMPLE;
  paint($("live"), $("body").value);
}
function copyText(t){
  t=t==null?"":String(t);
  if(!t){toast("Chưa có nội dung");return}
  function ok(){toast("Đã sao chép "+t.length+" ký tự")}
  function fallback(){
    var ta=document.createElement("textarea");
    ta.value=t;ta.readOnly=true;
    ta.style.cssText="position:fixed;top:0;left:0;width:100%;height:140px;font-size:16px;opacity:.02";
    document.body.appendChild(ta);ta.focus();ta.select();
    var done=false;try{done=document.execCommand("copy")}catch(e){done=false}
    document.body.removeChild(ta);
    if(done)ok();else toast("Chưa sao chép được");
  }
  if(window.isSecureContext&&navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(ok).catch(fallback);
  }else fallback();
}
$("body").addEventListener("input",function(){paint($("live"),$("body").value)});
$("bvideo").onclick=function(){show("video")};
$("bfull").onclick=function(){show("full")};
$("fmt").onclick=function(){
  try{$("body").value=JSON.stringify(JSON.parse($("body").value),null,2);paint($("live"),$("body").value);toast("Đã định dạng")}catch(e){toast("JSON không hợp lệ")}
};
$("copyb").onclick=function(){copyText($("body").value)};
$("copyr").onclick=function(){if(!last){toast("Chưa có kết quả");return}copyText(last)};
$("send").onclick=function(){
  var path=PRE[mode][0], opt={method:"POST",headers:{"Accept":"application/json","Content-Type":"application/json; charset=utf-8"},body:$("body").value};
  $("st").className="dst";$("st").textContent="Đang gửi";$("meta").textContent="";
  var t0=Date.now();
  fetch(path,opt).then(function(r){
    return r.text().then(function(raw){
      var pretty=raw, okj=false;
      try{pretty=JSON.stringify(JSON.parse(raw),null,2);okj=true}catch(e){}
      last=okj?pretty:raw;
      $("st").className="dst "+(r.status>=200&&r.status<300?"ok":"bad");
      $("st").textContent=String(r.status);
      $("meta").textContent=(Date.now()-t0)+" ms · "+raw.length+" B";
      if(okj)$("out").innerHTML=colorJson(pretty);else $("out").textContent=raw;
    });
  }).catch(function(e){$("st").className="dst bad";$("st").textContent="Lỗi";$("meta").textContent=e.message||String(e)});
};
show("video");
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
