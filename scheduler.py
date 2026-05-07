"""
Smart Idiomas - Agendador automático de clases
Ejecuta todos los días a las 8am (Colombia) via GitHub Actions
"""

import asyncio
import os
import sys
from datetime import datetime
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

async def screenshot(page, nombre="error_screenshot.png"):
    try:
        await page.screenshot(path=nombre)
        log(f"   📸 Screenshot: {nombre}")
    except:
        pass

# ─── Login ─────────────────────────────────────────────────────────────────────

async def hacer_login(page):
    log("🔐 Navegando a login...")
    await page.goto(LOGIN_URL, wait_until="networkidle")
    log(f"   URL: {page.url}")

    # Si ya hay sesión activa vamos directo al menú principal
    if "wv0480" in page.url or "wv0527" in page.url:
        log("✅ Sesión activa detectada")
        return

    # Verificar campos
    for selector in ["#vUSUCOD", "#vPASS", "#BUTTON1"]:
        el = await page.query_selector(selector)
        log(f"   {selector}: {'OK' if el else 'NO ENCONTRADO'}")

    log("   Llenando credenciales...")
    await page.click("#vUSUCOD")
    await page.fill("#vUSUCOD", "")
    await page.type("#vUSUCOD", USUARIO, delay=80)

    await page.click("#vPASS")
    await page.fill("#vPASS", "")
    await page.type("#vPASS", PASSWORD, delay=80)

    await esperar(page, 500)
    await page.keyboard.press("Tab")
    await esperar(page, 300)

    log("   Enviando login...")
    # GeneXus hace: 1) abre popup msje.aspx, 2) redirige a wv0480.aspx
    # No esperamos navegación completa porque abre una ventana emergente primero
    await page.click("#BUTTON1")
    await esperar(page, 3000)  # Dar tiempo para que se procese el AJAX

    log(f"   URL tras click: {page.url}")

    # ── Cerrar la modal informativa (msje.aspx) si aparece ──
    await cerrar_modal_informativa(page)

    # Ahora deberíamos estar en wv0480 (menú principal)
    url_final = page.url
    log(f"   URL final: {url_final}")

    if "wv0480" not in url_final and "wv0527" not in url_final:
        await screenshot(page)
        raise Exception(f"Login fallido — URL inesperada: {url_final}")

    log("✅ Login exitoso")


async def cerrar_modal_informativa(page):
    """
    Tras el login, GeneXus abre msje.aspx como popup/modal con un botón 'Regresar'.
    Esta función detecta y cierra esa modal.
    """
    log("   Verificando modal informativa...")

    # La modal puede abrirse en un popup (nueva página) o como overlay en la misma página
    # Primero revisar si hay una nueva página abierta (popup real)
    context = page.context
    await esperar(page, 1500)

    todas_las_paginas = context.pages
    log(f"   Páginas abiertas: {len(todas_las_paginas)}")

    for p in todas_las_paginas:
        if "msje" in p.url:
            log(f"   Modal detectada como popup: {p.url}")
            await p.wait_for_load_state("networkidle")
            btn = await p.query_selector("#BUTTON1")
            if btn:
                log("   Cerrando modal (click en Regresar)...")
                await p.click("#BUTTON1")
                await esperar(page, 1000)
            else:
                await p.close()
            log("   Modal cerrada")
            await page.wait_for_load_state("networkidle")
            return

    # Si no es popup, puede ser un iframe o un overlay en la misma página
    # Buscar el botón Regresar en la página principal o en iframes
    try:
        # Intentar en página principal
        btn_regresar = page.locator("#BUTTON1[value='Regresar'], input[value='Regresar']").first
        if await btn_regresar.count() > 0:
            log("   Modal detectada en página principal — cerrando...")
            await btn_regresar.click()
            await page.wait_for_load_state("networkidle")
            log("   Modal cerrada")
            return
    except:
        pass

    # Buscar el ícono X de cierre (exitIcon.svg)
    try:
        btn_x = page.locator("img[src*='exitIcon'], .gx-popup-close, [class*='close']").first
        if await btn_x.count() > 0:
            log("   Cerrando modal via ícono X...")
            await btn_x.click()
            await page.wait_for_load_state("networkidle")
            log("   Modal cerrada")
            return
    except:
        pass

    log("   No se detectó modal — continuando")
    # Navegar directamente a wv0480 como fallback
    await page.wait_for_load_state("networkidle")


# ─── Navegar al módulo de programación ────────────────────────────────────────

async def ir_a_programacion(page):
    """Desde wv0480 (menú), hacer click en 'Programación'."""
    log("📋 Navegando a Programación...")

    if "wv0527" in page.url:
        log("   Ya estamos en wv0527")
        return

    if "wv0480" in page.url:
        # Buscar el enlace/imagen de Programación en el menú
        try:
            prog = page.locator("img[src*='PROGRAMACION'], a:has-text('Programaci'), [title*='rogramaci']").first
            if await prog.count() > 0:
                log("   Click en Programación...")
                async with page.expect_navigation(timeout=15000, wait_until="networkidle"):
                    await prog.click()
                log(f"   URL: {page.url}")
                return
        except PlaywrightTimeout:
            log("   Timeout en navegación a Programación")

    # Fallback: ir directo a la URL de planes
    log("   Navegando directo a wv0527...")
    await page.goto(PLANES_URL, wait_until="networkidle")
    log(f"   URL: {page.url}")


# ─── Seleccionar plan ──────────────────────────────────────────────────────────

async def seleccionar_plan(page):
    log(f"   Buscando plan {PLAN_COD} en la tabla...")
    await page.wait_for_selector(".Grid", timeout=10000)

    fila = page.locator("tr").filter(has_text=PLAN_COD).first
    if await fila.count() == 0:
        raise Exception(f"No se encontró el plan {PLAN_COD}")

    await fila.click()
    await esperar(page, 400)
    log(f"   Plan {PLAN_COD} seleccionado — click en Iniciar...")
    await page.click("#W0030BUTTON1")
    await page.wait_for_load_state("networkidle")
    log("✅ Modal de clases abierta")


# ─── Buscar clase pendiente ────────────────────────────────────────────────────

async def encontrar_primera_clase_pendiente(page):
    log("🔍 Buscando primera clase pendiente...")
    await page.wait_for_selector("input[name='BUTTON1'][value='Asignar']", timeout=15000)

    pagina = 1
    while True:
        log(f"   Página {pagina}...")

        # Clases pendientes tienen fondo rojo (#FF6666)
        filas_pendientes = page.locator("tr").filter(
            has=page.locator("td[style*='FF6666'], td[style*='ff6666']")
        )
        if await filas_pendientes.count() == 0:
            filas_pendientes = page.locator("tr").filter(has_text="Pendiente")

        if await filas_pendientes.count() > 0:
            primera = filas_pendientes.first
            texto = await primera.text_content()
            log(f"   Clase encontrada: {texto[:60].strip()}")
            return primera

        btn_siguiente = page.locator("img[src*='PageNext']").first
        if await btn_siguiente.count() == 0:
            raise Exception("No hay clases pendientes")

        await btn_siguiente.click()
        await page.wait_for_load_state("networkidle")
        await esperar(page, 600)
        pagina += 1


# ─── Seleccionar día y hora ───────────────────────────────────────────────────

async def seleccionar_dia_y_hora(page, label_hora: str):
    log(f"   Configurando horario {label_hora}...")
    await page.wait_for_selector("#vDIA", timeout=10000)
    await esperar(page, 500)

    opciones = await page.eval_on_selector(
        "#vDIA",
        "sel => Array.from(sel.options).map(o => ({value: o.value, text: o.text}))"
    )
    log(f"   Días disponibles: {[o['text'] for o in opciones]}")

    if len(opciones) < 2:
        raise Exception("Solo hay un día disponible")

    # Seleccionar mañana (última opción disponible)
    valor_manana = opciones[-1]["value"]
    await page.select_option("#vDIA", valor_manana)
    await page.wait_for_load_state("networkidle")
    await esperar(page, 1000)
    log(f"   Día: {opciones[-1]['text']}")

    # Buscar la hora en la tabla por texto
    fila_hora = page.locator("tr").filter(has_text=label_hora).first
    if await fila_hora.count() > 0:
        await fila_hora.click()
    else:
        celda = page.locator(f"td:has-text('{label_hora}')").first
        if await celda.count() > 0:
            await celda.click()
        else:
            raise Exception(f"No se encontró la hora {label_hora}")

    await page.wait_for_load_state("networkidle")
    await esperar(page, 600)
    log(f"   Hora {label_hora} seleccionada — confirmando...")

    await page.click("#BUTTON1")
    await page.wait_for_load_state("networkidle")
    await esperar(page, 800)
    log(f"   ✅ Confirmado: {label_hora}")


# ─── Agendar una clase ────────────────────────────────────────────────────────

async def agendar_una_clase(page, hora_config: dict):
    log(f"\n━━━ Agendando {hora_config['label']} ━━━")
    fila_clase = await encontrar_primera_clase_pendiente(page)

    log("   Click en clase (Asignar)...")
    await fila_clase.click()
    await page.wait_for_load_state("networkidle")
    await esperar(page, 800)

    await seleccionar_dia_y_hora(page, hora_config["label"])
    log(f"🎉 Clase {hora_config['label']} agendada")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    hora_col = datetime.now(ZONA_COL)
    log(f"🚀 Iniciando — {hora_col.strftime('%A %d/%m/%Y %H:%M')} Colombia")

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
            await ir_a_programacion(page)
            await seleccionar_plan(page)

            errores = []
            for hora in HORAS:
                try:
                    await agendar_una_clase(page, hora)
                    await page.go_back()
                    await page.wait_for_load_state("networkidle")
                    await esperar(page, 500)
                except Exception as e:
                    log(f"⚠️  Error en {hora['label']}: {e}")
                    errores.append(f"{hora['label']}: {e}")
                    try:
                        await page.goto(PLANES_URL, wait_until="networkidle")
                        await seleccionar_plan(page)
                    except:
                        pass

            if errores:
                log("⚠️  Proceso con errores:")
                for err in errores:
                    log(f"   - {err}")
                sys.exit(1)
            else:
                log("✅ Todas las clases agendadas")

        except Exception as e:
            log(f"❌ Error fatal: {e}")
            await screenshot(page)
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
