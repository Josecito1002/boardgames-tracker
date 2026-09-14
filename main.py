import os
import json
import urllib.request
import urllib.parse
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from playwright.sync_api import sync_playwright

# Variables de entorno desde GitHub Secrets
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.6-flash"

# 1. Enviar alerta a Telegram
def enviar_alerta(titulo, precio, rating_bgg, rank_bgg, peso_bgg, url_post, thumbnail=None):
    mensaje = (
        f"🎲 <b>¡JUEGO DETECTADO EN MARKETPLACE!</b> 🎲\n\n"
        f"📦 <b>Juego:</b> {titulo}\n"
        f"💰 <b>Precio:</b> Q{precio:.2f}\n"
        f"⭐ <b>BGG Rating:</b> {rating_bgg or 'N/A'}/10\n"
        f"🏆 <b>Ranking BGG:</b> #{rank_bgg or 'N/A'}\n"
        f"🧠 <b>Complejidad:</b> {peso_bgg or 'N/A'}/5\n\n"
        f"🔗 <a href='{url_post}'>Ver en Facebook Marketplace</a>"
    )

    def _post(endpoint, payload):
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    if thumbnail:
        try:
            if _post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", {"chat_id": CHAT_ID, "photo": thumbnail, "caption": mensaje, "parse_mode": "HTML"}).get("ok"):
                return True
        except Exception:
            pass

    return _post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": False}).get("ok", False)

# 2. Consultar BoardGameGeek
def consultar_bgg(nombre_juego):
    try:
        url_search = f"https://boardgamegeek.com/xmlapi2/search?{urllib.parse.urlencode({'query': nombre_juego, 'type': 'boardgame'})}"
        req = urllib.request.Request(url_search, headers={"User-Agent": "FBTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        items = root.findall("item")
        if not items:
            return None
        
        bgg_id = items[0].attrib["id"]
        for it in items:
            ne = it.find("name")
            if ne is not None and ne.attrib.get("value", "").lower() == nombre_juego.lower():
                bgg_id = it.attrib["id"]
                break

        url_thing = f"https://boardgamegeek.com/xmlapi2/thing?id={bgg_id}&stats=1"
        req = urllib.request.Request(url_thing, headers={"User-Agent": "FBTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root_thing = ET.fromstring(resp.read())

        item = root_thing.find("item")
        if item is None:
            return None

        nombre = item.find("name[@type='primary']").attrib.get("value", nombre_juego)
        thumb_elem = item.find("thumbnail")
        thumbnail = thumb_elem.text if thumb_elem is not None else None

        rating, rank, weight = None, None, None
        ratings = item.find(".//ratings")
        if ratings is not None:
            avg = ratings.find("average")
            if avg is not None and avg.attrib.get("value"):
                rating = round(float(avg.attrib["value"]), 2)
            w = ratings.find("averageweight")
            if w is not None and w.attrib.get("value"):
                weight = round(float(w.attrib["value"]), 2)
            for r in ratings.findall(".//rank"):
                if r.attrib.get("name") == "boardgame" and r.attrib.get("value", "").isdigit():
                    rank = int(r.attrib["value"])
                    break

        return {"bgg_id": int(bgg_id), "nombre": nombre, "rating": rating, "rank": rank, "weight": weight, "thumbnail": thumbnail}
    except Exception as e:
        print(f"Error BGG ({nombre_juego}): {e}")
        return None

# 3. Analizar descripciones con Gemini
def extraer_juegos_con_ia(texto):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        "Analiza esta publicacion de Facebook Marketplace en Guatemala. "
        "Extrae cada juego de mesa y su precio en Quetzales. "
        "Si no tiene precio claro pon null. "
        f"Devuelve solo un JSON: [{{\"juego\": \"nombre\", \"precio\": 150.0}}].\\n\\nTexto: {texto}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"}
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return json.loads(res["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as e:
        print(f"Error IA: {e}")
        return []

# 4. Base de datos para no repetir alertas
def cargar_posts_vistos(db_path="vistos.json"):
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def guardar_posts_vistos(vistos, db_path="vistos.json"):
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(list(vistos), f, indent=2)

# 5. Scraper de Facebook Marketplace con Playwright
def raspar_marketplace():
    vistos = cargar_posts_vistos()
    nuevos_encontrados = 0

    url_busqueda = "https://www.facebook.com/marketplace/guatemala/search?query=juegos%20de%20mesa&sortBy=creation_time_descend"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-GT"
        )
        page = context.new_page()
        print(f"Navegando a Marketplace...")
        try:
            page.goto(url_busqueda, timeout=30000)
            page.wait_for_timeout(4000)

            # Extraer enlaces de items
            enlaces = page.query_selector_all('a[href*="/marketplace/item/"]')
            print(f"Se encontraron {len(enlaces)} publicaciones visibles.")

            for enlace in enlaces[:15]:  # Procesar las 15 más recientes
                href = enlace.get_attribute("href")
                if not href:
                    continue

                item_id = href.split("/item/").split("/")[0].split("?")[0]
                if item_id in vistos:
                    continue

                vistos.add(item_id)
                post_url = f"https://www.facebook.com/marketplace/item/{item_id}/"
                texto_tarjeta = enlace.inner_text()

                print(f"\nAnalizando publicación nueva ID {item_id}...")
                items_detectados = extraer_juegos_con_ia(texto_tarjeta)

                for item in items_detectados:
                    nombre = item.get("juego")
                    precio = item.get("precio")

                    # Regla de alerta: Q15 a Q250
                    if precio and 15.0 <= precio <= 250.0:
                        bgg = consultar_bgg(nombre)
                        if bgg:
                            print(f"🚨 Enviando alerta: {bgg['nombre']} a Q{precio}")
                            enviar_alerta(
                                titulo=bgg["nombre"],
                                precio=precio,
                                rating_bgg=bgg["rating"],
                                rank_bgg=bgg["rank"],
                                peso_bgg=bgg["weight"],
                                url_post=post_url,
                                thumbnail=bgg["thumbnail"]
                            )
                            nuevos_encontrados += 1

        except Exception as e:
            print(f"Error durante el raspado: {e}")
        finally:
            browser.close()

    guardar_posts_vistos(vistos)
    print(f"\nFinalizado. {nuevos_encontrados} alertas enviadas.")

if __name__ == "__main__":
    raspar_marketplace()
