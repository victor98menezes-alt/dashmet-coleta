"""Coleta meteorológica para o Dashboard Meteorológico de Salto.

Executado pelo GitHub Actions (workflow "Coleta meteorológica").
Entradas por variável de ambiente: LAT, LON, DATA (AAAA-MM-DD), HORA (0-23, local), FUSO (IANA), RUN_ID.
Saída em saida/<RUN_ID>/: openmeteo.json, sondagem.txt, meta.json.
Somente biblioteca padrão do Python.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

UA = "DashboardMeteorologicoSalto/1.0 (uso institucional nao comercial)"
# Janela H a H+5: quatro centros; ECMWF com superfície do IFS HRES 9 km (ecmwf_ifs) e níveis do IFS 0,25°
MODELOS = ["gfs_seamless", "ecmwf_ifs025", "ecmwf_ifs", "icon_seamless", "ukmo_global_deterministic_10km"]
# Tendência D a D+7: modelos de alcance >= 7 dias, só superfície
MODELOS7 = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"]
SUPERFICIE7 = ["temperature_2m", "precipitation", "showers", "precipitation_probability", "pressure_msl", "wind_speed_10m",
               "wind_direction_10m", "wind_gusts_10m", "cape", "weather_code", "cloud_cover"]
META_RODADA = {"GFS": "ncep_gfs013", "ECMWF": "ecmwf_ifs", "ICON": "dwd_icon", "UKMO": "ukmo_global_deterministic_10km"}
SUPERFICIE = ["temperature_2m", "apparent_temperature", "dew_point_2m", "precipitation_probability", "precipitation", "showers",
              "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
              "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "cape", "pressure_msl", "visibility",
              "wind_speed_80m", "wind_direction_80m", "wind_speed_120m", "wind_direction_120m", "wind_speed_180m", "wind_direction_180m",
              "freezing_level_height", "lifted_index", "weather_code"]
NIVEIS = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300]
VARS_NIVEL = ["wind_speed", "wind_direction", "geopotential_height", "temperature", "relative_humidity", "cloud_cover"]
MESES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def falha(msg):
    print("ERRO:", msg, file=sys.stderr)
    sys.exit(1)


def entradas():
    lat, lon = os.environ.get("LAT", ""), os.environ.get("LON", "")
    data, hora = os.environ.get("DATA", ""), os.environ.get("HORA", "")
    fuso, run_id = os.environ.get("FUSO", "America/Sao_Paulo"), os.environ.get("RUN_ID", "")
    icao = os.environ.get("ICAO", "").strip().upper()
    ads = [x for x in re.split(r"[ ,;]+", os.environ.get("AERODROMOS", "").strip().upper()) if x]
    if any(not re.match(r"^[A-Z0-9]{4}$", x) for x in ads) or len(ads) > 4:
        falha("lista de aeródromos inválida (até 4 códigos OACI)")
    if icao and not re.match(r"^[A-Z]{4}$", icao):
        falha("ICAO inválido")
    num = re.compile(r"^-?\d{1,3}(\.\d+)?$")
    if not num.match(lat) or not num.match(lon):
        falha("latitude/longitude inválidas")
    lat, lon = float(lat), float(lon)
    if abs(lat) > 90 or abs(lon) > 180:
        falha("coordenada fora dos limites")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", data):
        falha("data inválida")
    if not re.match(r"^\d{1,2}$", hora) or int(hora) > 23:
        falha("hora inválida")
    if not re.match(r"^[A-Za-z_]+(/[A-Za-z_+\-]+)*$", fuso):
        falha("fuso inválido")
    ZoneInfo(fuso)
    if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", run_id):
        falha("run_id inválido")
    return lat, lon, data, int(hora), fuso, run_id, icao, ads


def baixar(url, tentativas=3, timeout=60, binario=False):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                dados = r.read()
                return r.status, (dados if binario else dados.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            corpo = e.read()[:500].decode("utf-8", "replace")
            erro = f"HTTP {e.code}: {corpo}"
            if e.code < 500:
                break
        except Exception as e:  # rede, timeout
            erro = repr(e)
        time.sleep(5 * (i + 1))
    return None, erro


def url_open_meteo(lat, lon, data, fuso, tipo="janela", hora=0):
    """tipo 'janela': somente o dia D (D+1 só se H+5 passar da meia-noite), quatro modelos, superfície + níveis;
    'tendencia': D a D+7, três modelos, superfície."""
    d = dt.date.fromisoformat(data)
    jan = tipo != "tendencia"
    hourly = (list(SUPERFICIE) + [f"{v}_{p}hPa" for p in NIVEIS for v in VARS_NIVEL]) if jan else list(SUPERFICIE7)
    q = {
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "hourly": ",".join(hourly),
        "models": ",".join(MODELOS if jan else MODELOS7), "wind_speed_unit": "kn", "timezone": fuso,
        "start_date": d.isoformat(), "end_date": (d + dt.timedelta(days=(1 if int(hora or 0) + 5 >= 24 else 0) if jan else 7)).isoformat(),
    }
    return "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q, safe=",/")


def rodadas(baixar_fn):
    """Hora de inicialização da última rodada de cada modelo da janela (metadados públicos da Open-Meteo)."""
    out = {}
    for mid, nome in META_RODADA.items():
        st, corpo = baixar_fn(f"https://api.open-meteo.com/data/{nome}/static/meta.json", tentativas=2, timeout=30)
        try:
            j = json.loads(corpo) if st else {}
            out[mid] = {"init_utc": j.get("last_run_initialisation_time"), "disponivel_utc": j.get("last_run_availability_time"), "intervalo_s": j.get("update_interval_seconds")}
        except Exception:
            out[mid] = {"erro": str(corpo)[:120]}
    return out


def url_sondagem(lat, lon, quando_utc=None):
    q = {"data_source": "GFS", "n_hrs": "1", "fcst_len": "shortest", "airport": f"{lat:.3f},{lon:.3f}",
         "text": "Ascii text (GSD format)", "hydrometeors": "false"}
    if quando_utc is None:
        q.update({"latest": "latest", "start": "latest"})
    else:
        q.update({"start_year": str(quando_utc.year), "start_month_name": MESES[quando_utc.month - 1],
                  "start_mday": str(quando_utc.day), "start_hour": str(quando_utc.hour), "start_min": "0"})
    return "https://rucsoundings.noaa.gov/get_soundings.cgi?" + urllib.parse.urlencode(q)


NIVEIS_SONDAGEM = [1000, 975, 950, 925, 900, 850, 800, 750, 700, 650, 600, 550, 500, 450, 400, 350, 300, 250]


def ciclos_gfs(h_utc):
    """Ciclos GFS candidatos (mais recente primeiro) que cobrem h_utc com prazo <= 120 h, publicados há pelo menos 4 h."""
    agora = dt.datetime.now(dt.timezone.utc)
    c = agora.replace(minute=0, second=0, microsecond=0)
    c = c.replace(hour=c.hour - c.hour % 6)
    out = []
    for _ in range(6):
        if c <= agora - dt.timedelta(hours=4):
            f = int((h_utc - c).total_seconds() // 3600)
            if 0 <= f <= 120:
                out.append((c, f))
        c -= dt.timedelta(hours=6)
    return out


def url_nomads(ciclo, f, lat, lon):
    q = [("dir", f"/gfs.{ciclo:%Y%m%d}/{ciclo:%H}/atmos"), ("file", f"gfs.t{ciclo:%H}z.pgrb2.0p25.f{f:03d}")]
    q += [(f"var_{v}", "on") for v in ("HGT", "TMP", "RH", "UGRD", "VGRD")]
    q += [(f"lev_{p}_mb", "on") for p in NIVEIS_SONDAGEM]
    lon360 = lon % 360
    q += [("subregion", ""), ("toplat", f"{lat + 0.5:.2f}"), ("bottomlat", f"{lat - 0.5:.2f}"),
          ("leftlon", f"{lon360 - 0.5:.2f}"), ("rightlon", f"{lon360 + 0.5:.2f}")]
    return "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?" + urllib.parse.urlencode(q)


def grib_para_gsd(caminho, lat, lon, ciclo, f):
    """Lê o GRIB2 recortado e gera texto no formato GSD (o mesmo da página rucsoundings)."""
    import math
    import eccodes
    dados = {}
    ponto = None
    with open(caminho, "rb") as fh:
        while True:
            g = eccodes.codes_grib_new_from_file(fh)
            if g is None:
                break
            try:
                sn = eccodes.codes_get(g, "shortName")
                lev = eccodes.codes_get(g, "level")
                nn = eccodes.codes_grib_find_nearest(g, lat, lon % 360)[0]
                ponto = ponto or (nn["lat"], nn["lon"], nn["distance"])
                dados.setdefault(lev, {})[sn] = nn["value"]
            finally:
                eccodes.codes_release(g)
    linhas = [f"GFS 0.25 NOMADS ciclo {ciclo:%Y-%m-%d %H}Z prazo f{f:03d} valido {ciclo + dt.timedelta(hours=f):%Y-%m-%d %H}Z",
              f"ponto de grade {ponto[0]:.2f},{(ponto[1] + 180) % 360 - 180:.2f} ({ponto[2]:.1f} km)" if ponto else "",
              "      3           GFS                  12     kt"]
    for p in sorted(dados, reverse=True):
        d = dados[p]
        if not all(k in d for k in ("gh", "t", "u", "v")):
            continue
        tc = d["t"] - 273.15
        rh = max(1.0, min(100.0, d.get("r", 50.0)))
        a, b = 17.625, 243.04
        gm = math.log(rh / 100) + a * tc / (b + tc)
        td = b * gm / (a - gm)
        u, v = d["u"], d["v"]
        kt = math.hypot(u, v) * 1.943844
        di = (math.degrees(math.atan2(-u, -v)) + 360) % 360
        linhas.append(f"      4 {round(p * 10):6d} {round(d['gh']):6d} {round(tc * 10):6d} {round(td * 10):6d} {round(di) % 360 or 360:6d} {round(kt):6d}")
    return "\n".join(linhas) + "\n"


def tem_niveis(txt):
    return bool(txt) and len(re.findall(r"^\s*[4-9]\s+-?\d+\s+-?\d+", txt, re.M)) >= 3


def main():
    lat, lon, data, hora, fuso, run_id, icao, ads = entradas()
    pasta = os.path.join("saida", run_id)
    os.makedirs(pasta, exist_ok=True)
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    meta = {"run_id": run_id, "coletado_em_utc": agora, "lat": lat, "lon": lon, "data": data, "hora_local": hora, "fuso": fuso, "fontes": {}}

    # Open-Meteo: GFS + ECMWF + ICON, superfície e níveis de pressão
    u = url_open_meteo(lat, lon, data, fuso, "janela", hora)
    st, corpo = baixar(u)
    meta["fontes"]["openmeteo"] = {"url": u, "status": st, "erro": None if st else corpo}
    if st:
        open(os.path.join(pasta, "openmeteo.json"), "w", encoding="utf-8").write(corpo)
    u7 = url_open_meteo(lat, lon, data, fuso, "tendencia")
    st7, corpo7 = baixar(u7)
    meta["fontes"]["openmeteo7"] = {"url": u7, "status": st7, "erro": None if st7 else corpo7}
    if st7:
        open(os.path.join(pasta, "openmeteo7.json"), "w", encoding="utf-8").write(corpo7)
    meta["rodadas"] = rodadas(baixar)

    # Sondagem NOAA (GFS, formato GSD): horário H em UTC (arredondado para baixo a múltiplo de 3 h); se vazio, a mais recente
    h_local = dt.datetime.fromisoformat(f"{data}T{hora:02d}:00").replace(tzinfo=ZoneInfo(fuso))
    h_utc = h_local.astimezone(dt.timezone.utc)
    h_utc = h_utc.replace(hour=h_utc.hour - h_utc.hour % 3, minute=0, second=0, microsecond=0)
    tentativas = []
    # 1) NOAA NOMADS — GFS 0,25° em níveis de pressão, prazo que cobre H
    h_exato = h_local.astimezone(dt.timezone.utc)
    for ciclo, f in ciclos_gfs(h_exato)[:3]:
        u2 = url_nomads(ciclo, f, lat, lon)
        st2, corpo2 = baixar(u2, tentativas=2, timeout=90, binario=True)
        ok, erro = False, None
        if st2 and corpo2[:4] == b"GRIB":
            caminho = os.path.join(pasta, "gfs_nomads.grib2")
            open(caminho, "wb").write(corpo2)
            try:
                txt = grib_para_gsd(caminho, lat, lon, ciclo, f)
                ok = tem_niveis(txt)
                if ok:
                    open(os.path.join(pasta, "sondagem.txt"), "w", encoding="utf-8").write(txt)
            except Exception as e:
                erro = "decodificação: " + repr(e)
            finally:
                os.remove(caminho)
        else:
            erro = corpo2 if not st2 else "resposta não é GRIB (arquivo ainda não publicado?)"
        tentativas.append({"fonte": "NOAA NOMADS GFS 0.25", "url": u2, "status": st2, "ciclo_utc": ciclo.isoformat(), "prazo_h": f,
                           "valido_para_utc": h_exato.replace(minute=0).isoformat(), "niveis": ok, "erro": erro})
        if ok:
            break
    # 2) NOAA rucsoundings (alternativa)
    if not any(t["niveis"] for t in tentativas):
        for quando in (h_utc, None):
            u2 = url_sondagem(lat, lon, quando)
            st2, corpo2 = baixar(u2, tentativas=1, timeout=45)
            ok = bool(st2) and tem_niveis(corpo2)
            tentativas.append({"fonte": "NOAA rucsoundings", "url": u2, "status": st2, "valido_para_utc": quando.isoformat() if quando else "latest",
                               "niveis": ok, "erro": None if st2 else corpo2})
            if ok:
                open(os.path.join(pasta, "sondagem.txt"), "w", encoding="utf-8").write(corpo2)
                break
    meta["fontes"]["sondagem_noaa"] = tentativas

    # Fontes complementares
    import fontes_extra as fx
    extra = {"coletado_em_utc": agora, "lat": lat, "lon": lon, "data": data, "fuso": fuso}
    try:
        extra["skyfield"] = fx.astronomia_skyfield(lat, lon, data, fuso)
    except Exception as e:
        extra["skyfield"] = {"erro": repr(e)}
    extra["usno"] = fx.usno(lat, lon, data, fuso, baixar)
    json.dump(extra, open(os.path.join(pasta, "astro.json"), "w", encoding="utf-8"), ensure_ascii=False)
    try:
        ob = {"coletado_em_utc": agora, "lat": lat, "lon": lon, "inmet": fx.inmet(lat, lon, baixar, os.environ.get("INMET_TOKEN", "")),
              "redemet": fx.redemet(icao, baixar, os.environ.get("REDEMET_API_KEY", ""))}
    except Exception as e:
        ob = {"coletado_em_utc": agora, "erro": repr(e)}
    for k, f in (("inmet_prev", lambda: fx.inmet_prev(lat, lon, baixar, os.environ.get("IBGE") or None)), ("cptec", lambda: fx.cptec(lat, lon, baixar))):
        try:
            ob[k] = f()
        except Exception as e:
            ob[k] = {"erro": repr(e)}
    json.dump(ob, open(os.path.join(pasta, "obs_oficiais.json"), "w", encoding="utf-8"), ensure_ascii=False)
    # AISWEB: ROTAER, distâncias declaradas, cartas IAC, METAR/TAF e RCR dos aeródromos da missão (e da estação de referência)
    import aisweb
    lista = list(dict.fromkeys(ads + ([icao] if icao else [])))
    aer = {"coletado_em_utc": agora, "aerodromos": {}}
    for c in lista:
        st3, corpo3 = baixar(f"https://aisweb.decea.mil.br/?i=aerodromos&codigo={c}", tentativas=2, timeout=60)
        if not st3:
            aer["aerodromos"][c] = {"icao": c, "erro": str(corpo3)[:200]}
            continue
        try:
            aer["aerodromos"][c] = aisweb.ler(corpo3, c)
        except Exception as e:
            aer["aerodromos"][c] = {"icao": c, "erro": "leitura: " + repr(e)}
    json.dump(aer, open(os.path.join(pasta, "aerodromos.json"), "w", encoding="utf-8"), ensure_ascii=False)
    meta["fontes"]["aisweb"] = {c: ("erro" not in v) for c, v in aer["aerodromos"].items()}
    meta["fontes"]["astronomia"] = {"skyfield": "erro" not in extra["skyfield"], "usno": "erro" not in extra["usno"]}
    meta["fontes"]["inmet"] = {k: v for k, v in ob.get("inmet", {}).items() if k != "estacoes"}
    meta["fontes"]["redemet"] = {k: v for k, v in ob.get("redemet", {}).items() if k not in ("metars", "tafs")}

    json.dump(meta, open(os.path.join(pasta, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if not st and not any(t["niveis"] for t in tentativas):
        falha("nenhuma fonte respondeu")


if __name__ == "__main__":
    main()
