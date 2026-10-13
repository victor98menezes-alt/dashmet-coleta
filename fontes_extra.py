"""Fontes complementares: astronomia (Skyfield/JPL + USNO), INMET (estações automáticas) e REDEMET (OPMET)."""
import datetime as dt
import json
import math
import os
import re
import urllib.parse
from zoneinfo import ZoneInfo


def _hm(t, tz):
    return t.utc_datetime().astimezone(ZoneInfo(tz)).strftime("%Y-%m-%dT%H:%M")


def astronomia_skyfield(lat, lon, data, fuso):
    """Crepúsculo náutico (Sol a -12°), nascer/pôr da Lua, iluminação e altura máxima — efemérides JPL DE421."""
    from skyfield import almanac
    from skyfield.api import load, wgs84
    ts = load.timescale()
    eph = load("de421.bsp")
    loc = wgs84.latlon(lat, lon)
    z = ZoneInfo(fuso)
    d0 = dt.date.fromisoformat(data)
    out = {"fonte": "Skyfield + efemérides JPL DE421 (NASA)", "dias": {}}
    terra, sol, lua = eph["earth"], eph["sun"], eph["moon"]
    obs = terra + loc
    for k in (-1, 0, 1):
        dia = d0 + dt.timedelta(days=k)
        a = dt.datetime.combine(dia, dt.time(0), z)
        t0, t1 = ts.from_datetime(a), ts.from_datetime(a + dt.timedelta(days=1))
        f = almanac.dark_twilight_day(eph, loc)
        t, e = almanac.find_discrete(t0, t1, f)
        icmn = fcvn = None
        prev = int(f(t0))
        for ti, ei in zip(t, e):
            if prev == 1 and ei == 2:  # astronômico -> náutico (manhã)
                icmn = _hm(ti, fuso)
            if prev == 2 and ei == 1:  # náutico -> astronômico (tarde)
                fcvn = _hm(ti, fuso)
            prev = int(ei)
        f2 = almanac.risings_and_settings(eph, lua, loc)
        t, e = almanac.find_discrete(t0, t1, f2)
        nasc = [_hm(ti, fuso) for ti, ei in zip(t, e) if ei]
        poe = [_hm(ti, fuso) for ti, ei in zip(t, e) if not ei]
        meio = ts.from_datetime(a + dt.timedelta(hours=12))
        ilum = almanac.fraction_illuminated(eph, "moon", meio)
        out["dias"][dia.isoformat()] = {"icmn": icmn, "fcvn": fcvn, "lua_nasce": nasc, "lua_poe": poe, "iluminacao_meio_dia": round(float(ilum) * 100, 1)}
    # noites D-1→D e D→D+1: intervalos de Lua acima do horizonte durante a noite náutica
    noites = []
    for k in (-1, 0):
        da, db = (d0 + dt.timedelta(days=k)).isoformat(), (d0 + dt.timedelta(days=k + 1)).isoformat()
        ini, fim = out["dias"][da]["fcvn"], out["dias"][db]["icmn"]
        if not ini or not fim:
            continue
        ti_ = ts.from_datetime(dt.datetime.fromisoformat(ini).replace(tzinfo=z))
        tf_ = ts.from_datetime(dt.datetime.fromisoformat(fim).replace(tzinfo=z))
        n = 241
        passos = [ti_ + (tf_ - ti_) * i / (n - 1) for i in range(n)]
        alts = [obs.at(p).observe(lua).apparent().altaz()[0].degrees for p in passos]
        acima = [bool(h > 0) for h in alts]
        intervalos, inicio = [], 0
        for i in range(1, n + 1):
            if i == n or acima[i] != acima[inicio]:
                intervalos.append({"de": _hm(passos[inicio], fuso), "ate": _hm(passos[i - 1] if i == n else passos[i], fuso), "lua": bool(acima[inicio])})
                inicio = i
        meio = ti_ + (tf_ - ti_) * 0.5
        noites.append({"de": ini, "ate": fim, "intervalos": intervalos, "alt_max_lua": round(float(max(alts)), 1),
                       "iluminacao": round(float(almanac.fraction_illuminated(eph, "moon", meio)) * 100, 1)})
    out["noites"] = noites
    return out


def usno(lat, lon, data, fuso, baixar):
    """USNO (Observatório Naval dos EUA): nascer/pôr da Lua, crepúsculo civil, fase e iluminação para o dia D."""
    d = dt.datetime.fromisoformat(f"{data}T12:00").replace(tzinfo=ZoneInfo(fuso))
    off = d.utcoffset().total_seconds() / 3600
    url = f"https://aa.usno.navy.mil/api/rstt/oneday?date={data}&coords={lat:.4f},{lon:.4f}&tz={off:g}"
    st, corpo = baixar(url, tentativas=2, timeout=45)
    if not st:
        return {"fonte": "USNO", "url": url, "erro": corpo}
    try:
        p = json.loads(corpo)["properties"]["data"]
        return {"fonte": "USNO — U.S. Naval Observatory (API rstt)", "url": url, "data": data,
                "lua": {x["phen"]: x["time"] for x in p.get("moondata", [])}, "sol": {x["phen"]: x["time"] for x in p.get("sundata", [])},
                "fase": p.get("curphase"), "iluminacao": p.get("fracillum")}
    except Exception as e:
        return {"fonte": "USNO", "url": url, "erro": "formato inesperado: " + repr(e)}


def _dist_km(a, b, c, d):
    r = math.pi / 180
    h = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def inmet(lat, lon, baixar, token, raio_km=120, max_est=3):
    """Estações automáticas do INMET mais próximas e últimas 24 h de observação (dados exigem token do INMET)."""
    out = {"fonte": "INMET — estações automáticas", "estacoes": [], "token": bool(token)}
    st, corpo = baixar("https://apitempo.inmet.gov.br/estacoes/T", tentativas=2, timeout=60)
    if not st:
        out["erro"] = "lista de estações indisponível: " + str(corpo)[:200]
        return out
    lista = []
    for e in json.loads(corpo):
        try:
            if e.get("CD_SITUACAO") != "Operante":
                continue
            la, lo = float(e["VL_LATITUDE"]), float(e["VL_LONGITUDE"])
            dk = _dist_km(lat, lon, la, lo)
            if dk <= raio_km:
                lista.append({"codigo": e["CD_ESTACAO"], "nome": e["DC_NOME"].title(), "uf": e["SG_ESTADO"], "lat": la, "lon": lo,
                              "altitude_m": float(e["VL_ALTITUDE"] or 0), "dist_km": round(dk, 1)})
        except Exception:
            continue
    lista.sort(key=lambda x: x["dist_km"])
    out["estacoes"] = lista[:max_est]
    if not token:
        out["aviso"] = "Dados das estações exigem token do INMET (secret INMET_TOKEN não configurado)."
        return out
    hoje = dt.datetime.now(dt.timezone.utc).date()
    ini = (hoje - dt.timedelta(days=1)).isoformat()
    for est in out["estacoes"]:
        url = f"https://apitempo.inmet.gov.br/token/estacao/{ini}/{hoje.isoformat()}/{est['codigo']}/{urllib.parse.quote(token)}"
        st, corpo = baixar(url, tentativas=2, timeout=60)
        if not st or not corpo.strip().startswith("["):
            est["erro"] = (str(corpo) or "sem dados")[:120].replace(token, "***")
            continue
        obs = []
        for r in json.loads(corpo)[-24:]:
            def f(k):
                v = r.get(k)
                try:
                    return None if v in (None, "") else float(v)
                except ValueError:
                    return None
            ms = f("VEN_VEL"); raj = f("VEN_RAJ")
            obs.append({"utc": f"{r.get('DT_MEDICAO')}T{str(r.get('HR_MEDICAO', '')).zfill(4)[:2]}:00Z", "temp": f("TEM_INS"), "td": f("PTO_INS"),
                        "ur": f("UMD_INS"), "pressao": f("PRE_INS"), "chuva_mm": f("CHUVA"), "vento_dir": f("VEN_DIR"),
                        "vento_kt": None if ms is None else round(ms * 1.943844, 1), "rajada_kt": None if raj is None else round(raj * 1.943844, 1)})
        est["observacoes"] = obs
    return out


def _mensagens(obj, saida):
    if isinstance(obj, str):
        for m in re.findall(r"((?:METAR|SPECI|TAF)\b[^=]+)=?", obj):
            saida.append(re.sub(r"\s+", " ", m).strip())
    elif isinstance(obj, dict):
        for v in obj.values():
            _mensagens(v, saida)
    elif isinstance(obj, list):
        for v in obj:
            _mensagens(v, saida)


def redemet(icao, baixar, chave):
    """REDEMET (DECEA): METAR/SPECI das últimas 6 h e TAF da localidade (exige API key)."""
    out = {"fonte": "REDEMET — API DECEA", "chave": bool(chave), "icao": icao}
    if not chave:
        out["aviso"] = "API REDEMET exige chave (secret REDEMET_API_KEY não configurado)."
        return out
    if not icao:
        out["aviso"] = "Estação OACI não informada na missão."
        return out
    agora = dt.datetime.now(dt.timezone.utc)
    ini = (agora - dt.timedelta(hours=6)).strftime("%Y%m%d%H")
    fim = agora.strftime("%Y%m%d%H")
    for tipo in ("metar", "taf"):
        q = {"api_key": chave, "data_ini": ini, "data_fim": fim}
        url = f"https://api-redemet.decea.mil.br/mensagens/{tipo}/{icao}?" + urllib.parse.urlencode(q)
        st, corpo = baixar(url, tentativas=2, timeout=45)
        if not st:
            out[tipo + "_erro"] = str(corpo)[:200].replace(chave, "***")
            continue
        msgs = []
        try:
            _mensagens(json.loads(corpo), msgs)
        except Exception:
            _mensagens(corpo, msgs)
        out[tipo + "s"] = list(dict.fromkeys(m for m in msgs if m.startswith(("METAR", "SPECI") if tipo == "metar" else ("TAF",))))
    return out
