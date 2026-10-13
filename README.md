# Coleta meteorológica — ponte do Dashboard Meteorológico de Salto

Este repositório busca, sob demanda, os dados de modelo que o dashboard não consegue buscar sozinho:

- **Open-Meteo**: GFS (NOAA/NCEP), ECMWF IFS 0,25° e ICON (DWD), em superfície e de 1000 a 300 hPa, de D-1 a D+1, com vento em nós.
- **Sondagem NOAA**: GFS 0,25° do servidor oficial NOMADS (ciclo mais recente que cubra H, níveis de 1000 a 250 hPa, ponto de grade mais próximo). Alternativa: rucsoundings.noaa.gov.

- **Astronomia**: Skyfield com efemérides JPL DE421 (NASA) — ICMN/FCVN (Sol a −12°), nascer/pôr da Lua, iluminação, períodos de luar — conferida com a API da USNO (U.S. Naval Observatory).
- **INMET**: estações automáticas operantes a até 120 km (lista pública). Os dados horários exigem token do INMET — secret `INMET_TOKEN`.
- **REDEMET**: METAR/SPECI (6 h) e TAF da estação OACI da missão pela API do DECEA — exige chave, secret `REDEMET_API_KEY`.
- Time and Date bloqueia acesso automatizado (Cloudflare); fica como conferência manual.

## Secrets (Settings → Secrets and variables → Actions → New repository secret)

| Nome | Origem |
|---|---|
| `REDEMET_API_KEY` | Chave da API REDEMET fornecida pelo DECEA |
| `INMET_TOKEN` | Token da API de estações fornecido pelo INMET |

## Fluxo

1. O Claude lê a missão salva no dashboard.
2. Ele dispara o workflow **Coleta meteorológica** com latitude, longitude, data, H e fuso.
3. O GitHub Actions executa `coleta.py` e depois `transforma.js`, e grava o resultado em `saida/<run_id>/`.
4. O Claude lê `modelos.json` e `sondagem.json` e os grava no dashboard.

## Arquivos de cada coleta

| Arquivo | Conteúdo |
|---|---|
| `meta.json` | URLs consultadas, horário da coleta (UTC), status HTTP, erros e resultado da conversão |
| `openmeteo.json` | Resposta bruta da Open-Meteo |
| `sondagem.txt` | Texto bruto da sondagem NOAA |
| `modelos.json` / `sondagem.json` | Dados já no formato do dashboard |

O repositório mantém apenas as 30 coletas mais recentes.

## Cuidados

- **Repositório privado.** As coordenadas das missões ficam gravadas aqui.
- **Termos da Open-Meteo.** A API gratuita é restrita a uso não comercial. Confirmar se o uso institucional se enquadra; caso contrário, contratar a chave da API comercial.
- **Teste manual.** Aba Actions → Coleta meteorológica → Run workflow.
