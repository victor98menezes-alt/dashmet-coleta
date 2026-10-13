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
MODELOS = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"]
SUPERFICIE = ["temperature_2m", "dew_point_2m", "precipitation_probability", "precipitation", "showers",
              "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
              "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "cape", "pressure_msl"]
NIVEIS = [1000, 925, 850, 700, 600, 500, 400, 300]
VARS_NIVEL = ["wind_speed", "wind_direction", "geopotential_height", "temperature"]
MESES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def falha(msg):
    print("ERRO:", msg, file=sys.stderr)
    sys.exit(1)


def entradas():
    lat, lon = os.environ.get("LAT", ""), os.environ.get("LON", "")
    data, hora = os.environ.get("DATA", ""), os.environ.get("HORA", "")
    fuso, run_id = os.environ.get("FUSO", "America/Sao_Paulo"), os.environ.get("RUN_ID", "")
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
    return lat, lon, data, int(hora), fuso, run_id


def baixar(url, tentativas=3):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")[:500]
            erro = f"HTTP {e.code}: {corpo}"
            if e.code < 500:
                break
        except Exception as e:  # rede, timeout
            erro = repr(e)
        time.sleep(5 * (i + 1))
    return None, erro


def url_open_meteo(lat, lon, data, fuso):
    d = dt.date.fromisoformat(data)
    hourly = list(SUPERFICIE) + [f"{v}_{p}hPa" for p in NIVEIS for v in VARS_NIVEL]
    q = {
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "hourly": ",".join(hourly),
        "models": ",".join(MODELOS), "wind_speed_unit": "kn", "timezone": fuso,
        "start_date": (d - dt.timedelta(days=1)).isoformat(), "end_date": (d + dt.timedelta(days=1)).isoformat(),
    }
    return "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q, safe=",/")


def url_sondagem(lat, lon, quando_utc=None):
    q = {"data_source": "GFS", "n_hrs": "1", "fcst_len": "shortest", "airport": f"{lat:.3f},{lon:.3f}",
         "text": "Ascii text (GSD format)", "hydrometeors": "false"}
    if quando_utc is None:
        q.update({"latest": "latest", "start": "latest"})
    else:
        q.update({"start_year": str(quando_utc.year), "start_month_name": MESES[quando_utc.month - 1],
                  "start_mday": str(quando_utc.day), "start_hour": str(quando_utc.hour), "start_min": "0"})
    return "https://rucsoundings.noaa.gov/get_soundings.cgi?" + urllib.parse.urlencode(q)


def tem_niveis(txt):
    return bool(txt) and len(re.findall(r"^\s*[4-9]\s+-?\d+\s+-?\d+", txt, re.M)) >= 3


def main():
    lat, lon, data, hora, fuso, run_id = entradas()
    pasta = os.path.join("saida", run_id)
    os.makedirs(pasta, exist_ok=True)
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    meta = {"run_id": run_id, "coletado_em_utc": agora, "lat": lat, "lon": lon, "data": data, "hora_local": hora, "fuso": fuso, "fontes": {}}

    # Open-Meteo: GFS + ECMWF + ICON, superfície e níveis de pressão
    u = url_open_meteo(lat, lon, data, fuso)
    st, corpo = baixar(u)
    meta["fontes"]["openmeteo"] = {"url": u, "status": st, "erro": None if st else corpo}
    if st:
        open(os.path.join(pasta, "openmeteo.json"), "w", encoding="utf-8").write(corpo)

    # Sondagem NOAA (GFS, formato GSD): horário H em UTC (arredondado para baixo a múltiplo de 3 h); se vazio, a mais recente
    h_local = dt.datetime.fromisoformat(f"{data}T{hora:02d}:00").replace(tzinfo=ZoneInfo(fuso))
    h_utc = h_local.astimezone(dt.timezone.utc)
    h_utc = h_utc.replace(hour=h_utc.hour - h_utc.hour % 3, minute=0, second=0, microsecond=0)
    tentativas = []
    for quando in (h_utc, None):
        u2 = url_sondagem(lat, lon, quando)
        st2, corpo2 = baixar(u2)
        ok = bool(st2) and tem_niveis(corpo2)
        tentativas.append({"url": u2, "status": st2, "valido_para_utc": quando.isoformat() if quando else "latest", "niveis": ok,
                           "erro": None if st2 else corpo2})
        if ok:
            open(os.path.join(pasta, "sondagem.txt"), "w", encoding="utf-8").write(corpo2)
            break
    meta["fontes"]["sondagem_noaa"] = tentativas

    json.dump(meta, open(os.path.join(pasta, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if not st and not any(t["niveis"] for t in tentativas):
        falha("nenhuma fonte respondeu")


if __name__ == "__main__":
    main()
