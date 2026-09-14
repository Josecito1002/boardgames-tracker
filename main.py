import os, json, re, base64, time, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8578108762:AAHw2jIcKs8L8X44DxIQ7tjZTgscN2rjYKI"
CHAT_ID = os.environ.get("CHAT_ID") or "5171466462"
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
FB_COOKIES = os.environ.get("FB_COOKIES")

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

    def _post(ep, data):
        r = urllib.request.Request(ep, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=10) as resp: return json.loads(resp.read())

    if thumb:
        try:
            if _post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto", {"chat_id": CHAT_ID, "photo": thumb, "caption": msg, "parse_mode": "HTML"}).get("ok"):
                return True
        except Exception: pass
    return _post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": False}).get("ok", False)

def extraer_ia(texto, img_url=None):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
    prompt = (
        "Eres un experto en juegos de mesa y evaluador de precios.\n"
        "Analiza este anuncio de Facebook Marketplace en Guatemala.\n"
        f"Texto del anuncio:\n\"\"\"{texto}\"\"\"\n\n"
        "Si hay imagen adjunta, identifica TODOS los juegos de mesa visibles en las cajas, lomos o portadas (sin omitir ninguno).\n"
        "Para cada juego encontrado, extrae o estima:\n"
        "1. 'juego': Nombre oficial del juego.\n"
        "2. 'precio_post': Precio individual numérico en Quetzales si se menciona en el texto para este juego (float). Si no, null.\n"
        "3. 'precio_estimado_post': Texto legible del precio (ej. 'Q150', 'Rango Q15 - Q200', 'Gratis', 'Q1 señuelo').\n"
        "4. 'origen_precio': De donde salio el precio (ej. 'Precio fijo en anuncio', 'Rango en descripcion', 'Sin precio claro en post').\n"
        "5. 'rating_bgg': Calificacion aproximada en BoardGameGeek (1 a 10).\n"
        "6. 'peso_bgg': Complejidad aproximada en BGG (1 a 5).\n"
        "7. 'precio_amazon_usd': Precio de venta nuevo aproximado en Amazon USA en DOLARES (USD float, ej. 29.99).\n\n"
        "Devuelve exclusivamente un JSON valido: "
        '[{"juego": "Codenames", "precio_post": 150.0, "precio_estimado_post": "Q150", "origen_precio": "Precio fijo en anuncio", "rating_bgg": 7.6, "peso_bgg": 1.28, "precio_amazon_usd": 19.99}]'
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
                print(f"⏳ Limite por minuto alcanzado (429). Pausa de 25s para recargar cuota (intento {intento+1}/3)...")
                time.sleep(25)
            else:
                print(f"Error IA: {e}")
                return []
        except Exception as e:
            print(f"Error IA: {e}")
            return []
    return []

def raspar():
    vistos = set(json.load(open("vistos.json"))) if os.path.exists("vistos.json") else set()
    url = "https://www.facebook.com/marketplace/guatemalacity/search/?query=juegos%20de%20mesa"

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
                print("✅ Cookies inyectadas.")
            except Exception as e: print("Error cookies:", e)

        page = ctx.new_page()
        try:
            print("Navegando a Marketplace Ciudad de Guatemala...")
            page.goto(url, timeout=45000)
            page.wait_for_timeout(5000)

            try:
                page.keyboard.press("Escape")
                for s in ['[aria-label="Cerrar"]', '[aria-label="Close"]', 'div[role="button"]:has-text("Ahora no")']:
                    btn = page.query_selector(s)
                    if btn: btn.click(); page.wait_for_timeout(1000)
            except Exception: pass

            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(2000)

            enlaces = page.query_selector_all('a[href*="/marketplace/item/"], a[href*="/item/"]')
            print(f"Total publicaciones visibles: {len(enlaces)}")

            items_procesados = 0
            for a in enlaces:
                href = a.get_attribute("href") or ""
                txt = a.inner_text().strip()
                if not href or len(txt) < 5: continue

                m = re.search(r"/item/(\d+)", href)
                iid = m.group(1) if m else None
                if not iid: continue

                if iid in vistos: continue
                post_url = f"https://www.facebook.com/marketplace/item/{iid}/"

                img_elem = a.query_selector("img")
                img_url = img_elem.get_attribute("src") if img_elem else None

                print(f"\nProcesando ID {iid}: {txt[:70]}...")
                items_ia = extraer_ia(txt, img_url=img_url)

                if items_ia:
                    vistos.add(iid)

                for item in items_ia:
                    p = item.get("precio_post")
                    nom = item.get("juego")

                    if (p and 15.0 <= p <= 250.0) or (not p and nom):
                        print(f"🚨 ¡Enviando alerta a Telegram!: {nom}")
                        alerta(item, post_url, img_url)
                        items_procesados += 1

                time.sleep(12)

            print(f"\nTotal alertas enviadas en esta ejecución: {items_procesados}")
        except Exception as e: print("Error general:", e)
        finally: b.close()

    with open("vistos.json", "w") as f: json.dump(list(vistos), f, indent=2)
    print("Historial vistos.json actualizado con éxito.")

if __name__ == "__main__":
    raspar()
    
