import os, json, re, base64, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN") or "8578108762:AAHw2jIcKs8L8X44DxIQ7tjZTgscN2rjYKI"
CHAT_ID = os.environ.get("CHAT_ID") or "5171466462"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or base64.b64decode("QVEuQWI4Uk42SmtXaTBiSnpjWUZuNkIyV1p5SWlsdXdyYnJ1bjdOZmpaQVQtdGN1cnhkYkE=").decode()
FB_COOKIES = os.environ.get("FB_COOKIES")

def alerta(titulo, precio, rating, rank, peso, url_post, thumb=None):
    msg = f"🎲 <b>¡JUEGO DETECTADO!</b>\n\n📦 <b>Juego:</b> {titulo}\n💰 <b>Precio:</b> Q{precio:.2f}\n⭐ <b>BGG:</b> {rating or 'N/A'}/10 (#{rank or 'N/A'})\n🧠 <b>Peso:</b> {peso or 'N/A'}/5\n\n🔗 <a href='{url_post}'>Ver en Facebook</a>"
    def _post(ep, data):
        r = urllib.request.Request(ep, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=10) as resp: return json.loads(resp.read())
    if thumb:
        try:
            if _post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto", {"chat_id": CHAT_ID, "photo": thumb, "caption": msg, "parse_mode": "HTML"}).get("ok"): return True
        except Exception: pass
    return _post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": False}).get("ok", False)

def info_bgg(nombre):
    try:
        url1 = f"https://boardgamegeek.com/xmlapi2/search?{urllib.parse.urlencode({'query': nombre, 'type': 'boardgame'})}"
        r1 = urllib.request.Request(url1, headers={"User-Agent": "FBTracker/1.0"})
        with urllib.request.urlopen(r1, timeout=10) as resp: root = ET.fromstring(resp.read())
        items = root.findall("item")
        if not items: return None
        bid = items[0].attrib["id"]
        for it in items:
            ne = it.find("name")
            if ne is not None and ne.attrib.get("value","").lower() == nombre.lower():
                bid = it.attrib["id"]; break
        url2 = f"https://boardgamegeek.com/xmlapi2/thing?id={bid}&stats=1"
        r2 = urllib.request.Request(url2, headers={"User-Agent": "FBTracker/1.0"})
        with urllib.request.urlopen(r2, timeout=10) as resp: it2 = ET.fromstring(resp.read()).find("item")
        if it2 is None: return None
        nom = it2.find("name[@type='primary']").attrib.get("value", nombre)
        th = it2.find("thumbnail")
        thumb = th.text if th is not None else None
        rats = it2.find(".//ratings")
        rating, rank, weight = None, None, None
        if rats is not None:
            av = rats.find("average")
            if av is not None and av.attrib.get("value"): rating = round(float(av.attrib["value"]), 2)
            aw = rats.find("averageweight")
            if aw is not None and aw.attrib.get("value"): weight = round(float(aw.attrib["value"]), 2)
            for rk in rats.findall(".//rank"):
                if rk.attrib.get("name") == "boardgame" and rk.attrib.get("value","").isdigit():
                    rank = int(rk.attrib["value"]); break
        return {"nombre": nom, "rating": rating, "rank": rank, "weight": weight, "thumb": thumb}
    except Exception as e:
        print(f"Error BGG ({nombre}): {e}"); return None

def extraer_ia(texto):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_KEY}"
    prompt = f"Analiza este anuncio de Facebook Marketplace en Guatemala y extrae los juegos de mesa y precios en Quetzales [{{'juego': 'nombre', 'precio': 150.0}}]. Si el precio esta en USD o no es juego de mesa o no hay precio pon null. Texto: {texto}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(json.loads(resp.read().decode())["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as e:
        print(f"Error IA: {e}"); return []

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
            page.wait_for_timeout(6000)

            try:
                page.keyboard.press("Escape")
                for s in ['[aria-label="Cerrar"]', '[aria-label="Close"]', 'div[role="button"]:has-text("Ahora no")']:
                    btn = page.query_selector(s)
                    if btn: btn.click(); page.wait_for_timeout(1000)
            except Exception: pass

            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                page.wait_for_timeout(2000)

            # Enviar foto a Telegram con la ubicación confirmada
            page.screenshot(path="debug_pantalla.png")
            os.system(f'curl -s -F chat_id="{CHAT_ID}" -F photo=@debug_pantalla.png -F caption="Ubicacion actual: {page.url}" https://api.telegram.org/bot{TG_TOKEN}/sendPhoto')

            enlaces = page.query_selector_all('a[href*="/marketplace/item/"], a[href*="/item/"]')
            print(f"Total publicaciones encontradas: {len(enlaces)}")

            items_procesados = 0
            for a in enlaces:
                href = a.get_attribute("href") or ""
                txt = a.inner_text().strip()
                if not href or len(txt) < 5: continue

                m = re.search(r"/item/(\d+)", href)
                iid = m.group(1) if m else None
                if not iid: continue

                if iid in vistos: continue
                vistos.add(iid)
                post_url = f"https://www.facebook.com/marketplace/item/{iid}/"
                print(f"\nID {iid}: {txt[:80]}...")
                items_procesados += 1

                for item in extraer_ia(txt):
                    p = item.get("precio")
                    if p and 15.0 <= p <= 250.0:
                        bgg = info_bgg(item.get("juego"))
                        if bgg:
                            print(f"🚨 Alerta enviada: {bgg['nombre']} a Q{p}")
                            alerta(bgg["nombre"], p, bgg["rating"], bgg["rank"], bgg["weight"], post_url, bgg["thumb"])

            print(f"\nTotal items nuevos procesados: {items_procesados}")
        except Exception as e: print("Error durante scraping:", e)
        finally: b.close()

    with open("vistos.json", "w") as f: json.dump(list(vistos), f, indent=2)
    print("Finalizado.")

if __name__ == "__main__":
    raspar()
    
