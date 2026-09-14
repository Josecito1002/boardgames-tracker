import os, json, re, base64, time, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8578108762:AAHw2jIcKs8L8X44DxIQ7tjZTgscN2rjYKI"
CHAT_ID = os.environ.get("CHAT_ID") or "5171466462"
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
FB_COOKIES = os.environ.get("FB_COOKIES")

def tg_send(texto):
    try:
        cmd = f'curl -s -d "chat_id={CHAT_ID}" --data-urlencode "text={texto}" -d "parse_mode=HTML" https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        res = json.loads(os.popen(cmd).read())
        return res.get("result", {}).get("message_id")
    except Exception: return None

def tg_edit(msg_id, texto):
    if not msg_id: return
    try:
        cmd = f'curl -s -d "chat_id={CHAT_ID}" -d "message_id={msg_id}" --data-urlencode "text={texto}" -d "parse_mode=HTML" https://api.telegram.org/bot{TG_TOKEN}/editMessageText'
        os.system(cmd)
    except Exception: pass

def alerta(item_data, url_post, thumb=None):
    nombre = item_data.get("juego", "Juego desconocido")
    p_post = item_data.get("precio_post")
    p_estimado = item_data.get("precio_estimado_post") or ("Ver en publicación" if not p_post else f"Q{p_post:.2f}")
    origen = item_data.get("origen_precio", "No especificado")
    p_usd = item_data.get("precio_amazon_usd")
    rating = item_data.get("rating_bgg")
    peso = item_data.get("peso_bgg")

    amazon_str = ""
    ahorro_str = ""
    if p_usd and p_usd > 0:
        equiv_gtq = p_usd * 7.80
        amazon_str = f"🛒 <b>Precio nuevo en Amazon:</b> ~${p_usd:.2f} USD (~Q{equiv_gtq:.0f} GTQ)\n"
        if p_post and p_post > 0 and equiv_gtq > p_post:
            descuento = round(((equiv_gtq - p_post) / equiv_gtq) * 100)
            ahorro_str = f"🔥 <b>Ahorro frente a Amazon:</b> {descuento}%\n"

    rating_str = f"⭐ <b>BGG Rating:</b> {rating}/10\n" if rating else ""
    peso_str = f"🧠 <b>Complejidad:</b> {peso}/5\n" if peso else ""

    msg = (
        f"🎲 <b>¡JUEGO DETECTADO EN GUATEMALA!</b> 🎲\n\n"
        f"📦 <b>Juego:</b> {nombre}\n"
        f"💰 <b>Precio Marketplace:</b> {p_estimado}\n"
        f"📍 <b>Origen precio:</b> {origen}\n"
        f"{ahorro_str}"
        f"{amazon_str}"
        f"{rating_str}"
        f"{peso_str}\n"
        f"🔗 <a href='{url_post}'>Ver en Facebook Marketplace</a>"
    )

    if thumb:
        try:
            cmd = f'curl -s -F chat_id="{CHAT_ID}" -F photo=@{thumb} --data-urlencode "caption={msg}" -F parse_mode="HTML" https://api.telegram.org/bot{TG_TOKEN}/sendPhoto'
            if os.system(cmd) == 0: return True
        except Exception: pass
    return tg_send(msg) is not None

def extraer_ia(texto_completo, img_url=None):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
    prompt = (
        "Eres un experto en juegos de mesa y evaluador de precios en Guatemala.\n"
        "Analiza esta publicación de Facebook Marketplace (incluye título, precio mostrado y descripción detallada).\n"
        "Si hay una lista en la descripción (ej. 'Juego X - Q50, Juego Y - Q100'), extrae cada juego con su precio individual exacto.\n"
        "Si hay una imagen, apóyate en las cajas visibles en la foto.\n\n"
        f"Texto de la publicación:\n\"\"\"{texto_completo}\"\"\"\n\n"
        "Para cada juego de mesa encontrado, devuelve:\n"
        "1. 'juego': Nombre oficial del juego.\n"
        "2. 'precio_post': Precio individual numérico en Quetzales (float). Si no tiene precio claro, pon null.\n"
        "3. 'precio_estimado_post': Texto legible del precio (ej. 'Q75', 'Q40', 'Rango Q15 - Q200').\n"
        "4. 'origen_precio': 'Lista en descripción', 'Precio directo del anuncio', o 'Estimado por rango'.\n"
        "5. 'rating_bgg': Calificación BGG aproximada (1 a 10).\n"
        "6. 'peso_bgg': Complejidad BGG (1 a 5).\n"
        "7. 'precio_amazon_usd': Precio aproximado nuevo en Amazon USA en DÓLARES (USD float).\n\n"
        "Devuelve exclusivamente un JSON válido: "
        '[{"juego": "Ajedrez clásico", "precio_post": 75.0, "precio_estimado_post": "Q75", "origen_precio": "Lista en descripción", "rating_bgg": 7.1, "peso_bgg": 3.68, "precio_amazon_usd": 14.99}]'
    )
    parts = [{"text": prompt}]
    if img_url:
        try:
            req_img = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_img, timeout=5) as ir:
                b64_img = base64.b64encode(ir.read()).decode("utf-8")
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_img}})
        except Exception: pass

    payload = {"contents": [{"parts": parts}], "generationConfig": {"response_mime_type": "application/json"}}
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)

    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw_txt = json.loads(resp.read().decode())["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(raw_txt)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"⏳ Límite 429. Pausa de 25s (intento {intento+1}/3)...", flush=True)
                time.sleep(25)
            else:
                print(f"Error IA: {e}", flush=True)
                return []
        except Exception as e:
            print(f"Error IA: {e}", flush=True)
            return []
    return []

def raspar():
    vistos = set()
    juegos_notificados_hoy = set()
    url_busqueda = "https://www.facebook.com/marketplace/guatemalacity/search/?query=juegos%20de%20mesa"

    print("Iniciando bot...", flush=True)
    status_id = tg_send("📡 <b>Iniciando revisión de Marketplace en Guatemala...</b>\nBuscando publicaciones recientes...")

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}, locale="es-GT",
            geolocation={"latitude": 14.6349, "longitude": -90.5069}, permissions=["geolocation"]
        )
        if FB_COOKIES:
            try:
                cks = []
                for c in json.loads(FB_COOKIES):
                    ck = {"name": c["name"], "value": c["value"], "domain": c.get("domain", ".facebook.com"), "path": c.get("path", "/")}
                    ss = str(c.get("sameSite", "")).lower()
                    if ss == "strict": ck["sameSite"] = "Strict"
                    elif ss == "lax": ck["sameSite"] = "Lax"
                    elif ss in ["no_restriction", "none"]: ck["sameSite"] = "None"; ck["secure"] = True
                    elif c.get("secure"): ck["secure"] = True
                    cks.append(ck)
                ctx.add_cookies(cks)
                print("✅ Cookies inyectadas.", flush=True)
            except Exception as e: print("Error cookies:", e, flush=True)

        page = ctx.new_page()
        try:
            print("Navegando a Marketplace...", flush=True)
            page.goto(url_busqueda, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            try:
                page.keyboard.press("Escape")
                for s in ['[aria-label="Cerrar"]', '[aria-label="Close"]', 'div[role="button"]:has-text("Ahora no")']:
                    btn = page.query_selector(s)
                    if btn: btn.click(); page.wait_for_timeout(500)
            except Exception: pass

            for _ in range(2):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(1500)

            enlaces = page.query_selector_all('a[href*="/marketplace/item/"], a[href*="/item/"]')
            iids_pendientes = []
            for a in enlaces:
                href = a.get_attribute("href") or ""
                m = re.search(r"/item/(\d+)", href)
                if m:
                    iid = m.group(1)
                    if iid not in vistos and iid not in iids_pendientes:
                        iids_pendientes.append(iid)

            total_a_revisar = min(len(iids_pendientes), 8)
            print(f"Publicaciones encontradas: {len(iids_pendientes)}. Analizando las primeras {total_a_revisar}...", flush=True)
            tg_edit(status_id, f"🔍 <b>Se encontraron {len(iids_pendientes)} publicaciones en Guatemala.</b>\nAnalizando a fondo las {total_a_revisar} más recientes...")

            items_procesados = 0
            for idx, iid in enumerate(iids_pendientes[:total_a_revisar], 1):
                post_url = f"https://www.facebook.com/marketplace/item/{iid}/"
                print(f"[{idx}/{total_a_revisar}] Abriendo ID {iid}...", flush=True)
                tg_edit(status_id, f"⏳ <b>Analizando publicación {idx}/{total_a_revisar}</b>...\nAbriendo anuncio y leyendo descripción completa...")

                try:
                    page.goto(post_url, timeout=20000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)

                    try:
                        ver_mas = page.query_selector('div[role="main"] div[role="button"]:has-text("Ver más")')
                        if ver_mas: ver_mas.click(); page.wait_for_timeout(400)
                    except Exception: pass

                    main_el = page.query_selector('div[role="main"]')
                    texto_completo = main_el.inner_text() if main_el else page.inner_text("body")
                    
                    img_elem = page.query_selector('div[role="main"] img')
                    img_url = img_elem.get_attribute("src") if img_elem else None

                    print(f"[{idx}/{total_a_revisar}] Consultando IA...", flush=True)
                    tg_edit(status_id, f"🧠 <b>Analizando publicación {idx}/{total_a_revisar} con IA...</b>\nLeyendo lista y comparando con Amazon...")
                    items_ia = extraer_ia(texto_completo[:1500], img_url=img_url)
                    vistos.add(iid)

                    for item in items_ia:
                        nom = item.get("juego", "").strip()
                        p = item.get("precio_post")

                        clave = re.sub(r'[^a-z0-9]', '', nom.lower())
                        if not clave or clave in juegos_notificados_hoy:
                            continue

                        if (p and 15.0 <= p <= 250.0) or (not p and nom):
                            juegos_notificados_hoy.add(clave)
                            print(f"🚨 Enviando alerta: {nom}", flush=True)
                            alerta(item, post_url, img_url)
                            items_procesados += 1

                except Exception as ep:
                    print(f"Error al procesar ID {iid}: {ep}", flush=True)

                time.sleep(12)

            tg_edit(status_id, f"✅ <b>Revisión completada.</b>\nSe analizaron {total_a_revisar} publicaciones a fondo y se enviaron {items_procesados} alertas.")
            print(f"Finalizado con éxito. Alertas: {items_procesados}", flush=True)
        except Exception as e:
            print(f"Error general: {e}", flush=True)
            tg_edit(status_id, f"❌ <b>Error:</b> {e}")
        finally: b.close()

    with open("vistos.json", "w") as f: json.dump(list(vistos), f, indent=2)

if __name__ == "__main__":
    raspar()
    
