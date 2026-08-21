#!/usr/bin/env python3
"""
Vigila la pagina de presa de claus del CROUS i avisa per Telegram
si apareix un horari anterior a la cita que ja tens reservada.

Es basa en la linia "Prochain rendez-vous le XX mois a HH:MM" que la
propia web mostra a dalt a la dreta.
"""

import json
import os
import pathlib
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

URL = os.environ.get("URL", "").strip()
COOKIE = os.environ.get("COOKIE", "").strip()
LIMIT = os.environ.get("LIMIT", "2026-09-02 12:15").strip()

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

ESTAT = pathlib.Path("estat.json")

MESOS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aout": 8, "août": 8, "sept": 9, "oct": 10, "nov": 11,
    "dec": 12, "déc": 12,
}

CAPCALERES = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,ca;q=0.8,es;q=0.7",
}

PATRO = re.compile(
    r"[Pp]rochain\s+rendez-?vous\s+le\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\.?\s+"
    r"[àa]\s+(\d{1,2})\s*[h:]\s*(\d{2})",
    re.IGNORECASE,
)


def avisa(missatge: str) -> None:
    print(missatge, flush=True)
    if not (TOKEN and CHAT_ID):
        print("[avis] Sense credencials de Telegram: nomes al log.", flush=True)
        return
    resposta = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": missatge},
        timeout=30,
    )
    if not resposta.ok:
        print(f"[error] Telegram: {resposta.status_code} {resposta.text}")


def descarrega() -> str:
    capcaleres = dict(CAPCALERES)
    if COOKIE:
        capcaleres["Cookie"] = COOKIE
    resposta = requests.get(URL, headers=capcaleres, timeout=45)
    resposta.raise_for_status()
    sopa = BeautifulSoup(resposta.text, "html.parser")
    for etiqueta in sopa(["script", "style", "noscript"]):
        etiqueta.decompose()
    return re.sub(r"\s+", " ", sopa.get_text(" ", strip=True))


def interpreta_data(dia: str, mes: str, hora: str, minut: str) -> datetime:
    clau = mes.lower()[:4].rstrip(".")
    numero_mes = MESOS.get(clau) or MESOS.get(clau[:3])
    if not numero_mes:
        raise ValueError(f"Mes desconegut: {mes!r}")

    ara = datetime.now()
    any_ = ara.year if numero_mes >= ara.month else ara.year + 1
    return datetime(any_, numero_mes, int(dia), int(hora), int(minut))


def main() -> int:
    if not URL:
        print("[error] Falta la variable URL.")
        return 1

    limit = datetime.strptime(LIMIT, "%Y-%m-%d %H:%M")
    estat = json.loads(ESTAT.read_text()) if ESTAT.exists() else {}
    text = descarrega()

    coincidencia = PATRO.search(text)

    # --- Comprovacio que hem rebut la pagina bona ------------------------
    if not coincidencia:
        minuscules = text.lower()
        pagina_valida = any(
            marca in minuscules
            for marca in ("creneau", "créneau", "rendez-vous", "semaine")
        )

        if not pagina_valida:
            if estat.get("pagina_ok") is not False:
                avisa(
                    "L'AGENT NO VEU EL CALENDARI\n\n"
                    "La pagina no ha retornat el contingut esperat. Pot ser un "
                    "bloqueig de la IP, un manteniment del CROUS o un canvi "
                    "a la web. Mira el log de GitHub Actions."
                )
            estat["pagina_ok"] = False
            ESTAT.write_text(json.dumps(estat, ensure_ascii=False, indent=2))
            print(f"[diagnostic] Text rebut: {text[:800]}")
            return 1

        print("Pagina correcta, pero no anuncia cap proper horari lliure.")
        print(f"[diagnostic] {text[:800]}")
        estat["pagina_ok"] = True
        ESTAT.write_text(json.dumps(estat, ensure_ascii=False, indent=2))
        return 0

    estat["pagina_ok"] = True
    proxima = interpreta_data(*coincidencia.groups())
    etiqueta = proxima.strftime("%d/%m/%Y a les %H:%M")
    print(f"Proper horari lliure: {etiqueta}  (limit: {limit:%d/%m/%Y %H:%M})")

    if proxima < limit:
        if estat.get("ultima_avisada") != proxima.isoformat():
            avisa(
                f"HI HA UN HORARI MES AVIAT!\n\n"
                f"Proper lliure: {etiqueta}\n"
                f"La teva cita actual: {limit:%d/%m/%Y a les %H:%M}\n\n"
                f"{URL}"
            )
            estat["ultima_avisada"] = proxima.isoformat()
        else:
            print("Ja t'havia avisat d'aquest mateix horari.")
    else:
        print("Res mes aviat que la teva cita.")
        estat.pop("ultima_avisada", None)

    estat["ultima_comprovacio"] = datetime.now().isoformat(timespec="minutes")
    estat["proper_lliure"] = proxima.isoformat()
    ESTAT.write_text(json.dumps(estat, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}")
        sys.exit(1)
