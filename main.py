import os, json, re, base64, time, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8578108762:AAHw2jIcKs8L8X44DxIQ7tjZTgscN2rjYKI"
CHAT_ID = os.environ.get("CHAT_ID") or "5171466462"
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
FB_COOKIES = os.environ.get("FB_COOKIES")

def alerta(titulo, precio, rating, peso, precio_ref, url_post, thumb=None):
    precio_str = f"Q{precio:.2f}" if precio and precio > 0 else "Ver en publicación"

    # Cálculo automático de ahorro si se detectó precio y hay referencia
    ahorro_str = ""
    if precio and precio > 0 and precio_ref and precio_ref > precio:
        descuento = round(((precio_ref - precio) / precio_ref) * 100)
        ahorro_str = f"🔥 <b>Ahorro estimado:</b> {descuento}% (Nuevo: ~Q{precio_ref:.0f})\n"
    elif precio_ref:
        ahorro_str = f"🏷️ <b>Precio nuevo aprox.:</b> ~Q{precio_ref:.0f}\n"

    bgg_str = f"⭐ <b>BGG Rating:</b> {rating}/10\n" if rating else ""
    peso_str = f"🧠 <b>Complejidad:</b> {peso}/5\n" if peso else ""

    msg = (
        f"🎲 <b>¡JUEGO DETECTADO EN GUATEMALA!</b> 🎲\n\n"
        f"📦 <b>Juego:</b> {titulo}\n"
        f"💰 <b>Precio Marketplace:</b> {precio_str}\n"
        f"{ahorro_str}"
        f"{bgg_str}"
        f"{peso_str}\n"
        f"🔗 <a href='{url_post}'>Ver en Facebook Marketplace</a>"
    )

    def _post(ep, data):
        r = urllib.request.Request(ep, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=10) as resp: return json.loads(resp.read())
    if thumb:
        try:
            if _post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto", {"chat_id": CHAT_ID, "photo": thumb, "caption": msg, "parse_mode": "HTML"}).get("ok"): return True
        except Exception: pass
    return _post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": False}).get("ok", False)

def extraer_ia(texto, img_url=None):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
    prompt = (
        "Eres un experto en juegos de mesa y evaluador de precios en Guatemala.\n"
        "Analiza este anuncio de Facebook Marketplace en Guatemala. "
        "Si hay imagen, identifica los juegos de mesa visibles en las cajas o portadas.\n"
        "Para cada juego de mesa detectado:\n"
        "1. Identifica el nombre del juego.\n"
        "2. Extrae el precio de venta en Quetzales del anuncio (si dice Q1 o Gratis o no está claro, pon null).\n"
        "3. Estima su calificacion promedio en BoardGameGeek (rating_bgg, escala 1 a 10).\n"
        "4. Estima su complejidad en BGG (peso_bgg, escala 1 a 5).\n"
        "5. Estima su precio aproximado nuevo en tiendas de Guatemala en Quetzales (precio_referencia_gtq, basado en retail MSRP/importacion).\n\n"
        "Devuelve exclusivamente un JSON con formato: "
        '[{"juego": "nombre", "precio": 150.0, "rating_bgg": 7.2, "peso_bgg": 2.3, "precio_referencia_gtq": 450.0}]\n'
        f"Texto: {texto}"
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
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(json.loads(resp.read().decode())["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as e:
        print(f"Error IA: {e}")
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

            for _ in range(2):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(2000)

            enlaces = page.query_selector_all('a[href*="/marketplace/item/"], a[href*="/item/"]')
            print(f"Total publicaciones encontradas en Guatemala: {len(enlaces)}")

            items_procesados = 0
            # Procesamos las 8 más recientes por ejecución
            for a in enlaces[:8]:
                href = a.get_attribute("href") or ""
                txt = a.inner_text().strip()
                if not href or len(txt) < 5: continue

                m = re.search(r"/item/(\d+)", href)
                iid = m.group(1) if m else None
                if not iid: continue

                if iid in vistos: continue
                vistos.add(iid)
                post_url = f"https://www.facebook.com/marketplace/item/{iid}/"

                img_elem = a.query_selector("img")
                img_url = img_elem.get_attribute("src") if img_elem else None

                print(f"\nProcesando ID {iid}: {txt[:70]}...")
                items_ia = extraer_ia(txt, img_url=img_url)

                for item in items_ia:
                    nombre = item.get("juego")
                    precio = item.get("precio")
                    rating = item.get("rating_bgg")
                    peso = item.get("peso_bgg")
                    precio_ref = item.get("precio_referencia_gtq")

                    # Alerta si está entre Q15 y Q250, o si se identificó un juego en foto
                    if (precio and 15.0 <= precio <= 250.0) or (not precio and nombre):
                        print(f"🚨 ¡Enviando alerta a Telegram!: {nombre}")
                        alerta(nombre, precio or 0.0, rating, peso, precio_ref, post_url, img_url)
                        items_procesados += 1

                # Pausa de 13s para mantenerse dentro del límite gratuito de 5 peticiones/minuto
                time.sleep(13)

            print(f"\nTotal alertas enviadas: {items_procesados}")
        except Exception as e: print("Error general:", e)
        finally: b.close()

    with open("vistos.json", "w") as f: json.dump(list(vistos), f, indent=2)
    print("Finalizado.")

if __name__ == "__main__":
    raspar()
    
