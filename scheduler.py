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

HORAS = [
    {"label": "18:00"},
    {"label": "19:30"},
]

ZONA_COL = pytz.timezone("America/Bogota")

def log(msg: str):
    hora = datetime.now(ZONA_COL).strftime("%H:%M:%S")
    print(f"[{hora}] {msg}", flush=True)

async def esperar(page, ms=800):
    await page.wait_for_timeout(ms)

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
    await esperar(page, 500)
    await page.keyboard.press("Tab")
    await esperar(page, 300)
    await page.click("#BUTTON1")
    await esperar(page, 3000)

    # Cerrar modal informativa si aparece
    await esperar(page, 2000)  # Dar tiempo a que aparezca la modal

    modal_cerrada = False
    for p in page.context.pages:
        if "msje" in p.url:
            log("   Modal como popup — cerrando...")
            try:
                await p.click("#BUTTON1")
            except:
                await p.close()
            await esperar(page, 2000)
            modal_cerrada = True
            break

    if not modal_cerrada:
        try:
            btn = page.locator("input[value='Regresar']").first
            if await btn.count() > 0:
                log("   Modal en página — cerrando con Regresar...")
                await btn.click()
                await esperar(page, 2000)
                modal_cerrada = True
        except:
            pass

    if not modal_cerrada:
        try:
            btn_x = page.locator("img[src*='exitIcon'], .gx-popup-close").first
            if await btn_x.count() > 0:
                log("   Cerrando modal con X...")
                await btn_x.click()
                await esperar(page, 2000)
        except:
            pass

    # Esperar URL destino sin networkidle (la plataforma tiene polling constante)
    for _ in range(20):
        url = page.url
        if "wv0480" in url or "wv0527" in url:
            break
        await esperar(page, 500)

    log(f"   URL final: {page.url}")

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


# ─── Seleccionar plan ──────────────────────────────────────────────────────────

async def seleccionar_plan(page):
    log(f"   Esperando que GeneXus renderice la grilla de planes...")

    # GeneXus renderiza las filas via JS desde W0030Grid1ContainerDataV
    # Esperar a que aparezca una celda con el código del plan
    try:
        await page.wait_for_selector(
            f"td:has-text('{PLAN_COD}')",
            timeout=15000
        )
    except PlaywrightTimeout:
        await screenshot(page, "error_grilla_planes.png")
        raise Exception(f"Grilla de planes no renderizó — plan {PLAN_COD} no visible")

    # Hacer click en la celda del plan
    celda_plan = page.locator(f"td:has-text('{PLAN_COD}')").first
    log(f"   Click en celda del plan {PLAN_COD}...")
    await celda_plan.click()
    await esperar(page, 800)

    # Click en Iniciar y esperar que la grilla de clases aparezca
    log("   Click en Iniciar...")
    await page.click("#W0030BUTTON1")

    log("   Esperando grilla de clases (AJAX)...")
    try:
        # Esperar que aparezca el botón Asignar — indica que wv0613 cargó
        await page.wait_for_selector(
            "#BUTTON1[value='Asignar']",
            timeout=20000
        )
        log("✅ Grilla de clases lista")
    except PlaywrightTimeout:
        await screenshot(page, "error_tras_iniciar.png")
        # Log qué botones hay para diagnóstico
        import re
        html = await page.content()
        botones = re.findall(r'<input[^>]*type=["\']button["\'][^>]*value=["\']([^"\']+)["\']', html)
        log(f"   Botones visibles: {botones}")
        raise Exception("Timeout — grilla de clases no cargó tras Iniciar")


# ─── Buscar clase pendiente ────────────────────────────────────────────────────

async def encontrar_primera_clase_pendiente(page):
    log("🔍 Buscando clase pendiente...")
    pagina = 1
    while True:
        log(f"   Página {pagina}...")
        await esperar(page, 500)

        # Filas con fondo rojo = pendientes
        filas = page.locator("tr").filter(
            has=page.locator("td[style*='FF6666'], td[style*='ff6666'], td[bgcolor='#FF6666']")
        )
        if await filas.count() == 0:
            filas = page.locator("tr").filter(has_text="Pendiente")
        if await filas.count() == 0:
            # Intentar con cualquier fila de datos de la grilla
            filas = page.locator("table tr").filter(has=page.locator("td")).nth(1)

        cnt = await filas.count() if hasattr(filas, 'count') else 1
        if cnt > 0:
            primera = filas.first if hasattr(filas, 'first') else filas
            texto = await primera.text_content()
            log(f"   Clase: {texto[:80].strip()}")
            return primera

        btn_sig = page.locator("img[src*='PageNext'], [title='Siguiente página']").first
        if await btn_sig.count() == 0:
            raise Exception("No hay clases pendientes")
        await btn_sig.click()
        await page.wait_for_load_state("domcontentloaded")
        pagina += 1


# ─── Seleccionar día y hora ───────────────────────────────────────────────────

async def seleccionar_dia_y_hora(page, label_hora: str):
    log(f"   Horario {label_hora}...")
    await page.wait_for_selector("#vDIA", timeout=15000)
    await esperar(page, 500)

    opciones = await page.eval_on_selector(
        "#vDIA",
        "sel => Array.from(sel.options).map(o => ({value: o.value, text: o.text}))"
    )
    log(f"   Días: {[o['text'] for o in opciones]}")

    if len(opciones) < 2:
        raise Exception("No hay día disponible para mañana")

    await page.select_option("#vDIA", opciones[-1]["value"])
    await page.wait_for_load_state("domcontentloaded")
    await esperar(page, 1000)
    log(f"   Día seleccionado: {opciones[-1]['text']}")

    # Click en la fila de la hora
    fila = page.locator("tr").filter(has_text=label_hora).first
    if await fila.count() > 0:
        await fila.click()
    else:
        celda = page.locator(f"td:has-text('{label_hora}')").first
        if await celda.count() > 0:
            await celda.click()
        else:
            raise Exception(f"Hora {label_hora} no encontrada en la tabla")

    await page.wait_for_load_state("domcontentloaded")
    await esperar(page, 600)

    await page.click("#BUTTON1")
    await page.wait_for_load_state("domcontentloaded")
    await esperar(page, 800)
    log(f"   ✅ {label_hora} confirmada")


# ─── Agendar una clase ────────────────────────────────────────────────────────

async def agendar_una_clase(page, hora_config: dict):
    log(f"\n━━━ Agendando {hora_config['label']} ━━━")
    fila = await encontrar_primera_clase_pendiente(page)
    await fila.click()
    await page.wait_for_load_state("domcontentloaded")
    await esperar(page, 1000)
    log(f"   URL tras click clase: {page.url}")
    await seleccionar_dia_y_hora(page, hora_config["label"])
    log(f"🎉 {hora_config['label']} agendada")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    log(f"🚀 {datetime.now(ZONA_COL).strftime('%A %d/%m/%Y %H:%M')} Colombia")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await (await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="es-CO",
        )).new_page()

        try:
            await hacer_login(page)
            await ir_a_programacion(page)
            await seleccionar_plan(page)

            errores = []
            for hora in HORAS:
                try:
                    await agendar_una_clase(page, hora)
                    await page.go_back()
                    await page.wait_for_load_state("domcontentloaded")
                    await esperar(page, 800)
                except Exception as e:
                    log(f"⚠️  Error {hora['label']}: {e}")
                    errores.append(f"{hora['label']}: {e}")
                    await screenshot(page, f"error_{hora['label'].replace(':','')}.png")
                    try:
                        await page.goto(PLANES_URL, wait_until="load")
                        await seleccionar_plan(page)
                    except:
                        pass

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
