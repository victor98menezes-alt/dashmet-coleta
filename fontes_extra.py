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
    """Crepúsculos (civil −6°, náutico −12°), nascer/pôr do Sol e da Lua, fase e iluminação — efemérides JPL DE421.
    Noite operacional: FCVC (fim do crepúsculo vespertino civil) até ICMC (início do crepúsculo matutino civil) do dia seguinte;
    'luar' = Lua acima do horizonte (entre nascer e ocaso), 'visibilidade nula' = Lua abaixo do horizonte."""
    from skyfield import almanac
    from skyfield.api import load, wgs84
    ts = load.timescale()
    eph = load("de421.bsp")
    loc = wgs84.latlon(lat, lon)
    z = ZoneInfo(fuso)
    d0 = dt.date.fromisoformat(data)
    out = {"fonte": "Skyfield + efemérides JPL DE421 (NASA)", "dias": {}}
    lua = eph["moon"]
    fl = almanac.risings_and_settings(eph, lua, loc)
    for k in (-1, 0, 1, 2):
        dia = d0 + dt.timedelta(days=k)
        a = dt.datetime.combine(dia, dt.time(0), z)
        t0, t1 = ts.from_datetime(a), ts.from_datetime(a + dt.timedelta(days=1))
        f = almanac.dark_twilight_day(eph, loc)
        t, e = almanac.find_discrete(t0, t1, f)
        ev = {}
        prev = int(f(t0))
        for ti, ei in zip(t, e):
            ei = int(ei)
            if prev == 1 and ei == 2: ev["icmn"] = _hm(ti, fuso)
            if prev == 2 and ei == 3: ev["icmc"] = _hm(ti, fuso)
            if prev == 3 and ei == 4: ev["nascer_sol"] = _hm(ti, fuso)
            if prev == 4 and ei == 3: ev["por_sol"] = _hm(ti, fuso)
            if prev == 3 and ei == 2: ev["fcvc"] = _hm(ti, fuso)
            if prev == 2 and ei == 1: ev["fcvn"] = _hm(ti, fuso)
            prev = ei
        t, e = almanac.find_discrete(t0, t1, fl)
        ev["lua_nasce"] = [_hm(ti, fuso) for ti, ei in zip(t, e) if ei]
        ev["lua_poe"] = [_hm(ti, fuso) for ti, ei in zip(t, e) if not ei]
        meio = ts.from_datetime(a + dt.timedelta(hours=12))
        ev["iluminacao_meio_dia"] = round(float(almanac.fraction_illuminated(eph, "moon", meio)) * 100, 1)
        ph = float(almanac.moon_phase(eph, meio).degrees)
        ev["fase_graus"] = round(ph, 1)
        out["dias"][dia.isoformat()] = ev
    noites = []
    for k in (-1, 0, 1):
        da, db = (d0 + dt.timedelta(days=k)).isoformat(), (d0 + dt.timedelta(days=k + 1)).isoformat()
        ini, fim = out["dias"][da].get("fcvc"), out["dias"][db].get("icmc")
        if not ini or not fim:
            continue
        ti_ = ts.from_datetime(dt.datetime.fromisoformat(ini).replace(tzinfo=z))
        tf_ = ts.from_datetime(dt.datetime.fromisoformat(fim).replace(tzinfo=z))
        up = bool(fl(ti_))
        t, e = almanac.find_discrete(ti_, tf_, fl)
        intervalos, cur = [], ini
        for ti, ei in zip(t, e):
            intervalos.append({"de": cur, "ate": _hm(ti, fuso), "lua": up})
            cur, up = _hm(ti, fuso), bool(ei)
        intervalos.append({"de": cur, "ate": fim, "lua": up})
        intervalos = [x for x in intervalos if x["de"] != x["ate"]]
        obs = eph["earth"] + loc
        n = 121
        passos = [ti_ + (tf_ - ti_) * i / (n - 1) for i in range(n)]
        alts = [float(obs.at(p).observe(lua).apparent().altaz()[0].degrees) for p in passos]
        imax = max(range(n), key=lambda i: alts[i])
        meio = ti_ + (tf_ - ti_) * 0.5
        noites.append({"de": ini, "ate": fim, "fcvn": out["dias"][da].get("fcvn"), "icmn": out["dias"][db].get("icmn"),
                       "intervalos": intervalos, "alt_max_lua": round(alts[imax], 1), "hora_alt_max": _hm(passos[imax], fuso),
                       "iluminacao": round(float(almanac.fraction_illuminated(eph, "moon", meio)) * 100, 1)})
    out["noites"] = noites
    out["definicao"] = "Noite: FCVC (Sol a −6°, fim do crepúsculo vespertino civil) até ICMC do dia seguinte. Luar: Lua acima do horizonte; visibilidade nula: Lua abaixo do horizonte."
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
