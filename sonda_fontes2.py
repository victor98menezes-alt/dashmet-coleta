"""Sonda: radiossonda (Wyoming), radar (RainViewer), GOES-19 (ABI C13 e GLM) na AWS."""
import json, os, time, urllib.request, urllib.error, re, math, datetime as dt
UA = "DashboardMeteorologicoSalto/1.0 (uso institucional nao comercial)"
OUT = "saida/_sonda/fontes2"; os.makedirs(OUT, exist_ok=True)
res = {}
def get(u, n=None, binary=False, timeout=60):
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=timeout) as r:
            b = r.read() if n is None else r.read(n)
            return {"status": r.status, "bytes": len(b), "s": round(time.time() - t0, 1), "ctype": r.headers.get("Content-Type"), "body": b}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "erro": e.read()[:400].decode("utf-8", "replace")}
    except Exception as e:
        return {"erro": repr(e)}
def keep(k, r, txt=3000):
    d = {x: y for x, y in r.items() if x != "body"}
    if "body" in r:
        b = r["body"]
        if r.get("ctype", "") and ("text" in r["ctype"] or "json" in r["ctype"] or "xml" in r["ctype"]): d["texto"] = b[:txt].decode("utf-8", "replace")
    res[k] = d; print(k, {x: y for x, y in d.items() if x != "texto"})
now = dt.datetime.now(dt.timezone.utc)
ymd = now.strftime("%Y-%m-%d")
# 1) radiossonda Galeão 83746 (00Z/12Z)
for hh in ["12", "00"]:
    for k, u in [("uwyo_wsgi_list", f"https://weather.uwyo.edu/wsgi/sounding?datetime={ymd}%20{hh}:00:00&id=83746&type=TEXT:LIST&src=UNKNOWN"),
                 ("uwyo_wsgi_csv", f"https://weather.uwyo.edu/wsgi/sounding?datetime={ymd}%20{hh}:00:00&id=83746&type=TEXT:CSV&src=UNKNOWN"),
                 ("uwyo_cgi", f"https://weather.uwyo.edu/cgi-bin/sounding?region=samer&TYPE=TEXT%3ALIST&YEAR={now:%Y}&MONTH={now:%m}&FROM={now:%d}{hh}&TO={now:%d}{hh}&STNM=83746")]:
        keep(f"{k}_{hh}", get(u), 6000)
keep("igra_y2d", get("https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/access/data-y2d/", 4000), 4000)
# 2) radar RainViewer
r = get("https://api.rainviewer.com/public/weather-maps.json"); keep("rainviewer_maps", r, 4000)
try:
    j = json.loads(r["body"]); host = j["host"]; past = j["radar"]["past"]; last = past[-1]["path"]
    z = 6; lat, lon = -22.875, -43.384
    n = 2 ** z; x = int((lon + 180) / 360 * n); y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    for col in ["0", "2"]:
        u = f"{host}{last}/256/{z}/{x}/{y}/{col}/0_0.png"; rr = get(u)
        keep(f"rainviewer_tile_c{col}", rr)
        if "body" in rr: open(f"{OUT}/rv_z{z}_{x}_{y}_c{col}.png", "wb").write(rr["body"])
    u = f"{host}{last}/512/{z}/{x}/{y}/0/0_0.png"; keep("rainviewer_512", get(u))
except Exception as e:
    res["rainviewer_tile"] = {"erro": repr(e)}
# 3) GOES-19 na AWS
doy = now.timetuple().tm_yday
def lst(prefix):
    u = f"https://noaa-goes19.s3.amazonaws.com/?list-type=2&prefix={prefix}&max-keys=1000"
    rr = get(u)
    if "body" not in rr: return rr, []
    t = rr["body"].decode()
    return rr, list(zip(re.findall(r"<Key>([^<]+)</Key>", t), map(int, re.findall(r"<Size>(\d+)</Size>", t))))
for h in [now.hour, (now - dt.timedelta(hours=1)).hour]:
    rr, ks = lst(f"ABI-L2-CMIPF/{now:%Y}/{doy:03d}/{h:02d}/OR_ABI-L2-CMIPF-M6C13")
    res[f"abi_c13_{h}"] = {"status": rr.get("status"), "n": len(ks), "ex": ks[-3:]}; print("abi", h, len(ks), ks[-2:])
    if ks: break
if ks:
    k, sz = ks[-1]; rr = get(f"https://noaa-goes19.s3.amazonaws.com/{k}", timeout=180)
    res["abi_c13_download"] = {x: y for x, y in rr.items() if x != "body"}
    if "body" in rr:
        open(f"{OUT}/c13.nc", "wb").write(rr["body"])
        try:
            import h5py, numpy as np
            f = h5py.File(f"{OUT}/c13.nc", "r"); res["abi_vars"] = list(f.keys())[:40]
            v = f["CMI"]; res["abi_cmi"] = {"shape": v.shape, "attrs": {a: str(v.attrs[a]) for a in v.attrs}}
            pr = f["goes_imager_projection"]; res["abi_proj"] = {a: str(pr.attrs[a]) for a in pr.attrs}
            res["abi_x"] = {a: str(f["x"].attrs[a]) for a in f["x"].attrs}; res["abi_y"] = {a: str(f["y"].attrs[a]) for a in f["y"].attrs}
        except Exception as e: res["abi_h5"] = repr(e)
        os.remove(f"{OUT}/c13.nc")
rr, ks = lst(f"GLM-L2-LCFA/{now:%Y}/{doy:03d}/{now.hour:02d}/")
res["glm_list"] = {"status": rr.get("status"), "n": len(ks), "sz_med": (sum(s for _, s in ks) / len(ks)) if ks else None, "ex": ks[-2:]}; print("glm", res["glm_list"])
if ks:
    k, sz = ks[-1]; rr = get(f"https://noaa-goes19.s3.amazonaws.com/{k}")
    res["glm_download"] = {x: y for x, y in rr.items() if x != "body"}
    if "body" in rr:
        open(f"{OUT}/glm.nc", "wb").write(rr["body"])
        try:
            import h5py
            f = h5py.File(f"{OUT}/glm.nc", "r"); res["glm_vars"] = list(f.keys())
            res["glm_flash_lat"] = {"shape": f["flash_lat"].shape, "attrs": {a: str(f["flash_lat"].attrs[a]) for a in f["flash_lat"].attrs}}
        except Exception as e: res["glm_h5"] = repr(e)
        os.remove(f"{OUT}/glm.nc")
json.dump(res, open(f"{OUT}/res.json", "w"), indent=1, ensure_ascii=False, default=str)
