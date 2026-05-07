"""
Smart Idiomas - Agendador automático de clases
"""

import asyncio
import os
import sys
from datetime import datetime
import pytz

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

BASE_URL   = "https://schoolpack.smart.edu.co/idiomas"
LOGIN_URL  = f"{BASE_URL}/alumnos.aspx"
PLANES_URL = f"{BASE_URL}/wv0527.aspx?2UxxJsznnhFnikyCHt5r8u3UnECcT9qxNq7OemMxcG7Kag2xFv8lv6S4FQbMbYAEsD77lQVW8NPwj7DUz1OG8Q=="

USUARIO  = os.environ["SMART_USUARIO"]
PASSWORD = os.environ["SMART_PASSWORD"]
PLAN_COD = os.environ.get("SMART_PLAN", "INGA1B2")

HORAS = ["18:00", "19:30"]

ZONA_COL = pytz.timezone("America/Bogota")

def log(msg):
    print(f"[{datetime.now(ZONA_COL).strftime('%H:%M:%S')}] {msg}", flush=True)

async def esperar(ms=800):
    await asyncio.sleep(ms / 1000)

async def screenshot(page, nombre="error_screenshot.png"):
    try:
        await page.screenshot(path=nombre, full_page=True)
        log(f"   📸 {nombre}")
    except:
        pass

# ─── Login ─────────────────────────────────────────────────────────────────────

async def hacer_login(page):
    log("🔐 Login...")
    await page.goto(LOGIN_URL, wait_until="load")
    if "wv0480" in page.url or "wv0527" in page.url:
        log("✅ Sesión activa")
        return

    await page.type("#vUSUCOD", USUARIO, delay=80)
    await page.type("#vPASS", PASSWORD, delay=80)
    await esperar(500)
    await page.keyboard.press("Tab")
    await esperar(300)
    await page.click("#BUTTON1")
    await esperar(3000)

    # Cerrar modal informativa
    await esperar(1500)
    for p in page.context.pages:
        if "msje" in p.url:
            log("   Modal popup — cerrando...")
            try: await p.click("#BUTTON1")
            except: await p.close()
            await esperar(2000)
            break
    else:
        for selector in ["input[value='Regresar']", "img[src*='exitIcon']", ".gx-popup-close"]:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    log(f"   Modal en página — cerrando con {selector}...")
                    await btn.click()
                    await esperar(2000)
                    break
            except:
                continue

    # Esperar URL destino (sin networkidle — la plataforma tiene polling)
    for _ in range(20):
        if "wv0480" in page.url or "wv0527" in page.url:
            break
        await esperar(500)

    log(f"   URL: {page.url}")
    if "wv0480" not in page.url and "wv0527" not in page.url:
        await screenshot(page)
        raise Exception(f"Login fallido — URL: {page.url}")
    log("✅ Login OK")


# ─── Navegar a Programación ────────────────────────────────────────────────────

async def ir_a_programacion(page):
    log("📋 Ir a Programación...")
    if "wv0527" in page.url:
        return
    try:
        prog = page.locator("img[src*='PROGRAMACION'], a:has-text('Programaci'), [title*='rogramaci']").first
        if await prog.count() > 0:
            async with page.expect_navigation(timeout=15000, wait_until="load"):
                await prog.click()
            return
    except PlaywrightTimeout:
        pass
    await page.goto(PLANES_URL, wait_until="load")
    log(f"   URL: {page.url}")


# ─── Seleccionar plan y abrir iframe de clases ────────────────────────────────

async def seleccionar_plan(page):
    log(f"   Esperando grilla de planes...")
    await page.wait_for_selector(f"td:has-text('{PLAN_COD}')", timeout=15000)

    fila = page.locator("tr[data-gxrow]").filter(has_text=PLAN_COD).first
    if await fila.count() == 0:
        fila = page.locator(f"td:has-text('{PLAN_COD}')").first
    log(f"   Click en plan {PLAN_COD}...")
    await fila.click()
    await esperar(600)

    log("   Click en Iniciar...")
    await page.locator("#W0030BUTTON1").focus()
    await esperar(200)
    await page.locator("#W0030BUTTON1").click()
    await esperar(2000)

    # wv0613 carga dentro de un IFRAME — esperar que aparezca
    log("   Esperando iframe wv0613...")
    try:
        await page.wait_for_selector("iframe[src*='wv0613']", timeout=20000)
    except PlaywrightTimeout:
        await screenshot(page, "error_sin_iframe.png")
        raise Exception("Iframe wv0613 no apareció tras click en Iniciar")

    # Obtener el frame usando frame_locator (API correcta de Playwright)
    frame = page.frame_locator("iframe[src*='wv0613']")

    # Esperar que el iframe cargue el botón Asignar
    log("   Esperando contenido del iframe...")
    await frame.locator("#BUTTON1[value='Asignar']").wait_for(timeout=15000)
    log("✅ Iframe de clases listo")


# ─── Filtrar y encontrar primera clase pendiente ───────────────────────────────

async def get_wv0613_frame(page):
    """Obtiene el Frame real de wv0613 desde page.frames."""
    for f in page.frames:
        if "wv0613" in f.url:
            return f
    return None


async def encontrar_primera_clase_pendiente(page):
    log("🔍 Filtrando por 'Pendientes por programar'...")

    wv0613 = await get_wv0613_frame(page)
    if not wv0613:
        raise Exception("Frame wv0613 no encontrado")

    # Seleccionar filtro "Pendientes por programar" (value=2)
    await wv0613.select_option("#vTPEAPROBO", "2")
    await esperar(2000)

    # Buscar la primera fila visible
    log("   Buscando primera clase pendiente...")
    filas = wv0613.locator("tr[id^='Grid1ContainerRow_']")
    cnt = await filas.count()
    if cnt == 0:
        raise Exception("No hay clases pendientes por programar")

    primera_fila = filas.first
    texto = await primera_fila.text_content()
    log(f"   Clase: {texto[:80].strip()}")
    return primera_fila, wv0613


# ─── Hacer click en Asignar para abrir modal de día/hora ──────────────────────

async def abrir_modal_dia_hora(page):
    """Hace click en la primera fila pendiente y luego en el botón Asignar."""
    primera_fila, wv0613 = await encontrar_primera_clase_pendiente(page)

    log("   Click en fila de la clase...")
    await primera_fila.click()
    await esperar(500)

    log("   Click en Asignar...")
    await wv0613.locator("#BUTTON1[value='Asignar']").click()
    await esperar(2000)


# ─── Seleccionar día y hora en la modal de wv0614a ────────────────────────────

async def seleccionar_dia_y_hora(page, frame, label_hora):
    log(f"   Configurando {label_hora}...")

    # La modal de día/hora (wv0614a) puede abrirse como otro iframe o popup
    # Esperar que aparezca el select #vDIA
    # Primero buscar en un nuevo iframe dentro del frame actual
    dia_frame = frame  # por defecto, buscar en el mismo frame

    # Verificar si hay un iframe anidado para wv0614a
    # wv0614a puede abrirse en: iframe anidado dentro de wv0613, o frame en página principal
    dia_frame = None

    # Buscar en frames reales de la página (page.frames incluye todos los iframes)
    await esperar(2000)
    for f in page.frames:
        if "wv0614" in f.url:
            dia_frame = f
            log(f"   Modal día/hora en frame: {f.url}")
            break

    # Si no hay frame wv0614, buscar en el mismo iframe wv0613
    if not dia_frame:
        try:
            await frame.locator("#vDIA").wait_for(timeout=5000)
            # frame_locator no tiene eval — usar page.frames para encontrarlo
            for f in page.frames:
                if "wv0613" in f.url:
                    dia_frame = f
                    break
        except PlaywrightTimeout:
            pass

    # Último recurso: buscar en cualquier frame que tenga #vDIA
    if not dia_frame:
        for f in page.frames:
            try:
                el = await f.query_selector("#vDIA")
                if el:
                    dia_frame = f
                    log(f"   #vDIA encontrado en frame: {f.url}")
                    break
            except:
                continue

    if not dia_frame:
        raise Exception("No se encontró el selector #vDIA en ningún frame")

    await dia_frame.wait_for_selector("#vDIA", timeout=10000)
    await esperar(500)

    opciones = await dia_frame.eval_on_selector(
        "#vDIA",
        "sel => Array.from(sel.options).map(o => ({value: o.value, text: o.text}))"
    )
    log(f"   Días: {[o['text'] for o in opciones]}")

    if len(opciones) < 2:
        raise Exception("No hay día disponible para mañana")

    await dia_frame.select_option("#vDIA", opciones[-1]["value"])
    await esperar(1500)
    log(f"   Día: {opciones[-1]['text']}")

    # Click en la fila de la hora
    fila_hora = dia_frame.locator("tr").filter(has_text=label_hora).first
    if await fila_hora.count() > 0:
        await fila_hora.click()
    else:
        celda = dia_frame.locator(f"td:has-text('{label_hora}')").first
        if await celda.count() > 0:
            await celda.click()
        else:
            raise Exception(f"Hora {label_hora} no encontrada")

    await esperar(600)
    log(f"   Hora {label_hora} seleccionada — confirmando...")
    await dia_frame.click("#BUTTON1")
    await esperar(1500)
    log(f"   ✅ {label_hora} confirmada")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    log(f"🚀 {datetime.now(ZONA_COL).strftime('%A %d/%m/%Y %H:%M')} Colombia")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await (await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="es-CO",
        )).new_page()

        try:
            await hacer_login(page)
            await ir_a_programacion(page)
            await seleccionar_plan(page)

            errores = []
            for label_hora in HORAS:
                try:
                    log(f"\n━━━ Agendando {label_hora} ━━━")
                    await abrir_modal_dia_hora(page)
                    await seleccionar_dia_y_hora(page, None, label_hora)
                    log(f"🎉 {label_hora} agendada")
                    # Volver al iframe para la siguiente clase
                    await esperar(1000)
                    # Re-obtener el frame por si se recargó
                    pass  # frame se re-obtiene dinámicamente en cada llamada
                except Exception as e:
                    log(f"⚠️  Error {label_hora}: {e}")
                    errores.append(f"{label_hora}: {e}")
                    await screenshot(page, f"error_{label_hora.replace(':','')}.png")

            if errores:
                for err in errores:
                    log(f"   ❌ {err}")
                sys.exit(1)
            else:
                log("✅ Todas las clases agendadas")

        except Exception as e:
            log(f"❌ Fatal: {e}")
            await screenshot(page)
            raise
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
