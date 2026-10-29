"""Convecção atual por satélite: GOES-19 (ABI canal 13, 10,3 µm — temperatura de brilho do topo das nuvens) e
GLM (descargas elétricas), dados públicos da NOAA na AWS (noaa-goes19). Recorte em torno da ZL.

Limiares de topo frio: −32 °C e −52 °C (critérios de Maddox, 1980, para escudo de nuvens de sistemas convectivos).
Saída compacta (JSON) para o dashboard: grade de temperatura de brilho (°C, 0,04°) em base64, descargas recentes e estatísticas."""
import base64, datetime as dt, json, math, re, tempfile, os, urllib.request
from concurrent.futures import ThreadPoolExecutor

BUCKET = "https://noaa-goes19.s3.amazonaws.com"
UA = "DashboardMeteorologicoSalto/1.0 (uso institucional nao comercial)"
RAIO_GRADE = 2.0   # graus em torno da ZL
PASSO = 0.04       # graus (~4,4 km)


def _get(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
        return r.read()


def _listar(prefixo):
    t = _get(f"{BUCKET}/?list-type=2&prefix={prefixo}&max-keys=1000", 60).decode()
    return re.findall(r"<Key>([^<]+)</Key>", t)


def _inicio(chave):
    m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})", chave)
    y, j, h, mi, s = map(int, m.groups())
    return dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=j - 1, hours=h, minutes=mi, seconds=s)


def _chaves(produto, fim, horas=2):
    out = []
    for k in range(horas, -1, -1):
        t = fim - dt.timedelta(hours=k)
        out += _listar(f"{produto}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/")
    return sorted(set(out), key=_inicio)


def dist_km(a, b, c, d):
    r = math.pi / 180
    h = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def rumo(a, b, c, d):
    r = math.pi / 180
    y = math.sin((d - b) * r) * math.cos(c * r)
    x = math.cos(a * r) * math.sin(c * r) - math.sin(a * r) * math.cos(c * r) * math.cos((d - b) * r)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _abi_tb(caminho, lats, lons):
    """Temperatura de brilho (K) do canal 13 nos pontos lat/lon (vizinho mais próximo na grade fixa do GOES)."""
    import h5py, numpy as np
    with h5py.File(caminho, "r") as f:
        pr = f["goes_imager_projection"].attrs
        req, rpol = float(pr["semi_major_axis"][0]), float(pr["semi_minor_axis"][0])
        H = float(pr["perspective_point_height"][0]) + req
        lon0 = math.radians(float(pr["longitude_of_projection_origin"][0]))
        xs, xo = float(f["x"].attrs["scale_factor"][0]), float(f["x"].attrs["add_offset"][0])
        ys, yo = float(f["y"].attrs["scale_factor"][0]), float(f["y"].attrs["add_offset"][0])
        e2 = (req ** 2 - rpol ** 2) / req ** 2
        la, lo = np.radians(lats), np.radians(lons)
        phic = np.arctan((rpol ** 2 / req ** 2) * np.tan(la))
        rc = rpol / np.sqrt(1 - e2 * np.cos(phic) ** 2)
        sx = H - rc * np.cos(phic) * np.cos(lo - lon0)
        sy = -rc * np.cos(phic) * np.sin(lo - lon0)
        sz = rc * np.sin(phic)
        y = np.arctan(sz / sx)
        x = np.arcsin(-sy / np.sqrt(sx ** 2 + sy ** 2 + sz ** 2))
        col = np.rint((x - xo) / xs).astype(int)
        lin = np.rint((y - yo) / ys).astype(int)
        c0, c1, l0, l1 = col.min(), col.max() + 1, lin.min(), lin.max() + 1
        v = f["CMI"]
        raw = v[l0:l1, c0:c1].astype("int64") & 0xFFFF   # inteiro sem sinal (_Unsigned)
        sc, of = float(v.attrs["scale_factor"][0]), float(v.attrs["add_offset"][0])
        tb = np.where(raw > 4095, np.nan, raw * sc + of)
        return tb[lin - l0, col - c0]


def _resumo_tb(lat, lon, tb, glat, glon):
    import numpy as np
    d = np.vectorize(dist_km)(lat, lon, glat, glon)
    out = {}
    c = tb - 273.15
    def menor(r):
        m = d <= r
        return None if not np.any(m & ~np.isnan(c)) else round(float(np.nanmin(np.where(m, c, np.nan))), 1)
    i0 = np.unravel_index(np.nanargmin(np.where(np.isnan(d), np.inf, d)), d.shape)
    out["tb_zl_c"] = None if np.isnan(c[i0]) else round(float(c[i0]), 1)
    out["tb_min_10km_c"], out["tb_min_30km_c"], out["tb_min_100km_c"] = menor(10), menor(30), menor(100)
    for lim in (-32, -52):
        m = (c <= lim) & ~np.isnan(c)
        k = f"frio{abs(lim)}"
        if not np.any(m):
            out[k] = None; continue
        dd = np.where(m, d, np.inf); j = np.unravel_index(np.argmin(dd), d.shape)
        r30, r100 = d <= 30, d <= 100
        out[k] = {"dist_km": round(float(dd[j]), 1), "rumo": round(rumo(lat, lon, float(glat[j]), float(glon[j]))),
                  "frac_30km": round(float(np.sum(m & r30) / max(1, np.sum(r30))), 3), "frac_100km": round(float(np.sum(m & r100) / max(1, np.sum(r100))), 3)}
    return out


def abi(lat, lon, agora=None):
    """Recorte do canal 13 mais recente e de ~30 min antes (para a tendência de aproximação)."""
    import numpy as np
    agora = agora or dt.datetime.now(dt.timezone.utc)
    ks = _chaves("ABI-L2-CMIPF", agora, 1)
    ks = [k for k in ks if "M6C13" in k or "C13_" in k]
    if not ks:
        return {"erro": "nenhum arquivo ABI C13 recente"}
    atual = ks[-1]; t1 = _inicio(atual)
    ant = [k for k in ks if 20 <= (t1 - _inicio(k)).total_seconds() / 60 <= 45]
    n = int(round(2 * RAIO_GRADE / PASSO)) + 1
    glat = np.array([[lat + RAIO_GRADE - i * PASSO for _ in range(n)] for i in range(n)])
    glon = np.array([[lon - RAIO_GRADE + j * PASSO for j in range(n)] for _ in range(n)])
    res = {"fonte": "NOAA GOES-19 ABI L2 CMIPF, canal 13 (10,3 µm), AWS noaa-goes19", "grade": {"lat0": lat + RAIO_GRADE, "lon0": lon - RAIO_GRADE, "passo": PASSO, "n": n}}
    def proc(chave):
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as fp:
            fp.write(_get(f"{BUCKET}/{chave}", 300)); nome = fp.name
        try:
            return _abi_tb(nome, glat, glon)
        finally:
            os.remove(nome)
    with ThreadPoolExecutor(2) as ex:
        fut = {"atual": ex.submit(proc, atual)}
        if ant: fut["ant"] = ex.submit(proc, ant[-1])
        tbs = {k: f.result() for k, f in fut.items()}
    tb = tbs["atual"]
    res["arquivo"] = atual.split("/")[-1]; res["inicio_utc"] = t1.isoformat()
    res.update(_resumo_tb(lat, lon, tb, glat, glon))
    c = np.where(np.isnan(tb), 255, np.clip(np.rint(tb - 273.15 + 100), 0, 254)).astype("uint8")  # °C + 100; 255 = sem dado
    res["grade"]["tb_c_mais_100_b64"] = base64.b64encode(c.tobytes()).decode()
    if "ant" in tbs:
        ta = _inicio(ant[-1]); ra = _resumo_tb(lat, lon, tbs["ant"], glat, glon)
        res["anterior"] = {"inicio_utc": ta.isoformat(), "frio32": ra.get("frio32"), "frio52": ra.get("frio52"), "tb_min_30km_c": ra.get("tb_min_30km_c")}
        dtm = (t1 - ta).total_seconds() / 3600
        for k in ("frio32", "frio52"):
            a, b = ra.get(k), res.get(k)
            if a and b and dtm > 0:
                v = (a["dist_km"] - b["dist_km"]) / dtm   # km/h, positivo = aproximando
                res[k]["aprox_kmh"] = round(v, 1)
                if v > 3 and b["dist_km"] > 0:
                    res[k]["eta_min"] = round(b["dist_km"] / v * 60)
    return res


def glm(lat, lon, minutos=20, agora=None, raio_lista_km=150):
    """Descargas (flashes) do GLM nos últimos 'minutos', em torno da ZL."""
    import h5py, numpy as np
    agora = agora or dt.datetime.now(dt.timezone.utc)
    ks = _chaves("GLM-L2-LCFA", agora, 1)
    if not ks:
        return {"erro": "nenhum arquivo GLM recente"}
    tfim = _inicio(ks[-1])
    sel = [k for k in ks if (tfim - _inicio(k)).total_seconds() <= minutos * 60]
    def proc(chave):
        b = _get(f"{BUCKET}/{chave}", 120)
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as fp:
            fp.write(b); nome = fp.name
        try:
            with h5py.File(nome, "r") as f:
                la = f["flash_lat"][:].astype(float); lo = f["flash_lon"][:].astype(float)
                q = f["flash_quality_flag"][:] if "flash_quality_flag" in f else np.zeros(len(la))
                t0 = _inicio(chave)
                return [(float(a), float(o), t0) for a, o, qq in zip(la, lo, q) if qq == 0 and abs(a - lat) <= 3 and abs(o - lon) <= 3]
        finally:
            os.remove(nome)
    with ThreadPoolExecutor(8) as ex:
        fl = [x for r in ex.map(proc, sel) for x in r]
    out = {"fonte": "NOAA GOES-19 GLM L2 LCFA (flashes, qualidade boa), AWS noaa-goes19", "janela_min": minutos, "arquivos": len(sel),
           "inicio_utc": _inicio(sel[0]).isoformat() if sel else None, "fim_utc": tfim.isoformat()}
    D = [(dist_km(lat, lon, a, o), a, o, t) for a, o, t in fl]
    for r in (10, 30, 50, 100):
        out[f"n_{r}km"] = sum(1 for d, *_ in D if d <= r)
    if D:
        d, a, o, t = min(D, key=lambda x: x[0])
        out["mais_proximo"] = {"dist_km": round(d, 1), "rumo": round(rumo(lat, lon, a, o)), "utc": t.isoformat()}
        meio = tfim - dt.timedelta(minutes=minutos / 2)
        out["n_100km_1a_metade"] = sum(1 for d, a, o, t in D if d <= 100 and t < meio)
        out["n_100km_2a_metade"] = sum(1 for d, a, o, t in D if d <= 100 and t >= meio)
    out["flashes"] = [[round(a, 3), round(o, 3), round((tfim - t).total_seconds() / 60, 1)] for d, a, o, t in sorted(D)[:1500] if d <= raio_lista_km]
    return out


def coletar(lat, lon):
    res = {"coletado_em_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "lat": lat, "lon": lon}
    for nome, fn in (("abi", abi), ("glm", glm)):
        try:
            res[nome] = fn(lat, lon)
        except Exception as e:
            res[nome] = {"erro": repr(e)[:300]}
    return res


if __name__ == "__main__":
    import sys
    r = coletar(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps({k: ({kk: vv for kk, vv in v.items() if kk not in ("grade", "flashes")} if isinstance(v, dict) else v) for k, v in r.items()}, ensure_ascii=False, indent=1))
    if len(sys.argv) > 3: json.dump(r, open(sys.argv[3], "w"), ensure_ascii=False)
