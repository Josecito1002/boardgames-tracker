from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import glob
import json
import os
import re
import smtplib
import ssl
import time
import urllib.request
from PIL import Image
from playwright.sync_api import sync_playwright
import pytesseract

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or "5171466462"
FB_COOKIES = os.environ.get("FB_COOKIES")

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS")

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


def limpiar_texto_marketplace(texto_crudo):
  """Corta la basura de 'Sugerencias de hoy' y datos innecesarios."""
  t = texto_crudo
  for corte in [
      "Sugerencias de hoy",
      "Información del vendedor",
      "Búsquedas relacionadas",
  ]:
    if corte in t:
      t = t.split(corte)[0]
  return t.strip()


def extraer_texto_de_imagenes(rutas_imgs):
  """Aplica OCR local a las fotos para extraer listas escritas o precios."""
  texto_acumulado = []
  for idx, ruta in enumerate(rutas_imgs, 1):
    try:
      txt = pytesseract.image_to_string(Image.open(ruta), lang="spa").strip()
      if len(txt) > 20:  # Solo incluir si contiene texto significativo
        texto_acumulado.append(f"--- FOTO {idx} ---\n{txt}")
    except Exception as e:
      print(f"Aviso OCR en {ruta}: {e}", flush=True)
  return "\n\n".join(texto_acumulado)


def enviar_publicacion_correo(
    iid, url_post, texto_post, rutas_imgs=[], texto_ocr=""
):
  if not GMAIL_USER or not GMAIL_APP_PASS:
    print("Aviso: GMAIL no configurado.", flush=True)
    return False

  try:
    asunto = f"[Marketplace Scraper] Publicación ID {iid}"
    msg = MIMEMultipart("related")
    msg["Subject"] = asunto
    msg["From"] = f"Marketplace Scraper <{GMAIL_USER}>"
    msg["To"] = GMAIL_USER

    seccion_ocr = ""
    if texto_ocr:
      seccion_ocr = f"""
            <h3>Texto detectado dentro de las imágenes (OCR):</h3>
            <pre style="background: #eef4fb; padding: 12px; border-radius: 6px; white-space: pre-wrap; font-size: 14px;">{texto_ocr}</pre>
            <hr>
            """

    html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #222;">
            <h2>🎲 Publicación detectada: ID {iid}</h2>
            <p><b>Enlace:</b> <a href="{url_post}">{url_post}</a></p>
            <hr>
            <h3>Descripción limpia de la publicación:</h3>
            <pre style="background: #f4f4f4; padding: 12px; border-radius: 6px; white-space: pre-wrap; font-size: 14px;">{texto_post}</pre>
            <hr>
            {seccion_ocr}
            <h3>Fotos reales de la publicación ({len(rutas_imgs)} imágenes adjuntas):</h3>
        """

    for i in range(len(rutas_imgs)):
      html_content += f'<p><img src="cid:foto_{i}" style="max-width: 600px; border: 1px solid #ccc; border-radius: 4px; margin-bottom: 8px;"></p>'

    html_content += "</body></html>"

    msg_alt = MIMEMultipart("alternative")
    msg.attach(msg_alt)
    msg_alt.attach(MIMEText(html_content, "html", "utf-8"))

    # Adjuntar cada foto real
    for i, ruta in enumerate(rutas_imgs):
      if os.path.exists(ruta):
        with open(ruta, "rb") as f:
          img = MIMEImage(f.read())
          img.add_header("Content-ID", f"<foto_{i}>")
          img.add_header(
              "Content-Disposition",
              "inline",
              filename=os.path.basename(ruta),
          )
          msg.attach(img)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
      server.login(GMAIL_USER, GMAIL_APP_PASS)
      server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())

    print(f"📧 Correo enviado para ID {iid} con {len(rutas_imgs)} fotos.")
    return True
  except Exception as e:
    print(f"Error al enviar correo: {e}", flush=True)
    return False


def descargar_fotos_reales(page, iid):
  """Recorre el carrusel de Marketplace y descarga las imágenes originales."""
  rutas = []
  urls_vistas = set()

  for idx in range(8):  # Hasta 8 fotos por publicación
    try:
      # Buscar la imagen principal activa en el visor
      img_el = page.query_selector(
          'div[role="main"] div[data-visualcompletion="media-vc-image"] img'
      ) or page.query_selector('div[role="main"] img')
      if img_el:
        src = img_el.get_attribute("src")
        if src and src.startswith("http") and src not in urls_vistas:
          urls_vistas.add(src)
          ruta_archivo = f"foto_{iid}_{idx+1}.jpg"
          urllib.request.urlretrieve(src, ruta_archivo)
          rutas.append(ruta_archivo)

      # Intentar avanzar a la siguiente foto del carrusel
      btn_next = page.query_selector(
          'div[role="main"] [aria-label="Siguiente"], div[role="main"]'
          ' [aria-label="Next"], div[role="main"] [aria-label="Foto siguiente"]'
      )
      if btn_next and btn_next.is_visible():
        btn_next.click()
        page.wait_for_timeout(600)
      else:
        break
    except Exception:
      break

  return rutas


def raspar():
  vistos = set()
  if os.path.exists("vistos.json"):
    try:
      with open("vistos.json", "r", encoding="utf-8") as f:
        vistos = set(json.load(f))
    except Exception:
      pass

  url_busqueda = "https://www.facebook.com/marketplace/mixco-guatemala/search/?query=juegos%20de%20mesa"

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
            page.wait_for_timeout(400)
        except Exception:
          pass

        main_el = page.query_selector('div[role="main"]')
        texto_crudo = (
            main_el.inner_text() if main_el else page.inner_text("body")
        )
        texto_limpio = limpiar_texto_marketplace(texto_crudo)

        # Descargar fotos reales del carrusel y aplicar OCR
        fotos = descargar_fotos_reales(page, iid)
        texto_ocr = extraer_texto_de_imagenes(fotos) if fotos else ""

        if enviar_publicacion_correo(
            iid, real_url, texto_limpio, fotos, texto_ocr
        ):
          vistos.add(iid)

        # Limpiar archivos locales
        for f in fotos:
          if os.path.exists(f):
            os.remove(f)
        time.sleep(5)
      except Exception as e_prio:
        print(
            f"Error en publicación prioritaria {url_prio}: {e_prio}", flush=True
        )

    # 2. BARRIDO GENERAL
    try:
      print("\nCargando Marketplace...", flush=True)
      page.goto(url_busqueda, timeout=45000, wait_until="domcontentloaded")
      page.wait_for_timeout(3000)

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

      for idx, iid in enumerate(iids_pendientes[:10], 1):
        post_url = f"https://www.facebook.com/marketplace/item/{iid}/"
        print(f"[{idx}] Abriendo ID {iid}...", flush=True)

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
          texto_crudo = (
              main_el.inner_text() if main_el else page.inner_text("body")
          )

          if es_mueble(texto_crudo):
            vistos.add(iid)
            continue

          texto_limpio = limpiar_texto_marketplace(texto_crudo)
          fotos = descargar_fotos_reales(page, iid)
          texto_ocr = extraer_texto_de_imagenes(fotos) if fotos else ""

          if enviar_publicacion_correo(
              iid, post_url, texto_limpio, fotos, texto_ocr
          ):
            vistos.add(iid)

          for f in fotos:
            if os.path.exists(f):
              os.remove(f)
        except Exception as ep:
          print(f"Error en ID {iid}: {ep}", flush=True)

        time.sleep(5)
    except Exception as e:
      print(f"Error en barrido: {e}", flush=True)
    finally:
      b.close()

  with open("vistos.json", "w", encoding="utf-8") as f:
    json.dump(list(vistos), f, indent=2)


if __name__ == "__main__":
  raspar()
      
