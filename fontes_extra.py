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


def astronomia_skyfield(lat, lon, data, fuso, pasta_efemerides=None):
    """Crepúsculos (civil −6°, náutico −12°), nascer/pôr do Sol e da Lua, fase e iluminação — efemérides JPL DE421.
    Noite operacional: FCVC (fim do crepúsculo vespertino civil) até ICMC (início do crepúsculo matutino civil) do dia seguinte;
    'luar' = Lua acima do horizonte (entre nascer e ocaso), 'visibilidade nula' = Lua abaixo do horizonte."""
    from skyfield import almanac
    from skyfield.api import Loader, wgs84
    load = Loader(pasta_efemerides or ".", verbose=False)
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


# ---------------------------------------------------------------------------
# INMET (apiprevmet3, público): avisos meteorológicos, previsão do município e estação mais próxima
# ---------------------------------------------------------------------------
def _norm(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn").strip()


def municipio_ibge(lat, lon, baixar, geocode=None):
    """Código IBGE do município da coordenada: informado na missão > reverso OSM (Nominatim) > sede mais próxima."""
    from municipios_br import MUNICIPIOS
    por_cod = {m[0]: m for m in MUNICIPIOS}
    if geocode:
        try:
            m = por_cod.get(int(geocode))
            if m:
                return {"geocode": m[0], "nome": m[1], "uf": m[4], "metodo": "informado na missão"}
        except ValueError:
            pass
    st, corpo = baixar(f"https://nominatim.openstreetmap.org/reverse?lat={lat:.5f}&lon={lon:.5f}&format=json&zoom=10&accept-language=pt-BR", tentativas=2, timeout=30)
    if st:
        try:
            a = json.loads(corpo).get("address", {})
            nome = a.get("city") or a.get("town") or a.get("municipality") or a.get("village")
            uf = (a.get("ISO3166-2-lvl4") or "")[-2:]
            if nome and uf:
                for m in MUNICIPIOS:
                    if m[4] == uf and _norm(m[1]) == _norm(nome):
                        return {"geocode": m[0], "nome": m[1], "uf": m[4], "metodo": "localização reversa (OpenStreetMap)"}
        except Exception:
            pass
    m = min(MUNICIPIOS, key=lambda x: _dist_km(lat, lon, x[2], x[3]))
    return {"geocode": m[0], "nome": m[1], "uf": m[4], "metodo": f"sede municipal mais próxima ({_dist_km(lat, lon, m[2], m[3]):.0f} km)"}


def _no_poligono(lat, lon, geo):
    """Ponto (lat, lon) dentro de Polygon/MultiPolygon GeoJSON (lon, lat)."""
    try:
        g = json.loads(geo) if isinstance(geo, str) else geo
    except Exception:
        return False
    polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates", []) if g.get("type") == "MultiPolygon" else []
    for poly in polys:
        anel = poly[0]
        dentro = False
        for i in range(len(anel)):
            x1, y1 = anel[i][0], anel[i][1]
            x2, y2 = anel[i - 1][0], anel[i - 1][1]
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1:
                dentro = not dentro
        if dentro:
            return True
    return False


def _lista(txt):
    if isinstance(txt, list):
        return txt
    try:
        import ast
        v = ast.literal_eval(txt)
        return v if isinstance(v, list) else [str(v)]
    except Exception:
        return [str(txt)] if txt else []


def inmet_prev(lat, lon, baixar, geocode=None):
    """Avisos do INMET que abrangem a coordenada, previsão do município (até 5 dias) e estação automática mais próxima."""
    base = "https://apiprevmet3.inmet.gov.br"
    out = {"fonte": "INMET — apiprevmet3 (avisos, previsão e estação mais próxima)", "url_avisos": "https://alertas2.inmet.gov.br/"}
    mun = municipio_ibge(lat, lon, baixar, geocode)
    out["municipio"] = mun
    gc = str(mun["geocode"])
    # avisos
    st, corpo = baixar(f"{base}/avisos/ativos", tentativas=2, timeout=60)
    if st:
        try:
            dados = json.loads(corpo)
            av = []
            for grupo in ("hoje", "futuro"):
                for a in dados.get(grupo, []) or []:
                    dentro = _no_poligono(lat, lon, a.get("poligono")) or gc in str(a.get("geocodes", "")).split(",")
                    if not dentro:
                        continue
                    av.append({"grupo": grupo, "id": a.get("id_aviso"), "descricao": a.get("descricao"), "severidade": a.get("severidade"),
                               "cor": a.get("aviso_cor"), "inicio": a.get("inicio"), "fim": a.get("fim"), "riscos": _lista(a.get("riscos")),
                               "instrucoes": _lista(a.get("instrucoes")), "estados": a.get("estados"), "codigo": a.get("codigo")})
            out["avisos"] = av
            out["avisos_total_pais"] = sum(len(dados.get(g, []) or []) for g in ("hoje", "futuro"))
        except Exception as e:
            out["avisos_erro"] = "leitura: " + repr(e)
    else:
        out["avisos_erro"] = str(corpo)[:200]
    # previsão do município
    st, corpo = baixar(f"{base}/previsao/{gc}", tentativas=2, timeout=60)
    if st:
        try:
            dias = json.loads(corpo).get(gc, {})
            prev = []
            for data_br, v in dias.items():
                d, m_, a_ = data_br.split("/")
                item = {"data": f"{a_}-{m_}-{d}"}
                limpa = lambda x: {k: val for k, val in x.items() if "icone" not in k}
                if isinstance(v, dict) and "manha" in v:
                    item["periodos"] = {p: limpa(v[p]) for p in ("manha", "tarde", "noite") if p in v}
                else:
                    item["dia"] = limpa(v)
                prev.append(item)
            out["previsao"] = prev
        except Exception as e:
            out["previsao_erro"] = "leitura: " + repr(e)
    else:
        out["previsao_erro"] = str(corpo)[:200]
    # estação automática mais próxima (última observação)
    st, corpo = baixar(f"{base}/estacao/proxima/{gc}", tentativas=2, timeout=45)
    if st:
        try:
            out["estacao"] = json.loads(corpo)
        except Exception as e:
            out["estacao_erro"] = "leitura: " + repr(e)
    return out


CPTEC_TEMPO = {"ec": "Encoberto com chuvas isoladas", "ci": "Chuvas isoladas", "c": "Chuva", "in": "Instável", "pp": "Possibilidade de pancadas de chuva",
               "cm": "Chuva pela manhã", "cn": "Chuva à noite", "pt": "Pancadas de chuva à tarde", "pm": "Pancadas de chuva pela manhã",
               "np": "Nublado e pancadas de chuva", "pc": "Pancadas de chuva", "pn": "Parcialmente nublado", "cv": "Chuvisco", "ch": "Chuvoso",
               "t": "Tempestade", "ps": "Predomínio de sol", "e": "Encoberto", "n": "Nublado", "cl": "Céu claro", "nv": "Nevoeiro", "g": "Geada",
               "ne": "Neve", "nd": "Não definido", "pnt": "Pancadas de chuva à noite", "psc": "Possibilidade de chuva", "pcm": "Possibilidade de chuva pela manhã",
               "pct": "Possibilidade de chuva à tarde", "pcn": "Possibilidade de chuva à noite", "npt": "Nublado com pancadas à tarde",
               "npn": "Nublado com pancadas à noite", "ncn": "Nublado com possibilidade de chuva à noite", "nct": "Nublado com possibilidade de chuva à tarde",
               "ncm": "Nublado com possibilidade de chuva pela manhã", "npm": "Nublado com pancadas pela manhã", "npp": "Nublado com possibilidade de chuva",
               "vn": "Variação de nebulosidade", "ct": "Chuva à tarde", "ppn": "Possibilidade de pancadas de chuva à noite",
               "ppt": "Possibilidade de pancadas de chuva à tarde", "ppm": "Possibilidade de pancadas de chuva pela manhã"}


def cptec(lat, lon, baixar):
    """Previsão CPTEC/INPE de até 7 dias para a cidade mais próxima da coordenada (serviço XML público)."""
    out = {"fonte": "CPTEC/INPE — previsão de 7 dias (serviço XML)"}
    st, corpo = baixar(f"http://servicos.cptec.inpe.br/XML/cidade/7dias/{lat:.2f}/{lon:.2f}/previsaoLatLon.xml", tentativas=2, timeout=45, binario=True)
    if not st:
        out["erro"] = str(corpo)[:200]
        return out
    corpo = corpo.decode("iso-8859-1", "replace") if isinstance(corpo, bytes) else corpo
    try:
        nome = re.search(r"<nome>(.*?)</nome>", corpo)
        uf = re.search(r"<uf>(.*?)</uf>", corpo)
        atu = re.search(r"<atualizacao>(.*?)</atualizacao>", corpo)
        out.update({"cidade": nome.group(1) if nome else None, "uf": uf.group(1) if uf else None, "atualizacao": atu.group(1) if atu else None})
        dias = []
        for p in re.findall(r"<previsao>(.*?)</previsao>", corpo, re.S):
            g = lambda k: (re.search(f"<{k}>(.*?)</{k}>", p) or [None, None])[1]
            cod = g("tempo")
            dias.append({"data": g("dia"), "tempo": cod, "descricao": CPTEC_TEMPO.get(cod, cod), "max": g("maxima"), "min": g("minima"), "iuv": g("iuv")})
        out["dias"] = dias
    except Exception as e:
        out["erro"] = "leitura: " + repr(e)
    return out


# ---------------- Radiossonda observada (University of Wyoming, formato CSV) ----------------
RADIOSSONDAS = [("83746", "SBGL — Galeão, Rio de Janeiro")]  # estações confirmadas no serviço


def radiossonda(lat, lon, baixar, agora=None, raio_km=300):
    """Sondagem observada mais recente (00Z/12Z) da estação mais próxima dentro do raio. Vento em kt, alturas em m MSL."""
    import datetime as _dt, math as _m
    agora = agora or _dt.datetime.now(_dt.timezone.utc)
    tent = []
    for d in range(0, 2):
        dia = (agora - _dt.timedelta(days=d)).date()
        for hh in (12, 0):
            t = _dt.datetime(dia.year, dia.month, dia.day, hh, tzinfo=_dt.timezone.utc)
            if t <= agora: tent.append(t)
    erros = []
    for wmo, nome in RADIOSSONDAS:
        for t in sorted(tent, reverse=True):
            u = f"https://weather.uwyo.edu/wsgi/sounding?datetime={t:%Y-%m-%d}%20{t:%H}:00:00&id={wmo}&type=TEXT:CSV&src=UNKNOWN"
            st, txt = baixar(u, tentativas=1, timeout=60)
            if not st or not str(txt).startswith("time,"):
                erros.append(f"{wmo} {t:%d/%H}Z: sem dados"); continue
            linhas = [l.split(",") for l in str(txt).strip().splitlines()[1:]]
            niv = []
            for c in linhas:
                try:
                    p, z = float(c[3]), float(c[4])
                    tt = float(c[5]) if c[5].strip() else None; td = float(c[6]) if c[6].strip() else None
                    dd = float(c[11]) if c[11].strip() else None; ff = float(c[12]) if c[12].strip() else None
                except (ValueError, IndexError):
                    continue
                if p < 300: break
                niv.append([p, round(z), tt, td, dd, None if ff is None else round(ff * 1.943844, 1)])
            if not niv: continue
            # mantém todos os níveis até 3.000 m e um a cada ~250 m acima
            red, ult = [], -1e9
            for n in niv:
                if n[1] <= 3000 or n[1] - ult >= 250: red.append(n); ult = n[1]
            la, lo = float(linhas[0][2]), float(linhas[0][1])
            r = _m.pi / 180
            dist = 6371 * 2 * _m.asin(_m.sqrt(_m.sin((la - lat) * r / 2) ** 2 + _m.cos(lat * r) * _m.cos(la * r) * _m.sin((lo - lon) * r / 2) ** 2))
            if dist > raio_km:
                erros.append(f"{wmo}: {dist:.0f} km da ZL (fora do raio)"); break
            return {"fonte": "University of Wyoming — radiossonda observada", "estacao": wmo, "nome": nome, "lat": la, "lon": lo, "dist_km": round(dist, 1),
                    "nominal_utc": t.isoformat(), "lancamento_utc": linhas[0][0].strip().replace(" ", "T") + "Z", "url": u,
                    "colunas": ["p_hPa", "z_m_MSL", "t_C", "td_C", "dir_graus_V", "vel_kt"], "niveis": red}
    return {"erro": "; ".join(erros) or "nenhuma estação no raio"}
