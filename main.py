import os, json, re, base64, time, csv, urllib.request, urllib.parse
from datetime import datetime
from playwright.sync_api import sync_playwright

# Variables de entorno leídas de forma segura desde GitHub Secrets
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID") or "5171466462"
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
FB_COOKIES = os.environ.get("FB_COOKIES")

CSV_FILE = "historial_juegos.csv"
CAMPOS_CSV = [
    "Fecha", "Juego", "Precio Marketplace (GTQ)", "Precio Texto", "Origen Precio",
    "Oportunidad (<= Q250)", "Precio Amazon (USD)", "Equivalente Amazon (GTQ)",
    "Ahorro Estimado (%)", "BGG Rating", "BGG Complejidad", "ID Publicacion", "Enlace Marketplace"
]

def registrar_en_csv(item_data, post_url, iid):
    archivo_nuevo = not os.path.exists(CSV_FILE)
    try:
        with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
            if archivo_nuevo:
                writer.writeheader()
            
            p_post = item_data.get("precio_post")
            p_usd = item_data.get("precio_amazon_usd")
            equiv_gtq = round(p_usd * 7.80, 2) if (p_usd and p_usd > 0) else None
            
            ahorro = None
            if p_post and p_post > 0 and equiv_gtq and equiv_gtq > p_post:
                ahorro = f"{round(((equiv_gtq - p_post) / equiv_gtq) * 100)}%"

            es_oportunidad = "SÍ" if (p_post and 15.0 <= p_post <= 250.0) else "NO"

            writer.writerow({
                "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Juego": item_data.get("juego", "Desconocido"),
                "Precio Marketplace (GTQ)": p_post or "",
                "Precio Texto": item_data.get("precio_estimado_post", ""),
                "Origen Precio": item_data.get("origen_precio", ""),
                "Oportunidad (<= Q250)": es_oportunidad,
                "Precio Amazon (USD)": p_usd or "",
                "Equivalente Amazon (GTQ)": equiv_gtq or "",
                "Ahorro Estimado (%)": ahorro or "",
                "BGG Rating": item_data.get("rating_bgg", ""),
                "BGG Complejidad": item_data.get("peso_bgg", ""),
                "ID Publicacion": iid,
                "Enlace Marketplace": post_url
            })
    except Exception as e:
        print(f"Error al escribir en CSV: {e}", flush=True)

def tg_send(texto):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = json.dumps({"chat_id": CHAT_ID, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": False}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("result", {}).get("message_id")
    except Exception as e:
        print(f"Error tg_send: {e}", flush=True)
        return None

def tg_edit(msg_id, texto):
    if not msg_id: return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/editMessageText"
        payload = json.dumps({"chat_id": CHAT_ID, "message_id": msg_id, "text": texto, "parse_mode": "HTML"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r: pass
    except Exception: pass

def alerta(item_data, url_post, thumb=None):
    nombre = item_data.get("juego", "Juego de mesa")
    p_post = item_data.get("precio_post")
    p_estimado = item_data.get("precio_estimado_post") or ("Ver en publicación" if not p_post else f"Q{p_post:.2f}")
    origen = item_data.get("origen_precio", "No especificado")
    p_usd = item_data.get("precio_amazon_usd")
    rating = item_data.get("rating_bgg")
    peso = item_data.get("peso_bgg")

    badge_rango = ""
    if p_post and 15.0 <= p_post <= 250.0:
        badge_rango = "🎯 <b>[PRECIO DE OPORTUNIDAD]</b>\n"

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
        f"🎲 <b>{nombre.upper()}</b>\n\n"
        f"{badge_rango}"
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
            url_photo = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
            payload_photo = json.dumps({"chat_id": CHAT_ID, "photo": thumb, "caption": msg, "parse_mode": "HTML"}).encode("utf-8")
            req_photo = urllib.request.Request(url_photo, data=payload_photo, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req_photo, timeout=10) as r:
                if json.loads(r.read()).get("ok"): return True
        except Exception: pass
    return tg_send(msg) is not None

def extraer_ia(texto_completo, img_urls=None):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
    prompt = (
        "Eres un experto absoluto en juegos de mesa y evaluador de precios en Guatemala.\n"
        "Analiza esta publicación de Facebook Marketplace (incluye título, precio mostrado, fotos y descripción detallada).\n"
        "REGLA CRÍTICA DE EXHAUSTIVIDAD:\n"
        "- Si hay imágenes de cajas apiladas, estantes o carrusel de fotos, inspecciona CADA UNA de las fotos y lista TODOS los juegos de mesa visibles sin omitir ninguno (aunque sean 20 o 30 juegos).\n"
        "- Si hay una lista en la descripción (ej. 'Juego X - Q50, Juego Y - Q100'), extrae cada juego con su precio individual exacto.\n\n"
        f"Texto de la publicación:\n\"\"\"{texto_completo}\"\"\"\n\n"
        "Para cada juego de mesa encontrado, devuelve:\n"
        "1. 'juego': Nombre oficial del juego.\n"
        "2. 'precio_post': Precio individual numérico en Quetzales (float). Si no tiene precio individual pon null.\n"
        "3. 'precio_estimado_post': Texto legible del precio (ej. 'Q75', 'Q40', 'Rango Q15 - Q200', 'Ver en post').\n"
        "4. 'origen_precio': 'Lista en descripción', 'Precio directo del anuncio', o 'Estimado por rango'.\n"
        "5. 'rating_bgg': Calificación BGG aproximada (1 a 10).\n"
        "6. 'peso_bgg': Complejidad BGG (1 a 5).\n"
        "7. 'precio_amazon_usd': Precio aproximado nuevo en Amazon USA en DÓLARES (USD float).\n\n"
        "Devuelve exclusivamente una lista JSON válida con TODOS los juegos encontrados:\n"
        '[{"juego": "Nombre", "precio_post": 100.0, "precio_estimado_post": "Q100", "origen_precio": "Lista en descripción", "rating_bgg": 7.2, "peso_bgg": 2.1, "precio_amazon_usd": 24.99}]'
    )
    parts = [{"text": prompt}]
    
    if img_urls:
        for u in img_urls[:5]:
            try:
                req_img = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req_img, timeout=6) as ir:
                    b64_img = base64.b64encode(ir.read()).decode("utf-8")
                    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_img}})
            except Exception: pass

    payload = {"contents": [{"parts": parts}], "generationConfig": {"response_mime_type": "application/json"}}
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)

    for intento in range(4):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw_txt = json.loads(resp.read().decode())["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(raw_txt)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"⏳ Límite 429. Pausa de 35s para recargar cuota (intento {intento+1}/4)...", flush=True)
                time.sleep(35)
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

    print("Iniciando barrido exhaustivo con registro en Excel/CSV...", flush=True)
    status_id = tg_send("📡 <b>Iniciando búsqueda en Marketplace Guatemala...</b>\nBuscando publicaciones y actualizando registro Excel/CSV...")

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
            print("Cargando Marketplace Ciudad de Guatemala...", flush=True)
            page.goto(url_busqueda, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            try:
                page.keyboard.press("Escape")
                for s in ['[aria-label="Cerrar"]', '[aria-label="Close"]', 'div[role="button"]:has-text("Ahora no")']:
                    btn = page.query_selector(s)
                    if btn: btn.click(); page.wait_for_timeout(500)
            except Exception: pass

            for _ in range(8):
                page.evaluate("window.scrollBy(0, 1500)")
                page.wait_for_timeout(2000)

            enlaces = page.query_selector_all('a[href*="/marketplace/item/"], a[href*="/item/"]')
            
            items_encontrados = []
            vistos_temp = set()
            for a in enlaces:
                href = a.get_attribute("href") or ""
                txt = a.inner_text().strip()
                m = re.search(r"/item/(\d+)", href)
                if m:
                    iid = m.group(1)
                    if iid not in vistos_temp:
                        vistos_temp.add(iid)
                        es_lote = any(k in txt.lower() for k in ["lote", "liquidacion", "liquidación", "varios", "disponible", "remate", "combo", "coleccion", "colección", "gratis", "q1", "q 1"])
                        items_encontrados.append({
                            "iid": iid,
                            "txt": txt,
                            "prioridad": 1 if es_lote else 2
                        })

            items_encontrados.sort(key=lambda x: x["prioridad"])
            total_a_revisar = len(items_encontrados)
            print(f"Total publicaciones encontradas: {total_a_revisar}. Priorizando lotes...", flush=True)
            tg_edit(status_id, f"🔍 <b>Se encontraron {total_a_revisar} publicaciones en Guatemala.</b>\nAnalizando a fondo y guardando en Excel/CSV...")

            items_procesados = 0
            for idx, item_info in enumerate(items_encontrados, 1):
                iid = item_info["iid"]
                post_url = f"https://www.facebook.com/marketplace/item/{iid}/"
                print(f"\n[{idx}/{total_a_revisar}] Abriendo ID {iid} ({item_info['txt'][:50]}...)", flush=True)
                tg_edit(status_id, f"⏳ <b>Progreso: {idx}/{total_a_revisar} anuncios</b>\nLeyendo fotos y descripción...")

                try:
                    page.goto(post_url, timeout=20000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)

                    try:
                        ver_mas = page.query_selector('div[role="main"] div[role="button"]:has-text("Ver más")')
                        if ver_mas: ver_mas.click(); page.wait_for_timeout(400)
                    except Exception: pass

                    main_el = page.query_selector('div[role="main"]')
                    texto_completo = main_el.inner_text() if main_el else page.inner_text("body")
                    
                    imgs = page.query_selector_all('div[role="main"] img')
                    img_urls = []
                    for im in imgs:
                        src = im.get_attribute("src") or ""
                        if "fbcdn.net" in src and "rsrc.php" not in src and src not in img_urls:
                            img_urls.append(src)

                    print(f"[{idx}/{total_a_revisar}] Fotos en carrusel: {len(img_urls)}. Consultando IA...", flush=True)
                    items_ia = extraer_ia(texto_completo[:2000], img_urls=img_urls)

                    if items_ia:
                        vistos.add(iid)

                    for item in items_ia:
                        nom = item.get("juego", "").strip()
                        p = item.get("precio_post")

                        # Guardar SIEMPRE en la base de datos CSV para tener el registro histórico
                        registrar_en_csv(item, post_url, iid)

                        clave = re.sub(r'[^a-z0-9]', '', nom.lower())
                        if not clave or clave in juegos_notificados_hoy:
                            continue

                        if (p and p >= 15.0) or (not p and nom):
                            juegos_notificados_hoy.add(clave)
                            print(f"🚨 Alerta: {nom}", flush=True)
                            foto_alerta = img_urls[0] if img_urls else None
                            alerta(item, post_url, foto_alerta)
                            items_procesados += 1

                except Exception as ep:
                    print(f"Error al procesar ID {iid}: {ep}", flush=True)

                time.sleep(16)

            tg_edit(status_id, f"✅ <b>Barrido exhaustivo finalizado.</b>\nSe analizaron {total_a_revisar} publicaciones, se registraron en el archivo Excel/CSV y se enviaron {items_procesados} alertas.")
            print(f"Finalizado con éxito. Total alertas: {items_procesados}", flush=True)
        except Exception as e:
            print(f"Error general: {e}", flush=True)
            tg_edit(status_id, f"❌ <b>Error:</b> {e}")
        finally: b.close()

    with open("vistos.json", "w") as f: json.dump(list(vistos), f, indent=2)

if __name__ == "__main__":
    raspar()
    
