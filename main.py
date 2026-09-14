from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import os
import re
import smtplib
import ssl
import time
import urllib.parse
import urllib.request
from PIL import Image
from playwright.sync_api import sync_playwright
import pytesseract

# ==========================================
# CONFIGURACIÓN Y CREDENCIALES
# ==========================================
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or "5171466462"
FB_COOKIES = os.environ.get("FB_COOKIES")

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS")

# 1. Enlaces prioritarios (deja vacío; solo añade si tienes un post nuevo puntual)
URLS_PRIORITARIAS = []

# 2. Grupos de Facebook a rastrear (usa la URL de www.facebook.com/groups/<id-o-nombre>/)
URLS_GRUPOS = [
    "https://www.facebook.com/groups/boardgamesgt/",
]

# 3. Términos de búsqueda en Marketplace (Mixco / Guatemala)
TERMINOS_BUSQUEDA = [
    "juegos de mesa",
]

# Palabras que descartan publicaciones ajenas
PALABRAS_DESCARTAR = [
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
    "dragon ball",
    "trompo",
    "trompos",
    "mcfarlane",
    "burger king",
    "lamparas de metal",
    "alquiler de juegos",
]

# Palabras que salvan la publicación si coincide con juegos de mesa o rol
PALABRAS_CLAVE_JUEGO = [
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
    "dungeons",
    "d&d",
    "dnd",
    "board game",
    "manual del jugador",
    "guia del dungeon master",
]

# Juegos que quieres seguir sin importar el precio.
WISHLIST = [
    "slay the spire",
    "four souls",  # cubre "Isaac Four Souls" / "The Binding of Isaac: Four Souls"
]


def evaluar_alerta_telegram(texto):
    """Decide si vale la pena notificar por Telegram.

    Notifica solo si el juego está en la WISHLIST. La comparación de precio
    contra Amazon ("buena oferta") ya la hace Gemini/Spark al analizar el
    correo, así que no se replica aquí con un regex poco confiable.
    """
    t = texto.lower()
    for juego in WISHLIST:
        if juego in t:
            return True, f"⭐ En tu wishlist: {juego}"
    return False, ""


def es_publicacion_valida(texto, termino_busqueda=""):
    """
    Evalúa si la publicación es realmente de nuestro interés basándose
    en descartes generales de muebles/objetos ajenos.
    """
    t = texto.lower()

    # Descarte inmediato por muebles o cosas ajenas, salvo que mencione
    # explícitamente algo de juegos de mesa.
    if any(p in t for p in PALABRAS_DESCARTAR):
        if not any(j in t for j in PALABRAS_CLAVE_JUEGO):
            return False

    return True


def limpiar_texto_marketplace(texto_crudo):
    """Corta únicamente bloques estructurales de Facebook sin dañar la descripción."""
    t = texto_crudo
    cortes = [
        "\nSugerencias de hoy",
        "\nInformación del vendedor",
        "\nBúsquedas relacionadas",
        "\nDetalles del vendedor",
    ]
    for corte in cortes:
        if corte in t:
            t = t.split(corte)[0]
    return t.strip()


def expandir_todo_el_texto(page):
    """Despliega todos los botones 'Ver más' para obtener el catálogo completo."""
    try:
        botones = page.query_selector_all('div[role="button"]:has-text("Ver más")')
        for btn in botones:
            try:
                if btn.is_visible():
                    btn.click(timeout=1000)
                    page.wait_for_timeout(600)
            except Exception:
                pass
    except Exception:
        pass


def extraer_texto_de_imagenes(rutas_imgs):
    """Aplica OCR local a las fotos para extraer listas escritas o precios."""
    texto_acumulado = []
    for idx, ruta in enumerate(rutas_imgs, 1):
        try:
            txt = pytesseract.image_to_string(Image.open(ruta), lang="spa").strip()
            if len(txt) > 20:
                texto_acumulado.append(f"--- FOTO {idx} ---\n{txt}")
        except Exception as e:
            print(f"Aviso OCR en {ruta}: {e}", flush=True)
    return "\n\n".join(texto_acumulado)


def enviar_telegram(mensaje):
    """Envía un aviso rápido por Telegram."""
    if not TG_TOKEN or not CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id": CHAT_ID,
            "text": mensaje[:4096],
            "disable_web_page_preview": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except Exception as e:
        print(f"Error al enviar Telegram: {e}", flush=True)
        return False


def enviar_publicacion_correo(iid, url_post, texto_post, rutas_imgs=None, texto_ocr=""):
    rutas_imgs = rutas_imgs or []
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
            <p><b>Enlace directo:</b> <a href="{url_post}">{url_post}</a></p>
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

        for i, ruta in enumerate(rutas_imgs):
            if os.path.exists(ruta):
                with open(ruta, "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-ID", f"<foto_{i}>")
                    img.add_header("Content-Disposition", "inline", filename=os.path.basename(ruta))
                    msg.attach(img)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())

        print(f"📧 Correo enviado para ID {iid} con {len(rutas_imgs)} fotos.", flush=True)
        return True
    except Exception as e:
        print(f"Error al enviar correo: {e}", flush=True)
        return False


def _id_base_foto(src):
    return src.split("?")[0]


def _descargar_foto_con_reintentos(src, ruta_archivo, intentos=3, timeout=10):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        )
    }
    for intento in range(1, intentos + 1):
        try:
            req = urllib.request.Request(src, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "png" in content_type:
                    ruta_archivo = ruta_archivo.replace(".jpg", ".png")
                elif "webp" in content_type:
                    ruta_archivo = ruta_archivo.replace(".jpg", ".webp")
                data = resp.read()
                if len(data) < 2000:
                    raise ValueError("archivo demasiado pequeño")
                with open(ruta_archivo, "wb") as f:
                    f.write(data)
                return ruta_archivo
        except Exception as e:
            if intento == intentos:
                print(f"   ⚠️ Falló descarga tras {intentos} intentos: {e}", flush=True)
                return None
            continue


def descargar_fotos_reales(page, iid):
    """Descarga todas las fotos originales de la publicación."""
    rutas = []
    ids_vistos = set()

    def _guardar_si_es_nueva(src):
        if not (src and src.startswith("http") and "scontent" in src):
            return False
        uid = _id_base_foto(src)
        if uid in ids_vistos:
            return False
        ids_vistos.add(uid)
        ruta_tentativa = f"foto_{iid}_{len(rutas) + 1}.jpg"
        ruta_final = _descargar_foto_con_reintentos(src, ruta_tentativa)
        if ruta_final:
            rutas.append(ruta_final)
            return True
        return False

    try:
        img_principal = page.query_selector(
            'div[role="main"] div[data-visualcompletion="media-vc-image"] img'
        ) or page.query_selector('div[role="main"] img')
        if img_principal:
            img_principal.hover()
            img_principal.click()
            page.wait_for_timeout(600)
    except Exception:
        pass

    # Estrategia 1: Miniaturas
    miniaturas = page.query_selector_all(
        'div[role="main"] [role="button"]:has(img),'
        ' div[role="main"] [aria-label*="miniatura"],'
        ' div[role="main"] [aria-label*="thumbnail"]'
    )
    if len(miniaturas) > 1:
        for thumb in miniaturas[:12]:
            try:
                thumb.click(force=True)
                page.wait_for_timeout(800)
                img_activa = page.query_selector(
                    'div[role="main"] div[data-visualcompletion="media-vc-image"] img'
                ) or page.query_selector('div[role="main"] img')
                if img_activa:
                    _guardar_si_es_nueva(img_activa.get_attribute("src"))
            except Exception:
                continue

    # Estrategia 2: Teclado si no hubo miniaturas
    if len(rutas) <= 1:
        intentos_sin_avance = 0
        for _ in range(12):
            if intentos_sin_avance >= 3:
                break
            try:
                avanzo = False
                imgs = page.query_selector_all(
                    'div[role="main"] img, div[data-pagelet="MediaViewerRoot"] img'
                )
                for im in imgs:
                    src = im.get_attribute("src")
                    box = im.bounding_box()
                    if box and box["width"] > 250 and box["height"] > 250:
                        if _guardar_si_es_nueva(src):
                            avanzo = True
                            break
                intentos_sin_avance = 0 if avanzo else intentos_sin_avance + 1
                page.keyboard.press("ArrowRight")
                page.wait_for_timeout(700)
            except Exception:
                break

    print(f"   ✅ Total fotos descargadas para ID {iid}: {len(rutas)}", flush=True)
    return rutas


def resolver_url_grupo(page, url_grupo):
    """Normaliza la URL de un grupo de Facebook a la versión de www.facebook.com
    con orden cronológico, aceptando tanto IDs numéricos (/groups/123456789/)
    como nombres de vanity (/groups/boardgamesgt/). Si url_grupo es un link de
    invitación corto (facebook.com/share/g/<code>/), lo visita primero y deja
    que Facebook redirija a la URL canónica.
    """
    m_directo = re.search(r"facebook\.com/groups/([^/?]+)", url_grupo)
    if m_directo:
        identificador = m_directo.group(1)
        return f"https://www.facebook.com/groups/{identificador}/?sorting_setting=CHRONOLOGICAL"

    # No vino con /groups/<algo>/ directo (ej. un link de invitación /share/g/...):
    # lo visitamos y vemos a dónde redirige Facebook.
    page.goto(url_grupo, timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    m = re.search(r"facebook\.com/groups/([^/?]+)", page.url)
    if m:
        identificador = m.group(1)
        return f"https://www.facebook.com/groups/{identificador}/?sorting_setting=CHRONOLOGICAL"

    print(
        f"   ⚠️ No se pudo resolver un ID/nombre de grupo desde: {url_grupo}\n"
        f"      URL final tras la redirección: {page.url}\n"
        "      Reemplaza URLS_GRUPOS por la URL de escritorio del grupo"
        " (facebook.com/groups/<numero-o-nombre>/).",
        flush=True,
    )
    return None


def raspar_grupo(page, url_grupo, vistos, max_posts=5):
    """Rastrea publicaciones de venta en el grupo de Facebook."""
    print(f"\n👥 Accediendo al grupo de Facebook: {url_grupo}...", flush=True)
    try:
        url_resuelta = resolver_url_grupo(page, url_grupo)
        if not url_resuelta:
            return  # no se pudo determinar un grupo válido; se avisó arriba

        page.goto(url_resuelta, timeout=40000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

        # Diagnóstico: ¿la cuenta puede ver el feed del grupo, o solo la
        # pantalla de "unirte"? Esto se imprime siempre para poder revisar
        # el log sin tener que adivinar.
        titulo_pagina = page.title()
        texto_pagina = page.inner_text("body")[:500].replace("\n", " ")
        indicadores_sin_acceso = [
            "unirse al grupo",
            "unirte al grupo",
            "join group",
            "solicitar unirse",
            "no está disponible en este momento",
            "no esta disponible en este momento",
            "content isn't available",
        ]
        if any(ind in texto_pagina.lower() for ind in indicadores_sin_acceso):
            print(
                "   ⚠️ Facebook no está entregando el contenido del grupo a esta"
                " sesión (mensaje de 'contenido no disponible' o 'únete al"
                " grupo'). El link de invitación puede haber expirado, o la"
                " sesión automatizada recibe un trato distinto al de un"
                " navegador normal logueado con la misma cuenta.",
                flush=True,
            )

        print(f"   URL resuelta usada: {url_resuelta}", flush=True)
        print(f"   Título de la página cargada: {titulo_pagina!r}", flush=True)
        print(f"   Primeros 500 caracteres visibles: {texto_pagina!r}", flush=True)

        for intento_scroll in range(8):
            page.evaluate("window.scrollBy(0, 1400)")
            page.wait_for_timeout(2000)
            n_articulos_parcial = len(page.query_selector_all('div[role="article"]'))
            if n_articulos_parcial >= 6:
                break

        articulos = page.query_selector_all('div[role="article"]')
        print(
            f"   Bloques de publicación (div[role=article]) detectados:"
            f" {len(articulos)}",
            flush=True,
        )

        enlaces = page.query_selector_all(
            'a[href*="/posts/"], a[href*="/permalink/"],'
            ' a[href*="/multi_permalinks/"]'
        )
        print(f"   Links con /posts|permalink| detectados: {len(enlaces)}", flush=True)

        # Diagnóstico: si no encontramos links con el patrón esperado, mostrar
        # los hrefs reales que sí existen dentro de los primeros bloques para
        # descubrir el formato actual que usa Facebook.
        if len(enlaces) == 0 and articulos:
            print("   🔎 Volcando hrefs reales de los primeros bloques para diagnóstico:", flush=True)
            for i, art in enumerate(articulos[:3], 1):
                hrefs = [
                    a.get_attribute("href")
                    for a in art.query_selector_all("a[href]")
                ]
                hrefs = [h for h in hrefs if h][:15]
                print(f"      Bloque {i}: {hrefs}", flush=True)

        posts_pendientes = []
        for a in enlaces:
            href = a.get_attribute("href") or ""
            m = re.search(r"/(?:posts|permalink|multi_permalinks)/(\d+)", href)
            if m:
                pid = m.group(1)
                iid = f"GRUPO_{pid}"
                clean_url = href.split("?")[0]
                if (
                    iid not in vistos
                    and pid not in [p[0] for p in posts_pendientes]
                    and pid != "0"
                ):
                    posts_pendientes.append((pid, clean_url))

        total = min(len(posts_pendientes), max_posts)
        print(f"   Publicaciones detectadas en el grupo: {total}", flush=True)

        for idx, (pid, post_url) in enumerate(posts_pendientes[:total], 1):
            iid = f"GRUPO_{pid}"
            print(f"   [{idx}/{total}] Abriendo post del grupo ID {pid}...", flush=True)
            try:
                page.goto(post_url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)

                expandir_todo_el_texto(page)

                main_el = page.query_selector(
                    'div[role="main"] div[data-ad-preview="message"]'
                ) or page.query_selector('div[role="main"]')
                texto_crudo = main_el.inner_text() if main_el else page.inner_text("body")
                texto_limpio = limpiar_texto_marketplace(texto_crudo)

                # AQUÍ SE APLICA EL NUEVO FILTRO PARA GRUPOS
                if not es_publicacion_valida(texto_limpio):
                    vistos.add(iid)
                    continue

                fotos = descargar_fotos_reales(page, pid)
                texto_ocr = extraer_texto_de_imagenes(fotos) if fotos else ""

                correo_ok = enviar_publicacion_correo(
                    iid, post_url, texto_limpio, fotos, texto_ocr
                )
                debe_notificar, motivo = evaluar_alerta_telegram(
                    f"{texto_limpio}\n{texto_ocr}"
                )
                tg_ok = False
                if debe_notificar:
                    tg_ok = enviar_telegram(
                        f"👥 [GRUPO GT] {motivo}\nID {pid}\n{post_url}\n\n"
                        f"{texto_limpio[:300]}"
                    )
                if correo_ok or tg_ok:
                    vistos.add(iid)

                for f in fotos:
                    if os.path.exists(f):
                        os.remove(f)
            except Exception as ep:
                print(f"   Error procesando post {pid}: {ep}", flush=True)

            time.sleep(4)
    except Exception as e:
        print(f"Error al raspar el grupo: {e}", flush=True)


def raspar():
    vistos = set()
    if os.path.exists("vistos.json"):
        try:
            with open("vistos.json", "r", encoding="utf-8") as f:
                vistos = set(json.load(f))
        except Exception:
            pass

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                " (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
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

        # 1. PUBLICACIONES PRIORITARIAS (SI EXISTIERAN NUEVAS)
        for idx, url_prio in enumerate(URLS_PRIORITARIAS, 1):
            print(f"\n[PRIORITARIO {idx}/{len(URLS_PRIORITARIAS)}] Abriendo: {url_prio}", flush=True)
            try:
                page.goto(url_prio, timeout=35000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                real_url = page.url
                m = re.search(r"/item/(\d+)", real_url)
                iid = m.group(1) if m else f"prio_{idx}"

                if iid in vistos:
                    print(f"   Ya notificado antes (ID {iid}), se omite.", flush=True)
                    continue

                expandir_todo_el_texto(page)

                main_el = page.query_selector('div[role="main"]')
                texto_crudo = main_el.inner_text() if main_el else page.inner_text("body")
                texto_limpio = limpiar_texto_marketplace(texto_crudo)

                fotos = descargar_fotos_reales(page, iid)
                texto_ocr = extraer_texto_de_imagenes(fotos) if fotos else ""

                correo_ok = enviar_publicacion_correo(
                    iid, real_url, texto_limpio, fotos, texto_ocr
                )
                debe_notificar, motivo = evaluar_alerta_telegram(
                    f"{texto_limpio}\n{texto_ocr}"
                )
                tg_ok = False
                if debe_notificar:
                    tg_ok = enviar_telegram(
                        f"🎯 Prioritaria — {motivo}\nID {iid}\n{real_url}\n\n"
                        f"{texto_limpio[:300]}"
                    )
                if correo_ok or tg_ok:
                    vistos.add(iid)

                for f in fotos:
                    if os.path.exists(f):
                        os.remove(f)
                time.sleep(4)
            except Exception as e_prio:
                print(f"Error en publicación prioritaria {url_prio}: {e_prio}", flush=True)

        # 2. RASTREO EN EL GRUPO DE FACEBOOK GUATEMALA
        for url_g in URLS_GRUPOS:
            raspar_grupo(page, url_g, vistos)

        # 3. BARRIDO DE TÉRMINOS EN MARKETPLACE (Juegos de mesa y D&D)
        for termino in TERMINOS_BUSQUEDA:
            url_encoded = urllib.parse.quote(termino)
            url_busqueda = (
                "https://www.facebook.com/marketplace/mixco-guatemala/search/"
                f"?query={url_encoded}&sortBy=creation_time_descend"
            )
            print(f"\n🔍 Buscando en Marketplace: '{termino}'...", flush=True)

            try:
                page.goto(url_busqueda, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                for _ in range(4):
                    page.evaluate("window.scrollBy(0, 1500)")
                    page.wait_for_timeout(1500)

                enlaces = page.query_selector_all('a[href*="/marketplace/item/"], a[href*="/item/"]')
                iids_pendientes = []
                for a in enlaces:
                    href = a.get_attribute("href") or ""
                    txt = a.inner_text().strip()
                    m = re.search(r"/item/(\d+)", href)
                    if m:
                        iid = m.group(1)
                        # AQUÍ SE APLICA EL FILTRO PASANDO EL TÉRMINO DE BÚSQUEDA ACTUAL
                        if (
                            iid not in vistos
                            and iid not in iids_pendientes
                            and es_publicacion_valida(txt, termino_busqueda=termino)
                        ):
                            iids_pendientes.append(iid)

                total_termino = min(len(iids_pendientes), 5)
                print(f"   Nuevos avisos para '{termino}': {total_termino}", flush=True)

                for idx, iid in enumerate(iids_pendientes[:total_termino], 1):
                    post_url = f"https://www.facebook.com/marketplace/item/{iid}/"
                    print(f"   [{idx}/{total_termino}] Abriendo ID {iid}...", flush=True)

                    try:
                        page.goto(post_url, timeout=20000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)

                        expandir_todo_el_texto(page)

                        main_el = page.query_selector('div[role="main"]')
                        texto_crudo = main_el.inner_text() if main_el else page.inner_text("body")

                        # VALIDACIÓN FINAL DEL CONTENIDO COMPLETO
                        if not es_publicacion_valida(texto_crudo, termino_busqueda=termino):
                            vistos.add(iid)
                            continue

                        texto_limpio = limpiar_texto_marketplace(texto_crudo)
                        fotos = descargar_fotos_reales(page, iid)
                        texto_ocr = extraer_texto_de_imagenes(fotos) if fotos else ""

                        correo_ok = enviar_publicacion_correo(
                            iid, post_url, texto_limpio, fotos, texto_ocr
                        )
                        debe_notificar, motivo = evaluar_alerta_telegram(
                            f"{texto_limpio}\n{texto_ocr}"
                        )
                        tg_ok = False
                        if debe_notificar:
                            tg_ok = enviar_telegram(
                                f"🎲 [{termino.upper()}] {motivo}\nID {iid}\n{post_url}\n\n"
                                f"{texto_limpio[:300]}"
                            )
                        if correo_ok or tg_ok:
                            vistos.add(iid)

                        for f in fotos:
                            if os.path.exists(f):
                                os.remove(f)
                    except Exception as ep:
                        print(f"   Error en ID {iid}: {ep}", flush=True)

                    time.sleep(4)
            except Exception as e:
                print(f"Error en búsqueda '{termino}': {e}", flush=True)

        b.close()

    with open("vistos.json", "w", encoding="utf-8") as f:
        json.dump(list(vistos), f, indent=2)

if __name__ == "__main__":
    raspar()
