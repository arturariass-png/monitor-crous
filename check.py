#!/usr/bin/env python3
"""
Vigila la pagina de presa de claus del CROUS amb un navegador real
(Playwright) i avisa per Telegram si apareix un horari anterior a la
cita que ja tens reservada.
"""

import json
import os
import pathlib
import re
import sys
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

URL = os.environ.get("URL", "").strip()
LIMIT = os.environ.get("LIMIT", "2026-09-02 12:15").strip()

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

ESTAT = pathlib.Path("estat.json")

MESOS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aout": 8, "août": 8, "sept": 9, "oct": 10, "nov": 11,
    "dec": 12, "déc": 12,
}

AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

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
    """Obre la pagina amb un navegador real i espera que el JS la dibuixi."""
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        context = navegador.new_context(
            locale="fr-FR",
            user_agent=AGENT,
            viewport={"width": 1400, "height": 1200},
        )
        pagina = context.new_page()

        pagina.goto(URL, wait_until="networkidle", timeout=90_000)

        # Espera fins a 30 s que aparegui la frase que ens interessa.
        text = ""
        for _ in range(15):
            text = re.sub(r"\s+", " ", pagina.inner_text("body")).strip()
            if PATRO.search(text) or "creneau" in text.lower() or "créneau" in text.lower():
                break
            pagina.wait_for_timeout(2_000)

        print(f"[navegador] {len(text)} caracters de text visible")
        navegador.close()
        return text


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
            print(f"[diagnostic] Text rebut: {text[:1500]}")
            return 1

        print("Pagina correcta, pero no anuncia cap proper horari lliure.")
        print(f"[diagnostic] {text[:1500]}")
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
