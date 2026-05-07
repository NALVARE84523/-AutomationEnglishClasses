"""
Smart Idiomas - Agendador automático de clases
Ejecuta todos los días a las 8am (Colombia) via GitHub Actions
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
import pytz

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ─── Configuración ─────────────────────────────────────────────────────────────
BASE_URL   = "https://schoolpack.smart.edu.co/idiomas"
LOGIN_URL  = f"{BASE_URL}/alumnos.aspx"
PLANES_URL = f"{BASE_URL}/wv0527.aspx?2UxxJsznnhFnikyCHt5r8u3UnECcT9qxNq7OemMxcG7Kag2xFv8lv6S4FQbMbYAEsD77lQVW8NPwj7DUz1OG8Q=="

USUARIO  = os.environ["SMART_USUARIO"]
PASSWORD = os.environ["SMART_PASSWORD"]
PLAN_COD = os.environ.get("SMART_PLAN", "INGA1B2")

# Fila 0009 = 18:00-19:30  |  Fila 0010 = 19:30-21:00
HORAS = [
    {"fila": "0009", "label": "18:00"},
    {"fila": "0010", "label": "19:30"},
]

ZONA_COL = pytz.timezone("America/Bogota")

# ─── Helpers ───────────────────────────────────────────────────────────────────
def log(msg: str):
    hora = datetime.now(ZONA_COL).strftime("%H:%M:%S")
    print(f"[{hora}] {msg}", flush=True)

async def esperar(page, ms=800):
    await page.wait_for_timeout(ms)

# ─── Login ─────────────────────────────────────────────────────────────────────

async def hacer_login(page):
    log("🔐 Navegando a login...")
    await page.goto(LOGIN_URL, wait_until="networkidle")
    log(f"   URL actual: {page.url}")

    if "wv0527" in page.url:
        log("✅ Ya había sesión activa")
        return

    campo_usuario = await page.query_selector("#vUSUCOD")
    campo_pass    = await page.query_selector("#vPASS")
    btn_confirmar = await page.query_selector("#BUTTON1")

    log(f"   Campo vUSUCOD encontrado: {campo_usuario is not None}")
    log(f"   Campo vPASS encontrado:   {campo_pass is not None}")
    log(f"   Botón BUTTON1 encontrado: {btn_confirmar is not None}")

    if not campo_usuario or not campo_pass:
        await page.screenshot(path="error_screenshot.png")
        raise Exception("No se encontraron los campos de login")

    log("   Llenando credenciales...")
    await page.click("#vUSUCOD")
    await page.fill("#vUSUCOD", "")
    await page.type("#vUSUCOD", USUARIO, delay=80)

    await page.click("#vPASS")
    await page.fill("#vPASS", "")
    await page.type("#vPASS", PASSWORD, delay=80)

    await esperar(page, 600)

    # Tab dispara el onblur/onchange de GeneXus antes del submit
    await page.keyboard.press("Tab")
    await esperar(page, 400)

    log("   Haciendo click en Confirmar (esperando navegación)...")
    try:
        # expect_navigation captura el redirect AJAX de GeneXus
        async with page.expect_navigation(timeout=20000, wait_until="networkidle"):
            await page.click("#BUTTON1")
    except PlaywrightTimeout:
        log("   Timeout en navegación — revisando URL...")

    url_actual = page.url
    log(f"   URL tras login: {url_actual}")

    if "wv0527" not in url_actual:
        contenido = await page.content()
        msg_extra = ""
        for err in ["incorrecta", "invalida", "no existe", "incorrecto", "vEXISTE"]:
            if err.lower() in contenido.lower():
                msg_extra = f" — página contiene '{err}'"
                break
        await page.screenshot(path="error_screenshot.png")
        raise Exception(f"Login fallido — URL: {url_actual}{msg_extra}")

    log("✅ Login exitoso")


# ─── Seleccionar plan ──────────────────────────────────────────────────────────

async def seleccionar_plan(page):
    log(f"📋 Buscando plan {PLAN_COD}...")

    if "wv0527" not in page.url:
        await page.goto(PLANES_URL, wait_until="networkidle")

    await page.wait_for_selector(".Grid", timeout=10000)

    fila = page.locator("tr").filter(has_text=PLAN_COD).first
    if await fila.count() == 0:
        raise Exception(f"No se encontró el plan {PLAN_COD}")

    await fila.click()
    log(f"   Plan {PLAN_COD} seleccionado")
    await esperar(page, 500)

    await page.click("#W0030BUTTON1")
    await page.wait_for_load_state("networkidle")
    log("✅ Modal de clases abierta")


# ─── Buscar clase pendiente ────────────────────────────────────────────────────

async def encontrar_primera_clase_pendiente(page):
    log("🔍 Buscando primera clase pendiente...")
    await page.wait_for_selector("input[name='BUTTON1'][value='Asignar']", timeout=15000)

    pagina = 1
    while True:
        log(f"   Revisando página {pagina} de clases...")

        filas_pendientes = page.locator("tr").filter(
            has=page.locator("td[style*='FF6666'], td[style*='ff6666']")
        )
        if await filas_pendientes.count() == 0:
            filas_pendientes = page.locator("tr").filter(has_text="Pendiente")

        if await filas_pendientes.count() > 0:
            primera = filas_pendientes.first
            texto = await primera.text_content()
            log(f"   Clase pendiente: {texto[:60].strip()}")
            return primera

        btn_siguiente = page.locator("img[src*='PageNext']").first
        if await btn_siguiente.count() == 0:
            raise Exception("No hay clases pendientes")

        await btn_siguiente.click()
        await page.wait_for_load_state("networkidle")
        await esperar(page, 600)
        pagina += 1


# ─── Seleccionar día y hora ───────────────────────────────────────────────────

async def seleccionar_dia_y_hora(page, fila_hora: str, label_hora: str):
    log(f"   Configurando horario {label_hora}...")
    await page.wait_for_selector("#vDIA", timeout=10000)
    await esperar(page, 500)

    opciones = await page.eval_on_selector(
        "#vDIA",
        "sel => Array.from(sel.options).map(o => ({value: o.value, text: o.text}))"
    )
    log(f"   Días disponibles: {opciones}")

    if len(opciones) < 2:
        raise Exception("Solo hay un día disponible — muy tarde para agendar")

    valor_manana = opciones[-1]["value"]
    await page.select_option("#vDIA", valor_manana)
    await page.wait_for_load_state("networkidle")
    await esperar(page, 1000)
    log(f"   Día seleccionado: {opciones[-1]['text']}")

    # Buscar la fila de la hora en la tabla
    fila_locator = page.locator("tr").filter(has_text=label_hora).first
    if await fila_locator.count() == 0:
        celdas = page.locator(f"td:has-text('{label_hora}')")
        if await celdas.count() > 0:
            await celdas.first.click()
        else:
            raise Exception(f"No se encontró la hora {label_hora} en la tabla")
    else:
        await fila_locator.click()

    await page.wait_for_load_state("networkidle")
    await esperar(page, 600)
    log(f"   Hora {label_hora} seleccionada")

    await page.click("#BUTTON1")
    await page.wait_for_load_state("networkidle")
    await esperar(page, 800)
    log(f"   Confirmado: {label_hora}")


# ─── Agendar una clase ────────────────────────────────────────────────────────

async def agendar_una_clase(page, hora_config: dict):
    log(f"\n━━━ Agendando clase {hora_config['label']} ━━━")

    fila_clase = await encontrar_primera_clase_pendiente(page)
    await fila_clase.click()
    await page.wait_for_load_state("networkidle")
    await esperar(page, 800)

    await seleccionar_dia_y_hora(page, hora_config["fila"], hora_config["label"])
    log(f"Clase {hora_config['label']} agendada")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    hora_col = datetime.now(ZONA_COL)
    log(f"Iniciando agendador — {hora_col.strftime('%A %d/%m/%Y %H:%M')} (Colombia)")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="es-CO",
        )
        page = await context.new_page()

        try:
            await hacer_login(page)
            await seleccionar_plan(page)

            errores = []
            for hora in HORAS:
                try:
                    await agendar_una_clase(page, hora)
                    await page.go_back()
                    await page.wait_for_load_state("networkidle")
                    await esperar(page, 500)
                except Exception as e:
                    log(f"Error en {hora['label']}: {e}")
                    errores.append(f"{hora['label']}: {e}")
                    try:
                        await page.goto(PLANES_URL, wait_until="networkidle")
                        await seleccionar_plan(page)
                    except:
                        pass

            if errores:
                log("Proceso con errores:")
                for err in errores:
                    log(f"  - {err}")
                sys.exit(1)
            else:
                log("Todas las clases agendadas correctamente")

        except Exception as e:
            log(f"Error fatal: {e}")
            try:
                await page.screenshot(path="error_screenshot.png")
                log("Screenshot guardado")
            except:
                pass
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
