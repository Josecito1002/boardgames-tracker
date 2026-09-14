from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import os
import re
import smtplib
import ssl
import time
import urllib.request
from playwright.sync_api import sync_playwright

# Variables de entorno leídas desde GitHub Secrets
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or "5171466462"
FB_COOKIES = os.environ.get("FB_COOKIES")

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS")

# Enlaces prioritarios a revisar primero
URLS_PRIORITARIAS = [
    "https://www.facebook.com/share/1Ljt24Gr7u/",
    "https://www.facebook.com/share/1Hp3k4feUm/",
]

PALABRAS_MUEBLES = [
    "comedor",
    "tocador",
    "cabecera",
    "mesa de noche",
    "mesas de noche",
    "mesa de centro",
    "silla",
    "sillas",
    "mueble",
    "muebles",
    "sala",
    "ropero",
    "closet",
    "cocina",
]


def es_mueble(texto):
  t = texto.lower()
  if any(m in t for m in PALABRAS_MUEBLES):
    if not any(
        j in t
        for j in [
            "catan",
            "cartas",
            "tablero",
            "bgg",
            "hasbro",
            "devir",
            "monopoly",
            "carcassonne",
            "clue",
            "basta",
            "splendor",
            "dixit",
            "risk",
            "terra mystica",
        ]
    ):
      return True
  return False


def tg_send(texto):
  """Notificación ligera de estado por Telegram (opcional)."""
  if not TG_TOKEN or not CHAT_ID:
    return None
  try:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
      return json.loads(r.read()).get("result", {}).get("message_id")
  except Exception as e:
    print(f"Error tg_send: {e}", flush=True)
    return None


def enviar_publicacion_correo(iid, url_post, texto_post, ruta_img=None):
  """Envía los detalles de la publicación y la captura a Gmail para su análisis."""
  if not GMAIL_USER or not GMAIL_APP_PASS:
    print(
        "Aviso: GMAIL_USER o GMAIL_APP_PASS no configurados. Omitiendo envío.",
        flush=True,
    )
    return False

  try:
    asunto = f"[Marketplace Scraper] Publicación ID {iid}"
    msg = MIMEMultipart("related")
    msg["Subject"] = asunto
    msg["From"] = f"Marketplace Scraper <{GMAIL_USER}>"
    msg["To"] = GMAIL_USER

    html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #222;">
            <h2>🎲 Nueva publicación detectada: ID {iid}</h2>
            <p><b>Enlace directo:</b> <a href="{url_post}">{url_post}</a></p>
            <hr>
            <h3>Texto y descripción de la publicación:</h3>
            <pre style="background: #f4f4f4; padding: 12px; border-radius: 6px; white-space: pre-wrap; font-size: 14px;">{texto_post}</pre>
        """

    if ruta_img and os.path.exists(ruta_img):
      html_content += """
            <br>
            <h3>Captura de pantalla:</h3>
            <p><img src="cid:captura_marketplace" style="max-width: 650px; border: 1px solid #ccc; border-radius: 4px;"></p>
            """

    html_content += """
          </body>
        </html>
        """

    msg_alt = MIMEMultipart("alternative")
    msg.attach(msg_alt)
    msg_alt.attach(MIMEText(html_content, "html", "utf-8"))

    if ruta_img and os.path.exists(ruta_img):
      with open(ruta_img, "rb") as f:
        img = MIMEImage(f.read())
        img.add_header("Content-ID", "<captura_marketplace>")
        img.add_header(
            "Content-Disposition",
            "inline",
            filename=os.path.basename(ruta_img),
        )
        msg.attach(img)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
      server.login(GMAIL_USER, GMAIL_APP_PASS)
      server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())

    print(f"📧 Correo enviado para ID {iid}.", flush=True)
    return True
  except Exception as e:
    print(f"Error al enviar correo: {e}", flush=True)
    return False


def raspar():
  vistos = set()
  if os.path.exists("vistos.json"):
    try:
      with open("vistos.json", "r", encoding="utf-8") as f:
        vistos = set(json.load(f))
    except Exception:
      pass

  url_busqueda = "https://www.facebook.com/marketplace/mixco-guatemala/search/?query=juegos%20de%20mesa"
  tg_send(
      "📡 <b>Iniciando búsqueda en Marketplace...</b>\nExtrayendo publicaciones"
      " hacia Gmail."
  )

  with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
        locale="es-GT",
        geolocation={"latitude": 14.6333, "longitude": -90.6064},
        permissions=["geolocation"],
    )

    if FB_COOKIES:
      try:
        cks = []
        for c in json.loads(FB_COOKIES):
          ck = {
              "name": c["name"],
              "value": c["value"],
              "domain": c.get("domain", ".facebook.com"),
              "path": c.get("path", "/"),
          }
          ss = str(c.get("sameSite", "")).lower()
          if ss == "strict":
            ck["sameSite"] = "Strict"
          elif ss == "lax":
            ck["sameSite"] = "Lax"
          elif ss in ["no_restriction", "none"]:
            ck["sameSite"] = "None"
            ck["secure"] = True
          elif c.get("secure"):
            ck["secure"] = True
          cks.append(ck)
        ctx.add_cookies(cks)
        print("✅ Cookies inyectadas.", flush=True)
      except Exception as e:
        print("Error cookies:", e, flush=True)

    page = ctx.new_page()
    items_enviados = 0

    # 1. PUBLICACIONES PRIORITARIAS
    for idx, url_prio in enumerate(URLS_PRIORITARIAS, 1):
      print(
          f"\n[PRIORITARIO {idx}/{len(URLS_PRIORITARIAS)}] Abriendo:"
          f" {url_prio}",
          flush=True,
      )
      try:
        page.goto(url_prio, timeout=35000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        real_url = page.url
        m = re.search(r"/item/(\d+)", real_url)
        iid = m.group(1) if m else f"prio_{idx}"

        try:
          ver_mas = page.query_selector(
              'div[role="main"] div[role="button"]:has-text("Ver más")'
          )
          if ver_mas:
            ver_mas.click()
            page.wait_for_timeout(500)
        except Exception:
          pass

        main_el = page.query_selector('div[role="main"]')
        texto_completo = (
            main_el.inner_text() if main_el else page.inner_text("body")
        )

        ruta_captura = f"captura_{iid}.png"
        page.screenshot(path=ruta_captura)

        if enviar_publicacion_correo(
            iid, real_url, texto_completo, ruta_captura
        ):
          vistos.add(iid)
          items_enviados += 1

        if os.path.exists(ruta_captura):
          os.remove(ruta_captura)
        time.sleep(5)
      except Exception as e_prio:
        print(
            f"Error en publicación prioritaria {url_prio}: {e_prio}", flush=True
        )

    # 2. BARRIDO GENERAL EN MARKETPLACE
    try:
      print("\nCargando Marketplace...", flush=True)
      page.goto(url_busqueda, timeout=45000, wait_until="domcontentloaded")
      page.wait_for_timeout(3000)

      try:
        page.keyboard.press("Escape")
        for s in [
            '[aria-label="Cerrar"]',
            '[aria-label="Close"]',
            'div[role="button"]:has-text("Ahora no")',
        ]:
          btn = page.query_selector(s)
          if btn:
            btn.click()
            page.wait_for_timeout(400)
      except Exception:
        pass

      for _ in range(5):
        page.evaluate("window.scrollBy(0, 1500)")
        page.wait_for_timeout(1800)

      enlaces = page.query_selector_all(
          'a[href*="/marketplace/item/"], a[href*="/item/"]'
      )
      iids_pendientes = []
      for a in enlaces:
        href = a.get_attribute("href") or ""
        txt = a.inner_text().strip()
        m = re.search(r"/item/(\d+)", href)
        if m:
          iid = m.group(1)
          if (
              iid not in vistos
              and iid not in iids_pendientes
              and not es_mueble(txt)
          ):
            iids_pendientes.append(iid)

      total_a_revisar = min(len(iids_pendientes), 15)
      print(f"Publicaciones a procesar: {total_a_revisar}...", flush=True)

      for idx, iid in enumerate(iids_pendientes[:total_a_revisar], 1):
        post_url = f"https://www.facebook.com/marketplace/item/{iid}/"
        print(f"[{idx}/{total_a_revisar}] Abriendo ID {iid}...", flush=True)

        try:
          page.goto(post_url, timeout=20000, wait_until="domcontentloaded")
          page.wait_for_timeout(2000)

          try:
            ver_mas = page.query_selector(
                'div[role="main"] div[role="button"]:has-text("Ver más")'
            )
            if ver_mas:
              ver_mas.click()
              page.wait_for_timeout(400)
          except Exception:
            pass

          main_el = page.query_selector('div[role="main"]')
          texto_completo = (
              main_el.inner_text() if main_el else page.inner_text("body")
          )

          if es_mueble(texto_completo):
            vistos.add(iid)
            continue

          ruta_captura = f"captura_{iid}.png"
          page.screenshot(path=ruta_captura)

          if enviar_publicacion_correo(
              iid, post_url, texto_completo, ruta_captura
          ):
            vistos.add(iid)
            items_enviados += 1

          if os.path.exists(ruta_captura):
            os.remove(ruta_captura)
        except Exception as ep:
          print(f"Error procesando ID {iid}: {ep}", flush=True)

        time.sleep(5)

      tg_send(
          f"✅ <b>Barrido completado.</b>\nSe enviaron {items_enviados}"
          " publicaciones a Gmail para registro en Google Sheets."
      )
    except Exception as e:
      print(f"Error general: {e}", flush=True)
      tg_send(f"❌ <b>Error:</b> {e}")
    finally:
      b.close()

  with open("vistos.json", "w", encoding="utf-8") as f:
    json.dump(list(vistos), f, indent=2)


if __name__ == "__main__":
  raspar()
      
