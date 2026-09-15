from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import csv
import json
import os
import re
import smtplib
import ssl
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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
URLS_PRIORITARIAS = [
    # Publicación puntual con catálogo grande. Se procesa una sola vez: al
    # enviarse el correo queda en vistos.json y las corridas siguientes la
    # saltan. Se puede borrar de aquí después.
    "https://www.facebook.com/share/p/1EtvvX7izt/",
    # Catálogo cuyo listado va dentro de capturas de una hoja de cálculo.
    "https://www.facebook.com/share/p/19yrhVsL8N/",
]

# 2. Grupos de Facebook a rastrear (pestaña de Compraventa, no el feed general)
URLS_GRUPOS = [
    "https://www.facebook.com/groups/boardgamesgt/buy_sell_discussion/",
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

# IDs que quieres volver a recibir aunque ya estén en vistos.json (por
# ejemplo, si el correo salió pero no alcanzaste a analizarlo). Se sacan del
# historial al arrancar, así que la publicación vuelve a tratarse como nueva
# y, si el envío sale bien, se vuelve a marcar como vista al terminar.
# Da igual escribir "1039264158674649" o "GRUPO_1039264158674649".
# Ojo: esto solo desbloquea el ID; la publicación además tiene que seguir
# apareciendo en el grupo o en la búsqueda para que el scraper la encuentre.
# Si ya no aparece, usa URLS_PRIORITARIAS con su enlace directo.
FORZAR_REENVIO_IDS = [
    # Se registró leyendo el OCR de las capturas y salió corrupto; ahora se
    # lee la hoja que enlaza la publicación. Quitar tras la próxima corrida.
    "3778687745613381",
]

# Descartar las publicaciones de gente que BUSCA un juego ("Busco Bang!
# Reloaded, nuevo o usado") en vez de venderlo. Ponlo en False si también
# quieres enterarte de esas.
DESCARTAR_PUBLICACIONES_DE_BUSQUEDA = True

# Frases de quien busca y de quien vende. Cuando un anuncio tiene de ambas,
# gana la que aparezca primero en el texto.
PATRONES_BUSQUEDA = [
    r"\bbusco\b",
    r"\bbuscando\b",
    r"\bcompro\b",
    r"\bse busca\b",
    r"\bquiero comprar\b",
    r"\balguien (?:tiene|vende|vender[ií]a)\b",
    r"\bqui[eé]n vende\b",
    r"\bd[oó]nde (?:consigo|venden|puedo conseguir)\b",
    r"\bwtb\b",
]
PATRONES_VENTA = [
    r"\bvendo\b",
    r"\bse vende\b",
    r"\ben venta\b",
    r"\bremato\b",
    # Un precio real. Se exige que no empiece en cero porque los anuncios de
    # búsqueda salen justamente con "Q0".
    r"\bq\s?[1-9]\d*",
]

# Líneas que Facebook mete en el texto de la página y que no son parte de la
# publicación: menú, contadores, botones y el alt de las imágenes que todavía
# no cargan (por eso salían decenas de "Facebook" seguidos en los correos).
# Se comparan en minúsculas y sin espacios alrededor, contra la línea entera,
# para no recortar nunca una descripción que contenga alguna de estas palabras.
LINEAS_BASURA_INTERFAZ = {
    "facebook",
    "buscar amigos",
    "enviar mensaje",
    "detalles",
    "ver traducción",
    "ver traduccion",
    "ver más",
    "ver mas",
    "publicación compartida",
    "publicacion compartida",
    "insignia de contenido destacado",
    "actividad reciente",
    "destacados",
    "compartir",
    "me gusta",
    "comentar",
    "guardar",
    "marketplace",
    "inicio",
    "invitar",
    "miembro",
    "más información",
    "mas informacion",
    "vender algo",
}

# Historial en CSV dentro del propio repositorio. El workflow lo commitea al
# terminar, así que se puede leer desde Google Sheets con IMPORTDATA sobre la
# URL "raw" y la hoja se refresca sola, sin credenciales de Google.
ARCHIVO_HISTORIAL = "historial.csv"
COLUMNAS_HISTORIAL = [
    "Fecha", "ID Publicacion", "Juego", "Precio GTQ", "Estado",
    "En Wishlist", "BGG Nombre", "BGG Rating", "BGG Complejidad", "Enlace",
]

# BoardGameGeek tiene API pública y gratuita, así que el rating y la
# complejidad no necesitan ningún modelo de lenguaje. Cada juego se consulta
# una sola vez en su vida: el resultado se guarda en este caché, que también
# se commitea.
CONSULTAR_BGG = True
ARCHIVO_CACHE_BGG = "bgg_cache.json"
MAX_CONSULTAS_BGG_POR_CORRIDA = 40
PAUSA_ENTRE_CONSULTAS_BGG = 1.5  # segundos; BGG limita las peticiones seguidas

# Correo que se envía al terminar una corrida en la que SÍ se notificó al
# menos una publicación. Sirve de detonador para el análisis posterior: en
# vez de revisar el buzón a ciegas cada tanto, se dispara justo cuando hay
# algo nuevo que analizar. Si no se envió ninguna publicación no se manda,
# para no despertar al analizador en vano.
ENVIAR_CORREO_DE_CORRIDA = True
ASUNTO_CORRIDA_COMPLETADA = "[Marketplace Scraper] Corrida completada"

# Se llena durante la corrida con los IDs efectivamente notificados.
PUBLICACIONES_NOTIFICADAS = []

# Cuántas publicaciones nuevas procesar como máximo por corrida.
# Cada una implica abrirla, descargar fotos, pasarles OCR y enviar el correo,
# así que subirlas alarga la corrida y la cantidad de correos de golpe.
MAX_POSTS_GRUPO = 15
MAX_POSTS_MARKETPLACE = 5

# Juegos que quieres seguir sin importar el precio.
WISHLIST = [
    "slay the spire",
    "four souls",  # cubre "Isaac Four Souls" / "The Binding of Isaac: Four Souls"
]


def sanear_para_log(valor):
    """Prepara un texto para imprimirlo sin que GitHub Actions lo tape.

    GitHub reemplaza por '***' cualquier fragmento del log que coincida con
    un secret, y en el caso de un secret MULTILÍNEA lo hace línea por línea.
    Si FB_COOKIES está guardado como JSON "bonito", sus líneas sueltas '['
    y ']' convierten cada corchete del log en '***' — por eso en las
    corridas anteriores se veía '##***endgroup***' en lugar de
    '##[endgroup]' y '(div***role=article***)' en lugar de
    '(div[role=article])'. Además, el ID numérico de la cuenta aparece en
    casi todos los hrefs y puede coincidir con CHAT_ID.

    Para el diagnóstico solo necesitamos el PATRÓN de la ruta, así que:
      - cada dígito se sustituye por '#'
      - los corchetes se sustituyen por paréntesis angulares
    Así ningún fragmento impreso puede coincidir con un secret.
    """
    texto = re.sub(r"\d", "#", str(valor))
    return texto.replace("[", "⟨").replace("]", "⟩")


def lista_para_log(items):
    """Imprime una lista sin usar la repr de Python (que lleva corchetes)."""
    if not items:
        return "(vacío)"
    return " | ".join(sanear_para_log(i) for i in items)


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


def es_publicacion_de_busqueda(texto):
    """True si el anuncio es de alguien que BUSCA un juego, no que lo vende.

    El grupo mezcla ventas con publicaciones tipo "Busco Bang! Reloaded,
    nuevo o usado", que salen con precio Q0 y no sirven para el rastreo.
    """
    t = texto.lower()
    # "no busco cambios" en una venta no la convierte en una búsqueda.
    t = re.sub(r"\bno\s+(?:busco|compro|estoy buscando)\b", " ", t)

    def _primera_posicion(patrones):
        posiciones = [m.start() for p in patrones if (m := re.search(p, t))]
        return min(posiciones) if posiciones else None

    pos_busqueda = _primera_posicion(PATRONES_BUSQUEDA)
    if pos_busqueda is None:
        return False

    pos_venta = _primera_posicion(PATRONES_VENTA)
    if pos_venta is None:
        return True

    # Con señales de ambos tipos, manda la que abre el anuncio.
    return pos_busqueda < pos_venta


def es_publicacion_valida(texto, termino_busqueda=""):
    """
    Evalúa si la publicación es realmente de nuestro interés basándose
    en descartes generales de muebles/objetos ajenos.
    """
    t = texto.lower()

    if DESCARTAR_PUBLICACIONES_DE_BUSQUEDA and es_publicacion_de_busqueda(texto):
        return False

    # Descarte inmediato por muebles o cosas ajenas, salvo que mencione
    # explícitamente algo de juegos de mesa.
    if any(p in t for p in PALABRAS_DESCARTAR):
        if not any(j in t for j in PALABRAS_CLAVE_JUEGO):
            return False

    return True


def limpiar_texto_marketplace(texto_crudo):
    """Corta los bloques estructurales de Facebook sin dañar la descripción."""
    t = texto_crudo.replace("\xa0", " ")
    cortes = [
        "\nSugerencias de hoy",
        "\nInformación del vendedor",
        "\nBúsquedas relacionadas",
        "\nDetalles del vendedor",
    ]
    for corte in cortes:
        if corte in t:
            t = t.split(corte)[0]

    # Los cortes de arriba solo limpian el final; la cabecera de Facebook
    # (menú, contadores, placeholders) se cuela al inicio y llegaba tal cual
    # al correo. Se filtra línea por línea.
    limpias = []
    venia_contador = False
    for linea in t.splitlines():
        actual = linea.strip()
        clave = actual.lower()

        # "Número de notificaciones no leídas" viene seguido del número suelto.
        if clave.startswith(("número de notificaciones", "numero de notificaciones")):
            venia_contador = True
            continue
        if venia_contador and actual.isdigit():
            venia_contador = False
            continue
        venia_contador = False

        if clave in LINEAS_BASURA_INTERFAZ:
            continue
        # Un número solo en su línea es un contador de reacciones o
        # comentarios. Los precios siempre llevan la Q, así que no se pierden.
        if re.fullmatch(r"\d{1,4}", actual):
            continue
        # Líneas que solo traen puntuación suelta: '.', '·', separadores.
        if actual and not re.search(r"[0-9a-záéíóúüñ]", clave):
            continue
        # Placeholders repetidos y espacios en blanco de más.
        if limpias and actual == limpias[-1]:
            continue
        limpias.append(actual)

    return "\n".join(limpias).strip()


def id_desde_url_publicacion(url_final, url_original=""):
    """Deduce un ID estable para una publicación a partir de su URL.

    Facebook usa formas distintas según de dónde venga el enlace, y los
    enlaces cortos /share/p/<codigo>/ redirigen a cualquiera de ellas. Si
    ninguna coincide se usa el código del enlace corto, que al menos es
    único y estable entre corridas — a diferencia de un número de posición,
    que se reutilizaría con la siguiente publicación prioritaria.
    """
    for patron in (
        r"/item/(\d+)",
        r"/commerce/listing/(\d+)",
        r"/posts/(\d+)",
        r"/permalink/(\d+)",
        r"/multi_permalinks/(\d+)",
        r"[?&]story_fbid=(\d+)",
        r"[?&]fbid=(\d+)",
    ):
        encontrado = re.search(patron, url_final)
        if encontrado:
            return encontrado.group(1)

    codigo = re.search(r"/share/p/([A-Za-z0-9]+)", url_original or url_final)
    if codigo:
        return f"share_{codigo.group(1)}"
    return ""


# Frases que aparecen junto a un precio pero no son el nombre de un juego.
# Se comparan sin acentos, en minúsculas y contra la línea ya recortada.
FRASES_NO_JUEGO_EXACTAS = {
    "precio", "oferta", "disponible", "entrego", "entrega", "envio",
    "negociable", "nuevo", "usado", "detalles", "informacion", "total",
    "juegos", "juego", "combo", "promocion", "descuento", "unidad",
}
PREFIJOS_NO_JUEGO = (
    "publicado en", "la ubicacion", "guatemala", "precio", "entrego",
    "entrega", "envio", "pago", "acepto", "interesados", "mas informacion",
    "excelente estado", "buen estado", "que incluye", "horario", "lunes",
    "martes", "miercoles", "jueves", "viernes", "sabados", "sabado",
    "domingos", "domingo", "solo", "unicamente", "tambien", "ademas",
)
# Marcadores donde termina el nombre del juego y empieza la descripción de
# su estado: "catan caja dañada 8/10" es el juego "catan". Se corta en el
# primero que aparezca. Las ediciones entre paréntesis, como "Rummikub
# (Deluxe Edition)", no llevan ninguno y se conservan enteras.
MARCADORES_DE_ESTADO = re.compile(
    r"\b\d{1,2}\s?/\s?10\b"
    r"|\b(?:completo|completa|incompleto|incompleta)\b"
    r"|\b(?:nuevo|nueva|nuevos|nuevas|seminuevo)\b"
    r"|\b(?:usado|usada|abierto|abierta|sellado|sellada)\b"
    r"|\bcaja\s+(?:da[ñn]ad[ao]|abollada|maltratada|rota|sin|con)\b"
    r"|\bdetalles?\s+(?:en|de)\b"
    r"|\bfaltan?\b"
    r"|\b(?:como\s+nuevo|sin\s+uso|poco\s+uso)\b"
    r"|\b(?:excelente|buen|mal|mal[ií]simo)\s+estado\b"
    r"|\ben\s+idioma\b",
    re.IGNORECASE,
)

# Una línea que termina en preposición o artículo está cortada a la mitad
# ("Entrego por", "Sábados por"): no es el nombre de nada.
FINALES_TRUNCADOS = (
    "por", "de", "en", "con", "para", "y", "a", "el", "la", "los", "las",
    "un", "una", "al", "del", "que", "o",
)


def _clave_comparable(texto):
    """Minúsculas, sin acentos y sin puntuación en los bordes."""
    base = unicodedata.normalize("NFD", texto.lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", base).strip(" .,:;-–—¿?¡!*")


def _nombre_de_juego(bruto):
    """Devuelve el nombre de juego utilizable de una línea, o None.

    Existe porque la versión anterior aceptaba cualquier línea con letras
    que tuviera un precio cerca, y acababa registrando "Entrego por",
    "💰 Precio" u "Oferta juegos de mesa" como si fueran juegos.
    """
    # Emojis y símbolos de los bordes: sin esto "💰 Precio" no se reconoce
    # como la palabra "precio".
    nombre = re.sub(r"^[^\w¿¡(]+", "", bruto, flags=re.UNICODE)
    nombre = re.sub(r"[^\w)\]?!.]+$", "", nombre, flags=re.UNICODE).strip()

    # "Juegos de mesa Jenga tradicional" -> "Jenga tradicional".
    # Si tras quitar la categoría no queda nada, era solo la categoría.
    sin_categoria = re.sub(r"^(?:vendo|oferta|nuevos?|nueva)\s+", "", nombre, flags=re.I)
    sin_categoria = re.sub(
        r"^juegos?\s+de\s+mesas?\b[\s:,\-–—]*", "", sin_categoria, flags=re.I
    ).strip()
    se_quito_categoria = sin_categoria != nombre
    nombre = sin_categoria

    clave = _clave_comparable(nombre)
    if len(clave) < 3 or len(nombre) > 80:
        return None
    # Tras quitar la categoría puede quedar un complemento en vez de un
    # nombre: "juegos de mesas con sus bancas" deja "con sus bancas". Solo
    # se comprueba en ese caso, porque hay títulos que empiezan por artículo,
    # como "El Señor de los Anillos".
    if se_quito_categoria and clave.split()[0] in FINALES_TRUNCADOS:
        return None
    if not re.search(r"[a-z]", clave):
        return None
    if clave in FRASES_NO_JUEGO_EXACTAS or clave.startswith(PREFIJOS_NO_JUEGO):
        return None
    if clave.split()[-1] in FINALES_TRUNCADOS:
        return None
    return nombre


def separar_estado(nombre):
    """Parte "catan caja dañada 8/10" en ("catan", "caja dañada 8/10").

    El nombre limpio es el que sirve para buscar en BoardGameGeek y para
    que dos anuncios del mismo juego caigan en la misma fila; el estado se
    conserva aparte en vez de tirarse.
    """
    encontrado = MARCADORES_DE_ESTADO.search(nombre)
    if not encontrado:
        return nombre, ""

    limpio = nombre[: encontrado.start()].strip(" -–—:,;(·")
    nota = nombre[encontrado.start():].strip(" -–—:,;·")
    # Si no queda nombre antes del marcador, la línea era solo estado.
    if len(limpio) < 3:
        return nombre, ""
    return limpio, nota


def extraer_juegos_con_precio(texto):
    """Saca pares (juego, precio) del texto ya limpio de la publicación.

    Existe para que el análisis posterior no tenga que deducir qué línea es
    un juego: las publicaciones de catálogo traen veinte o más juegos, uno
    por línea con su precio, y hacer ese trabajo aquí sale gratis.

    Es una heurística sobre texto libre: prefiere dejar fuera una línea
    dudosa a registrar una frase suelta como si fuera un juego.

    Devuelve una lista de tuplas (nombre, precio_texto, estado) en el orden
    en que aparecen, sin repetir el mismo juego con el mismo precio.
    """
    patron_precio = re.compile(r"Q\s?([\d.,]+)", re.IGNORECASE)

    def _normalizar_precio(bruto):
        # "1,250.00" -> "1250.00"; "150" -> "150"
        return bruto.rstrip(".,").replace(",", "")

    juegos = []
    nombre_pendiente = None
    for linea in texto.splitlines():
        actual = linea.strip(" -–—:·\t")
        if not actual:
            continue

        coincidencia = patron_precio.search(actual)
        if not coincidencia:
            # Puede ser el nombre de un juego cuyo precio viene en la línea
            # siguiente, como pasa cuando Facebook parte la línea.
            nombre_pendiente = _nombre_de_juego(actual)
            continue

        precio = _normalizar_precio(coincidencia.group(1))
        nombre = _nombre_de_juego(actual[: coincidencia.start()])

        if nombre is None:
            # La línea era solo el precio, o texto que no es un juego: se
            # intenta con el nombre de la línea anterior.
            nombre = nombre_pendiente
        nombre_pendiente = None

        if nombre:
            limpio, estado = separar_estado(nombre)
            if (limpio, precio) not in [(j[0], j[1]) for j in juegos]:
                juegos.append((limpio, precio, estado))

    return juegos


def extraer_juegos_de_tabla_ocr(texto_ocr):
    """Lee las listas de juegos que vienen como tabla dentro de una imagen.

    Hay publicaciones cuyo texto es solo "les dejo la lista" y el catálogo
    entero está en capturas de una hoja de cálculo, con columnas
    Juego / Precio / Estado / Idioma y SIN el símbolo Q delante del precio.
    El parser del texto libre no las ve, así que se leen aparte del OCR.

    El precio se reconoce como un token que es únicamente un número de 2 a 5
    dígitos: así "(8/10)", "Copy 2)" o "(2000s" no se confunden con él, que
    es lo que rompía los intentos más simples.
    """
    if not texto_ocr:
        return []

    token_precio = re.compile(r"^\d{2,5}(?:[.,]\d{1,2})?$")
    juegos = []
    for linea in texto_ocr.splitlines():
        actual = linea.strip()
        if not actual or actual.startswith("---"):
            continue

        partes = actual.split()
        posicion = next(
            (i for i, t in enumerate(partes) if token_precio.match(t)), None
        )
        if posicion is None or posicion == 0:
            continue

        precio = partes[posicion].replace(",", ".")
        try:
            if not 20 <= float(precio) <= 20000:
                continue
        except ValueError:
            continue

        nombre = _nombre_de_juego(" ".join(partes[:posicion]))
        if not nombre:
            continue
        estado = " ".join(partes[posicion + 1:]).strip(" -–—:,;·'\"")
        # Una fila de la tabla siempre trae algo después del precio (estado,
        # idioma). Si no hay nada, la línea no era una fila: así se cuela el
        # nombre de quien publica y otros restos de la captura.
        if not estado:
            continue
        if (nombre, precio) not in [(j[0], j[1]) for j in juegos]:
            juegos.append((nombre, precio, estado))

    return juegos


def _clave_juego(juego):
    """Nombre y precio comparables: "350" y "350.00" son el mismo precio."""
    try:
        precio = f"{float(str(juego[1]).replace(',', '.')):.2f}"
    except ValueError:
        precio = str(juego[1])
    return (_clave_comparable(juego[0]), precio)


def extraer_juegos_de_google_sheet(texto):
    """Lee el catálogo desde el Google Sheet que enlaza la publicación.

    Varios vendedores publican "les dejo un drive por si es mas facil" con el
    enlace a una hoja, y adjuntan capturas de esa misma hoja. Leer la hoja
    original da datos exactos; hacer OCR de la captura da "Rush 8 Bash" y
    "ravel Blokus". Si la hoja es pública se exporta como CSV, que no
    necesita credenciales.
    """
    if not texto:
        return []
    enlace = re.search(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{20,})", texto)
    if not enlace:
        return []

    url_csv = (
        f"https://docs.google.com/spreadsheets/d/{enlace.group(1)}/export?format=csv"
    )
    try:
        peticion = urllib.request.Request(
            url_csv,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(peticion, timeout=25) as respuesta:
            contenido = respuesta.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"   Aviso: no se pudo leer la hoja enlazada: {e}", flush=True)
        return []

    filas = list(csv.reader(contenido.splitlines()))
    if not filas:
        return []

    # La cabecera no siempre está en la primera fila: se busca la primera que
    # tenga a la vez una columna de juego y una de precio.
    def _indices(cabecera):
        col_juego = col_precio = None
        otras = []
        for i, celda in enumerate(cabecera):
            clave = _clave_comparable(celda)
            if col_juego is None and clave in ("juego", "juegos", "game", "nombre", "titulo"):
                col_juego = i
            elif col_precio is None and clave in ("precio", "precios", "price", "costo", "valor"):
                col_precio = i
            elif clave:
                otras.append(i)
        return col_juego, col_precio, otras

    inicio = col_juego = col_precio = None
    otras = []
    for n, fila in enumerate(filas[:10]):
        col_juego, col_precio, otras = _indices(fila)
        if col_juego is not None and col_precio is not None:
            inicio = n + 1
            break
    if inicio is None:
        print("   Aviso: la hoja enlazada no tiene columnas de juego y precio.", flush=True)
        return []

    juegos = []
    for fila in filas[inicio:]:
        if len(fila) <= max(col_juego, col_precio):
            continue
        nombre = _nombre_de_juego(fila[col_juego])
        precio = fila[col_precio].strip().replace(",", ".").lstrip("Qq$ ")
        if not nombre or not precio:
            continue
        estado = " ".join(
            fila[i].strip() for i in otras if i < len(fila) and fila[i].strip()
        )
        if (nombre, precio) not in [(j[0], j[1]) for j in juegos]:
            juegos.append((nombre, precio, estado))

    print(f"   📄 Hoja enlazada leída: {len(juegos)} juegos.", flush=True)
    return juegos


def combinar_juegos(*listas):
    """Une varias listas de juegos sin repetir el mismo juego con el mismo precio.

    El mismo catálogo suele venir a la vez en la descripción y en la captura,
    así que sin comparar los precios normalizados se duplicaría cada fila.
    """
    combinados = []
    vistas = set()
    for lista in listas:
        for juego in lista:
            clave = _clave_juego(juego)
            if clave not in vistas:
                vistas.add(clave)
                combinados.append(juego)
    return combinados


def formatear_juegos_para_correo(juegos):
    """Bloque de texto plano, una línea por juego, fácil de leer en bloque."""
    if not juegos:
        return "ninguno (no se encontraron líneas con precio en quetzales)"
    return "\n".join(
        f"{nombre} | {precio} | {estado}" for nombre, precio, estado in juegos
    )


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


def _leer_cache_bgg():
    if os.path.exists(ARCHIVO_CACHE_BGG):
        try:
            with open(ARCHIVO_CACHE_BGG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _guardar_cache_bgg(cache):
    try:
        with open(ARCHIVO_CACHE_BGG, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False, sort_keys=True)
    except Exception as e:
        print(f"   Aviso: no se pudo guardar el caché de BGG: {e}", flush=True)


def _pedir_xml(url, timeout=20):
    # BoardGameGeek responde 401 a los agentes que no parecen un navegador,
    # que es lo que devolvía con un User-Agent propio del script.
    peticion = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            ),
            "Accept": "application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        return ET.fromstring(respuesta.read())


def consultar_bgg(nombre):
    """Rating y complejidad de un juego en BoardGameGeek.

    Devuelve un dict con bgg_nombre, rating y complejidad; vacío si no se
    encuentra o si la consulta falla. Nunca lanza: un fallo de red no debe
    tumbar la corrida, y la columna vacía es una respuesta aceptable.
    """
    try:
        consulta = urllib.parse.quote(nombre)
        raiz = _pedir_xml(
            f"https://boardgamegeek.com/xmlapi2/search"
            f"?query={consulta}&type=boardgame"
        )
        item = raiz.find("item")
        if item is None:
            # Búsqueda válida sin resultados: eso sí se puede cachear.
            return {"bgg_nombre": "", "rating": "", "complejidad": ""}
        bgg_id = item.get("id")
        nombre_bgg = item.find("name")
        nombre_bgg = nombre_bgg.get("value") if nombre_bgg is not None else ""

        time.sleep(PAUSA_ENTRE_CONSULTAS_BGG)
        detalle = _pedir_xml(
            f"https://boardgamegeek.com/xmlapi2/thing?id={bgg_id}&stats=1"
        )
        promedio = detalle.find(".//statistics/ratings/average")
        peso = detalle.find(".//statistics/ratings/averageweight")
        return {
            "bgg_nombre": nombre_bgg,
            "rating": round(float(promedio.get("value")), 2) if promedio is not None else "",
            "complejidad": round(float(peso.get("value")), 2) if peso is not None else "",
        }
    except Exception as e:
        print(f"   Aviso: BGG falló para {nombre!r}: {e}", flush=True)
        return {}


def enriquecer_con_bgg(juegos):
    """Añade los datos de BGG a cada juego, consultando solo los nuevos."""
    if not (CONSULTAR_BGG and juegos):
        return {}

    cache = _leer_cache_bgg()
    consultas = 0
    for nombre, _precio, _estado in juegos:
        clave = _clave_comparable(nombre)
        if clave in cache:
            continue
        if consultas >= MAX_CONSULTAS_BGG_POR_CORRIDA:
            print(
                "   Aviso: alcanzado el tope de consultas a BGG en esta"
                " corrida; el resto queda sin datos hasta la próxima.",
                flush=True,
            )
            break
        datos = consultar_bgg(nombre)
        consultas += 1
        # Solo se cachea un resultado bueno. Cachear el fallo convertiría un
        # corte de red o un bloqueo temporal en un "sin datos" permanente.
        if datos:
            cache[clave] = datos
        time.sleep(PAUSA_ENTRE_CONSULTAS_BGG)

    if consultas:
        _guardar_cache_bgg(cache)
        print(f"   📚 BGG: {consultas} juegos consultados, el resto del caché.", flush=True)
    return cache


def _precio_plausible(precio):
    """Descarta filas sin un precio utilizable antes de escribirlas."""
    try:
        valor = float(str(precio).replace(",", "."))
    except (TypeError, ValueError):
        return False
    return 1 <= valor <= 100000


def registrar_en_historial(iid, url_post, juegos):
    """Escribe una fila por juego en el CSV que alimenta la hoja de cálculo.

    Es idempotente: si el ID ya tiene filas, no vuelve a escribir. Así una
    corrida repetida no duplica el catálogo.
    """
    if not juegos:
        return 0

    existentes = set()
    if os.path.exists(ARCHIVO_HISTORIAL):
        try:
            with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8", newline="") as f:
                existentes = {fila.get("ID Publicacion", "") for fila in csv.DictReader(f)}
        except Exception:
            pass
    if str(iid) in existentes:
        print(f"   El historial ya tiene el ID {iid}; no se reescribe.", flush=True)
        return 0

    cache = enriquecer_con_bgg(juegos)
    fecha = time.strftime("%Y-%m-%d")
    es_nuevo = not os.path.exists(ARCHIVO_HISTORIAL)
    try:
        with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=COLUMNAS_HISTORIAL)
            if es_nuevo:
                escritor.writeheader()
            for nombre, precio, estado in juegos:
                if not _precio_plausible(precio):
                    continue
                datos = cache.get(_clave_comparable(nombre), {})
                en_wishlist = any(j in nombre.lower() for j in WISHLIST)
                escritor.writerow({
                    "Fecha": fecha,
                    "ID Publicacion": iid,
                    "Juego": nombre,
                    "Precio GTQ": precio,
                    "Estado": estado,
                    "En Wishlist": "sí" if en_wishlist else "",
                    "BGG Nombre": datos.get("bgg_nombre", ""),
                    "BGG Rating": datos.get("rating", ""),
                    "BGG Complejidad": datos.get("complejidad", ""),
                    "Enlace": url_post,
                })
        print(f"   🗒️ Historial: {len(juegos)} filas añadidas para {iid}.", flush=True)
        return len(juegos)
    except Exception as e:
        print(f"   Error al escribir el historial: {e}", flush=True)
        return 0


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

        # Bloque ya parseado: evita que el análisis posterior tenga que
        # deducir qué línea del texto libre es un juego con precio.
        # Si la publicación enlaza su hoja y se pudo leer, esa es la fuente
        # buena y el OCR de sus capturas solo añadiría el mismo catálogo mal
        # transcrito ("Rush 8 Bash" junto a "Rush & Bash"), que el dedupe no
        # puede unir porque los nombres difieren.
        desde_hoja = extraer_juegos_de_google_sheet(texto_post)
        fuentes = [desde_hoja, extraer_juegos_con_precio(texto_post)]
        if not desde_hoja:
            fuentes.append(extraer_juegos_de_tabla_ocr(texto_ocr))
        juegos = combinar_juegos(*fuentes)
        bloque_juegos = formatear_juegos_para_correo(juegos)
        registrar_en_historial(iid, url_post, juegos)

        html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #222;">
            <h2>🎲 Publicación detectada: ID {iid}</h2>
            <p><b>Enlace directo:</b> <a href="{url_post}">{url_post}</a></p>
            <hr>
            <h3>Juegos detectados ({len(juegos)}) — formato "Juego | Precio GTQ | Estado":</h3>
            <pre style="background: #eefbf1; padding: 12px; border-radius: 6px; white-space: pre-wrap; font-size: 14px;">{bloque_juegos}</pre>
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
        PUBLICACIONES_NOTIFICADAS.append(str(iid))
        return True
    except Exception as e:
        print(f"Error al enviar correo: {e}", flush=True)
        return False


def enviar_correo_de_corrida(ids_notificados):
    """Avisa por correo que la corrida terminó y cuántas publicaciones salieron.

    El asunto es fijo y distinto al de las publicaciones, para que se pueda
    usar como disparador sin que coincida con la búsqueda de éstas.
    """
    if not (ENVIAR_CORREO_DE_CORRIDA and ids_notificados):
        return False
    if not GMAIL_USER or not GMAIL_APP_PASS:
        return False

    try:
        cuerpo = (
            f"Publicaciones notificadas en esta corrida: {len(ids_notificados)}\n"
            f"Terminada: {time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
            "IDs:\n" + "\n".join(f"- {i}" for i in ids_notificados)
        )
        msg = MIMEText(cuerpo, "plain", "utf-8")
        msg["Subject"] = ASUNTO_CORRIDA_COMPLETADA
        msg["From"] = f"Marketplace Scraper <{GMAIL_USER}>"
        msg["To"] = GMAIL_USER

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())

        print(
            f"🔔 Aviso de corrida enviado ({len(ids_notificados)} publicaciones).",
            flush=True,
        )
        return True
    except Exception as e:
        print(f"Error al enviar el aviso de corrida: {e}", flush=True)
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

    # Estrategia 3 (respaldo): barrido directo de las imágenes que la página
    # ya muestra, sin abrir el visor. Las páginas de /commerce/listing/ no
    # usan el visor de fotos del feed, así que las estrategias de clic no
    # encuentran nada y hacía falta leerlas tal cual están.
    if not rutas:
        def _mejor_src(img):
            # A veces el src es un placeholder y la foto real solo viaja en
            # srcset; se toma la última entrada, que es la de mayor tamaño.
            src = img.get_attribute("src") or ""
            if src.startswith("http") and "scontent" in src:
                return src
            srcset = img.get_attribute("srcset") or ""
            for trozo in reversed([t.strip() for t in srcset.split(",") if t.strip()]):
                candidato = trozo.split(" ")[0]
                if candidato.startswith("http") and "scontent" in candidato:
                    return candidato
            return src

        def _barrer_imagenes():
            """Guarda las imágenes grandes visibles. Devuelve cuántas nuevas."""
            nuevas = 0
            for im in page.query_selector_all("img"):
                try:
                    box = im.bounding_box()
                    if not box or box["width"] < 200 or box["height"] < 200:
                        continue
                    if _guardar_si_es_nueva(_mejor_src(im)):
                        nuevas += 1
                except Exception:
                    continue
            return nuevas

        def _avanzar_carrusel():
            """Pasa a la siguiente foto del anuncio; False si no se pudo."""
            for selector in (
                'div[role="main"] [aria-label*="iguiente"]',
                'div[role="main"] [aria-label*="ext photo"]',
                'div[role="main"] [aria-label*="Next"]',
            ):
                for boton in page.query_selector_all(selector):
                    try:
                        if boton.is_visible():
                            boton.click(timeout=1500)
                            page.wait_for_timeout(900)
                            return True
                    except Exception:
                        continue
            return False

        total_imgs = len(page.query_selector_all("img"))
        _barrer_imagenes()

        # El carrusel de /commerce/listing/ solo monta la foto visible, así que
        # las demás aparecen únicamente al ir pasando. Se recorre hasta que dos
        # avances seguidos no aporten nada nuevo.
        url_anuncio = page.url
        sin_novedad = 0
        for _ in range(12):
            if sin_novedad >= 2 or not _avanzar_carrusel():
                break
            if page.url != url_anuncio:
                # Un clic sacó de la publicación; lo que se vea ya no es suyo.
                break
            sin_novedad = 0 if _barrer_imagenes() else sin_novedad + 1

        print(
            f"   🔎 Respaldo de fotos — imágenes en la página:"
            f" {total_imgs}, rescatadas: {len(rutas)}",
            flush=True,
        )

    print(f"   ✅ Total fotos descargadas para ID {iid}: {len(rutas)}", flush=True)
    return rutas


def extraer_publicaciones_del_html(html, slug_grupo):
    """Saca IDs de publicaciones del HTML crudo del grupo.

    Facebook ya casi no entrega <a href="/groups/x/posts/123"> en el feed:
    los enlaces se arman con JavaScript al hacer clic, así que buscarlos con
    query_selector_all devuelve 0 aunque el feed sí haya cargado. Los IDs,
    en cambio, sí viajan en el payload JSON incrustado en la página, y de ahí
    se puede reconstruir el permalink canónico.

    Se quitan las barras invertidas primero porque dentro del JSON incrustado
    las comillas y las barras vienen escapadas (\"post_id\":\"123\",
    \/groups\/...).
    """
    plano = html.replace("\\", "")
    ids = []

    # Solo rutas que nombran explícitamente al grupo. Los campos sueltos del
    # JSON ("post_id", "top_level_post_id", "story_fbid") se probaron y dan
    # falsos positivos: son IDs de publicaciones destacadas o de otros
    # contextos, y al abrirlos Facebook redirige al feed del grupo, así que
    # todas terminaban entregando el MISMO contenido.
    patrones = [
        rf"/groups/{re.escape(slug_grupo)}/posts/(\d{{8,}})",
        rf"/groups/{re.escape(slug_grupo)}/permalink/(\d{{8,}})",
        rf"/groups/{re.escape(slug_grupo)}/multi_permalinks/(\d{{8,}})",
    ]
    for patron in patrones:
        for pid in re.findall(patron, plano):
            if pid not in ids:
                ids.append(pid)

    return [
        (pid, f"https://www.facebook.com/groups/{slug_grupo}/posts/{pid}/")
        for pid in ids
    ]


def extraer_listings_de_comercio(page):
    """Saca los anuncios de la pestaña Compraventa del grupo.

    En /buy_sell_discussion/ las ventas no son publicaciones normales: cada
    tarjeta apunta a /commerce/listing/<id>/ y no existe ningún enlace con
    /posts/ ni /permalink/. Por eso el scraper no encontraba nada aunque la
    página tuviera decenas de anuncios cargados.
    """
    vistos_ids = []
    resultados = []
    enlaces = page.query_selector_all('a[href*="/commerce/listing/"]')
    for a in enlaces:
        href = a.get_attribute("href") or ""
        m = re.search(r"/commerce/listing/(\d{8,})", href)
        if m and m.group(1) not in vistos_ids:
            vistos_ids.append(m.group(1))
            resultados.append(
                (m.group(1), f"https://www.facebook.com/commerce/listing/{m.group(1)}/")
            )
    # Cada tarjeta suele traer varios enlaces al mismo anuncio (imagen, título,
    # precio...), así que la diferencia entre ambos números dice si faltan
    # tarjetas por cargar o si solo eran enlaces repetidos.
    print(
        f"   🔎 Enlaces a anuncios: {len(enlaces)} —"
        f" anuncios distintos: {len(resultados)}",
        flush=True,
    )
    return resultados


def esperar_feed_del_grupo(page, intentos=25, estables_necesarios=3):
    """Espera a que el feed del grupo deje de crecer antes de leerlo.

    Sin esto se lee la página cuando todavía está el esqueleto de carga (los
    'Facebook Facebook Facebook...' que salen en el log son el alt de las
    imágenes placeholder), y se detectan solo los 2 bloques del carrusel de
    'Destacados'.
    """
    try:
        page.wait_for_selector('div[role="feed"]', timeout=15000)
    except Exception:
        pass

    def _contar():
        # En la pestaña Compraventa los anuncios no son div role=article, así
        # que contar solo bloques haría que el scroll se detuviera enseguida.
        return len(page.query_selector_all('div[role="article"]')) + len(
            page.query_selector_all('a[href*="/commerce/listing/"]')
        )

    # Una sola pasada sin crecimiento no significa que ya no haya más: la
    # carga diferida de Facebook a veces tarda más que la espera, así que se
    # exigen varias pasadas estables seguidas antes de darse por satisfecho.
    previos = -1
    estables = 0
    for _ in range(intentos):
        actuales = _contar()
        if actuales == previos:
            estables += 1
            if estables >= estables_necesarios and actuales >= 6:
                break
        else:
            estables = 0
        previos = actuales
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1800)
    return _contar()


def resolver_url_grupo(page, url_grupo):
    """Normaliza la URL de un grupo/pestaña de grupo de Facebook a
    www.facebook.com, preservando cualquier sub-ruta (ej. /buy_sell_discussion/)
    y agregando orden cronológico si no se especificó otro parámetro de orden.
    Si url_grupo es un link de invitación corto (facebook.com/share/g/<code>/)
    sin un /groups/<algo>/ explícito, lo visita primero y sigue la
    redirección de Facebook para obtener la URL canónica.
    """

    def _normalizar(url):
        url = re.sub(
            r"https?://(m|mbasic|web)\.facebook\.com",
            "https://www.facebook.com",
            url,
        )
        if "sorting_setting" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}sorting_setting=CHRONOLOGICAL"
        return url

    if re.search(r"facebook\.com/groups/[^/?]+", url_grupo):
        return _normalizar(url_grupo)

    # No vino con /groups/<algo>/ directo (ej. un link de invitación /share/g/...):
    # lo visitamos y vemos a dónde redirige Facebook.
    page.goto(url_grupo, timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    if re.search(r"facebook\.com/groups/[^/?]+", page.url):
        return _normalizar(page.url)

    print(
        f"   ⚠️ No se pudo resolver un ID/nombre de grupo desde: {url_grupo}\n"
        f"      URL final tras la redirección: {page.url}\n"
        "      Reemplaza URLS_GRUPOS por la URL de escritorio del grupo"
        " (facebook.com/groups/<numero-o-nombre>/).",
        flush=True,
    )
    return None


def raspar_grupo(page, url_grupo, vistos, max_posts=MAX_POSTS_GRUPO):
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

        esperar_feed_del_grupo(page)
        articulos = page.query_selector_all('div[role="article"]')
        print(
            f"   Bloques de publicación (div role=article) detectados:"
            f" {len(articulos)}",
            flush=True,
        )

        enlaces = page.query_selector_all(
            'a[href*="/posts/"], a[href*="/permalink/"],'
            ' a[href*="/multi_permalinks/"]'
        )
        print(f"   Links con /posts|permalink| detectados: {len(enlaces)}", flush=True)

        # Diagnóstico: si no encontramos links con el patrón esperado,
        # mostrar qué rutas SÍ existen para descubrir el formato actual.
        # Todo pasa por sanear_para_log() para que GitHub no lo tape con
        # "***": dígitos a '#' (pueden coincidir con CHAT_ID) y corchetes a
        # '⟨⟩' (un secret multilínea como FB_COOKIES en JSON "bonito" hace
        # que GitHub enmascare cada '[' y ']' sueltos del log).
        if len(enlaces) == 0:
            print(
                "   🔎 Diagnóstico v# activo"
                " (dígitos a #, corchetes a ⟨⟩ para evitar el enmascarado)",
                flush=True,
            )
            # 1) Rutas dentro de los bloques detectados. Ojo: los primeros
            #    bloques suelen ser el carrusel de "Destacados" y no
            #    publicaciones reales, por eso más abajo revisamos también
            #    TODOS los links de la página.
            if articulos:
                print(
                    "   🔎 Rutas dentro de los bloques detectados"
                    " (dígitos enmascarados con #):",
                    flush=True,
                )
                for i, art in enumerate(articulos[:3], 1):
                    rutas = []
                    for a in art.query_selector_all("a[href]"):
                        h = a.get_attribute("href")
                        if not h:
                            continue
                        ruta = urllib.parse.urlparse(h).path
                        if ruta and ruta not in rutas:
                            rutas.append(ruta)
                    print(
                        f"      Bloque {i}"
                        f" ({len(rutas)} rutas): {lista_para_log(rutas[:15])}",
                        flush=True,
                    )

            # 2) Censo de TODOS los links de la página, no solo los que están
            #    dentro de los bloques. Agrupamos rutas idénticas (ya
            #    enmascaradas) para ver de un vistazo qué formatos hay.
            todos = page.query_selector_all("a[href]")
            print(
                f"   🔎 Links totales en la página: {len(todos)}"
                " — rutas más comunes (dígitos enmascarados con #):",
                flush=True,
            )
            conteo_rutas = {}
            for a in todos:
                h = a.get_attribute("href")
                if not h:
                    continue
                ruta = urllib.parse.urlparse(h).path
                if not ruta or ruta == "/":
                    continue
                patron = sanear_para_log(ruta)
                conteo_rutas[patron] = conteo_rutas.get(patron, 0) + 1
            for patron, veces in sorted(
                conteo_rutas.items(), key=lambda kv: kv[1], reverse=True
            )[:30]:
                print(f"      {veces:>3}x {patron}", flush=True)

            # 3) Rutas que huelen a publicación aunque no usen /posts/ ni
            #    /permalink/ (story_fbid, ?story, /groups/<id>/<algo>, etc.).
            sospechosas = sorted(
                patron
                for patron in conteo_rutas
                if "/groups/" in patron
                and patron.rstrip("/").count("/") >= 3
            )
            print(
                "   🔎 Rutas candidatas a publicación dentro del grupo:"
                f" {lista_para_log(sospechosas[:20])}",
                flush=True,
            )

        # Candidatos: primero los <a href> clásicos, y si el feed no trae
        # ninguno (lo normal hoy: Facebook arma los links con JavaScript al
        # hacer clic), los IDs incrustados en el payload JSON de la página.
        candidatos = []
        for a in enlaces:
            href = a.get_attribute("href") or ""
            m = re.search(r"/(?:posts|permalink|multi_permalinks)/(\d+)", href)
            if m:
                candidatos.append((m.group(1), href.split("?")[0]))

        if not candidatos:
            # La pestaña Compraventa publica los anuncios como
            # /commerce/listing/<id>/, no como publicaciones del grupo.
            candidatos = extraer_listings_de_comercio(page)
            print(
                f"   🔎 Anuncios de Compraventa encontrados:"
                f" {len(candidatos)}",
                flush=True,
            )

        slug_grupo = re.search(r"/groups/([^/?]+)", url_resuelta)
        slug_grupo = slug_grupo.group(1) if slug_grupo else None
        if not candidatos and slug_grupo:
            candidatos = extraer_publicaciones_del_html(page.content(), slug_grupo)
            print(
                f"   🔎 IDs de publicación encontrados en el HTML de la"
                f" página: {len(candidatos)}",
                flush=True,
            )

        posts_pendientes = []
        for pid, url_post in candidatos:
            iid = f"GRUPO_{pid}"
            if (
                iid not in vistos
                and pid not in [p[0] for p in posts_pendientes]
                and pid != "0"
            ):
                posts_pendientes.append((pid, url_post))

        total = min(len(posts_pendientes), max_posts)
        print(f"   Publicaciones detectadas en el grupo: {total}", flush=True)

        for idx, (pid, post_url) in enumerate(posts_pendientes[:total], 1):
            iid = f"GRUPO_{pid}"
            print(f"   {idx}/{total} · Abriendo post del grupo ID {pid}...", flush=True)
            try:
                page.goto(post_url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)

                # Si el ID no era una publicación real, Facebook redirige al
                # feed del grupo y se acabaría leyendo el mismo contenido una
                # y otra vez (así se enviaron 4 correos idénticos). Se
                # comprueba que la URL final siga apuntando al ID pedido.
                if pid not in page.url:
                    print(
                        f"      ⚠️ Facebook redirigió fuera de la publicación"
                        f" {pid}; se omite para no reenviar contenido repetido.",
                        flush=True,
                    )
                    continue

                expandir_todo_el_texto(page)

                main_el = page.query_selector(
                    'div[role="main"] div[data-ad-preview="message"]'
                ) or page.query_selector('div[role="main"]')
                texto_crudo = main_el.inner_text() if main_el else page.inner_text("body")
                texto_limpio = limpiar_texto_marketplace(texto_crudo)

                # AQUÍ SE APLICA EL NUEVO FILTRO PARA GRUPOS
                if not es_publicacion_valida(texto_limpio):
                    motivo_descarte = (
                        "es alguien buscando un juego, no vendiéndolo"
                        if es_publicacion_de_busqueda(texto_limpio)
                        else "no pasó el filtro de contenido"
                    )
                    print(f"      ↩️ Descartada: {motivo_descarte}.", flush=True)
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


def olvidar_ids_forzados(vistos):
    """Saca de vistos los IDs marcados para reenvío en FORZAR_REENVIO_IDS."""
    pedidos = 0
    sacados = []
    for entrada in FORZAR_REENVIO_IDS:
        base = str(entrada).strip()
        if not base:
            continue
        pedidos += 1
        if base.startswith("GRUPO_"):
            base = base[len("GRUPO_"):]
        # No se sabe de qué fuente venía el ID, así que se prueban las dos
        # formas con que se guarda.
        for variante in (base, f"GRUPO_{base}"):
            if variante in vistos:
                vistos.discard(variante)
                sacados.append(variante)

    if pedidos:
        # Sin enmascarar: son IDs de publicaciones, igual que los que ya se
        # imprimen al abrirlas, y aquí hace falta saber cuáles se liberaron.
        detalle = " | ".join(sacados) if sacados else "ninguno estaba"
        print(
            f"♻️ Reenvío forzado: {len(sacados)} de {pedidos} IDs"
            f" sacados del historial ({detalle}).",
            flush=True,
        )
    return vistos


def raspar():
    vistos = set()
    if os.path.exists("vistos.json"):
        try:
            with open("vistos.json", "r", encoding="utf-8") as f:
                vistos = set(json.load(f))
        except Exception:
            pass

    olvidar_ids_forzados(vistos)

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
            print(f"\nPRIORITARIO {idx}/{len(URLS_PRIORITARIAS)} · Abriendo: {url_prio}", flush=True)
            try:
                page.goto(url_prio, timeout=35000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                real_url = page.url
                iid = id_desde_url_publicacion(real_url, url_prio)
                if not iid:
                    print(
                        f"   ⚠️ No se pudo deducir un ID de {real_url};"
                        " se omite para no guardarla con un ID inestable.",
                        flush=True,
                    )
                    continue

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

                total_termino = min(len(iids_pendientes), MAX_POSTS_MARKETPLACE)
                print(f"   Nuevos avisos para '{termino}': {total_termino}", flush=True)

                for idx, iid in enumerate(iids_pendientes[:total_termino], 1):
                    post_url = f"https://www.facebook.com/marketplace/item/{iid}/"
                    print(f"   {idx}/{total_termino} · Abriendo ID {iid}...", flush=True)

                    try:
                        page.goto(post_url, timeout=20000, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)

                        expandir_todo_el_texto(page)

                        main_el = page.query_selector('div[role="main"]')
                        texto_crudo = main_el.inner_text() if main_el else page.inner_text("body")

                        # VALIDACIÓN FINAL DEL CONTENIDO COMPLETO
                        if not es_publicacion_valida(texto_crudo, termino_busqueda=termino):
                            motivo_descarte = (
                                "es alguien buscando un juego, no vendiéndolo"
                                if es_publicacion_de_busqueda(texto_crudo)
                                else "no pasó el filtro de contenido"
                            )
                            print(f"      ↩️ Descartada: {motivo_descarte}.", flush=True)
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

    # Al final, y solo si hubo algo que notificar: así el análisis posterior
    # se dispara con el historial ya guardado.
    enviar_correo_de_corrida(PUBLICACIONES_NOTIFICADAS)

if __name__ == "__main__":
    raspar()
