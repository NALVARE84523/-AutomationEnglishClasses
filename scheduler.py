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

# Credenciales — vienen de variables de entorno (nunca hardcodeadas)
USUARIO    = os.environ["SMART_USUARIO"]   # tu número de cédula
PASSWORD   = os.environ["SMART_PASSWORD"]

# Plan que quieres agendar (código del plan)
PLAN_COD   = os.environ.get("SMART_PLAN", "INGA1B2")

# Horas a agendar: filas en la tabla de wv0614a
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

# ─── Pasos del flujo ───────────────────────────────────────────────────────────

async def hacer_login(page):
    log("🔐 Navegando a login...")
    await page.goto(LOGIN_URL, wait_until="networkidle")
    log(f"   URL actual: {page.url}")

    # Verificar si ya hay sesión activa (redirect a wv0527)
    if "wv0527" in page.url:
        log("✅ Ya había sesión activa")
        return

    # Verificar que los campos existen
    campo_usuario = await page.query_selector("#vUSUCOD")
    campo_pass    = await page.query_selector("#vPASS")
    btn_confirmar = await page.query_selector("#BUTTON1")

    log(f"   Campo vUSUCOD encontrado: {campo_usuario is not None}")
    log(f"   Campo vPASS encontrado:   {campo_pass is not None}")
    log(f"   Botón BUTTON1 encontrado: {btn_confirmar is not None}")

    if not campo_usuario or not campo_pass:
        await page.screenshot(path="error_screenshot.png")
        raise Exception("❌ No se encontraron los campos de login en la página")

    log("   Llenando credenciales...")
    # Limpiar primero y luego llenar (más robusto con GeneXus)
    await page.click("#vUSUCOD")
    await page.fill("#vUSUCOD", "")
    await page.type("#vUSUCOD", USUARIO, delay=50)

    await page.click("#vPASS")
    await page.fill("#vPASS", "")
    await page.type("#vPASS", PASSWORD, delay=50)

    await esperar(page, 500)

    # GeneXus a veces requiere Tab antes del submit para disparar el onchange
    await page.keyboard.press("Tab")
    await esperar(page, 300)

    log("   Haciendo click en Confirmar...")
    await page.click("#BUTTON1")

    # Esperar navegación — GeneXus puede ser lento
    try:
        await page.wait_for_url("**/wv0527**", timeout=15000)
        log("✅ Login exitoso — redirigido a wv0527")
        return
    except PlaywrightTimeout:
        pass

    # Si no hubo redirect, ver qué pasó
    url_actual = page.url
    log(f"   URL tras login: {url_actual}")

    # Buscar mensaje de error en la página
    contenido = await page.content()
    errores_posibles = ["incorrecta", "inválid", "no existe", "error", "incorrecto"]
    for err in errores_posibles:
        if err.lower() in contenido.lower():
            log(f"   Mensaje de error detectado en página (contiene: '{err}')")
            break

    await page.screenshot(path="error_screenshot.png")

    if "wv0527" not in url_actual:
        raise Exception(
            f"❌ Login fallido — URL actual: {url_actual}. "
            "Verifica usuario/contraseña en los Repository secrets."
        )


async def seleccionar_plan(page):
    log(f"📋 Buscando plan {PLAN_COD}...")

    # Navegar a la pantalla de planes si no estamos ahí
    if "wv0527" not in page.url:
        await page.goto(PLANES_URL, wait_until="networkidle")

    # Esperar a que cargue la grilla de planes
    await page.wait_for_selector(".Grid", timeout=10000)

    # Buscar la fila del plan por código
    # La grilla tiene celdas con el código del plan
    fila = page.locator("tr").filter(has_text=PLAN_COD).first
    count = await fila.count()
    if count == 0:
        raise Exception(f"❌ No se encontró el plan {PLAN_COD} en la tabla")

    await fila.click()
    log(f"   Plan {PLAN_COD} seleccionado")
    await esperar(page, 500)

    # Click en botón Iniciar
    await page.click("#W0030BUTTON1")
    await page.wait_for_load_state("networkidle")
    log("✅ Plan iniciado — modal de clases abierta")


async def encontrar_primera_clase_pendiente(page):
    """
    Recorre la tabla paginada de wv0613 buscando la primera clase
    con estado=2 (Pendiente por programar).
    Devuelve el selector de la fila.
    """
    log("🔍 Buscando primera clase pendiente...")

    # wv0613 puede estar como modal o frame — esperar que cargue
    # El modal tiene su propio form con la grilla
    await page.wait_for_selector("input[name='BUTTON1'][value='Asignar']", timeout=15000)

    pagina = 1
    while True:
        log(f"   Revisando página {pagina} de clases...")

        # Las filas pendientes tienen fondo rojo (#FF6666) o estado texto "2"
        # En el HTML: TPEAPROBO_XXXX con valor "2"
        # La forma más robusta: buscar celdas con color rojo de fondo
        filas_pendientes = page.locator("tr").filter(
            has=page.locator("td[style*='FF6666'], td[style*='ff6666']")
        )

        # Alternativa: buscar por texto del estado
        if await filas_pendientes.count() == 0:
            filas_pendientes = page.locator("tr").filter(has_text="Pendiente")

        if await filas_pendientes.count() > 0:
            primera = filas_pendientes.first
            texto = await primera.text_content()
            log(f"   ✅ Clase pendiente encontrada: {texto[:60].strip()}")
            return primera

        # No hay pendientes en esta página — ir a la siguiente
        btn_siguiente = page.locator("img[src*='PageNext']").first
        if await btn_siguiente.count() == 0:
            raise Exception("❌ No se encontraron clases pendientes en ninguna página")

        await btn_siguiente.click()
        await page.wait_for_load_state("networkidle")
        await esperar(page, 600)
        pagina += 1


async def click_asignar_clase(page, fila):
    """Hace click en la fila de la clase para disparar el evento E'ASIGNAR'."""
    log("   Haciendo click en la clase para asignar...")
    await fila.click()
    await page.wait_for_load_state("networkidle")
    await esperar(page, 800)


async def seleccionar_dia_y_hora(page, fila_hora: str, label_hora: str):
    """
    En wv0614a:
    1. Selecciona el día de mañana en el select vDIA
    2. Hace click en la fila de la tabla correspondiente a la hora deseada
    3. Click en Confirmar
    """
    log(f"   Configurando horario {label_hora}...")

    # Esperar que cargue la pantalla de selección
    await page.wait_for_selector("#vDIA", timeout=10000)
    await esperar(page, 500)

    # ── Seleccionar día de mañana ──
    # El select tiene las opciones disponibles; seleccionar la segunda (mañana)
    opciones = await page.eval_on_selector(
        "#vDIA",
        "sel => Array.from(sel.options).map(o => ({value: o.value, text: o.text}))"
    )
    log(f"   Días disponibles: {opciones}")

    if len(opciones) < 2:
        raise Exception("⚠️  Solo hay un día disponible — puede que sea muy tarde para agendar mañana")

    # Seleccionar el último día disponible (mañana)
    valor_manana = opciones[-1]["value"]
    await page.select_option("#vDIA", valor_manana)
    await page.wait_for_load_state("networkidle")
    await esperar(page, 1000)

    log(f"   Día seleccionado: {opciones[-1]['text']}")

    # ── Click en la fila de la hora deseada ──
    # Las filas de la tabla tienen IDs de evento ERFR.XXXX
    # donde XXXX es el número de fila (0009 = 18:00, 0010 = 19:30)
    # La tabla se renderiza dinámicamente; buscar por contenido de hora

    # Primero intentar por texto de hora exacta
    fila_locator = page.locator("tr").filter(has_text=label_hora).first

    if await fila_locator.count() == 0:
        # Fallback: buscar la fila por índice ERFR
        fila_locator = page.locator(f"tr[data-row='{fila_hora}'], tr:nth-child({int(fila_hora)})")

    if await fila_locator.count() == 0:
        # Último recurso: hacer click directo en la celda con el texto de la hora
        celdas = page.locator(f"td:has-text('{label_hora}')")
        if await celdas.count() > 0:
            await celdas.first.click()
        else:
            raise Exception(f"❌ No se encontró la hora {label_hora} en la tabla")
    else:
        await fila_locator.click()

    await page.wait_for_load_state("networkidle")
    await esperar(page, 600)
    log(f"   Hora {label_hora} seleccionada")

    # ── Click en Confirmar ──
    await page.click("#BUTTON1")
    await page.wait_for_load_state("networkidle")
    await esperar(page, 800)
    log(f"   ✅ Confirmado: {label_hora}")


async def agendar_una_clase(page, hora_config: dict):
    """Agenda una clase para la hora especificada."""
    log(f"\n━━━ Agendando clase {hora_config['label']} ━━━")

    # Buscar la primera clase pendiente
    fila_clase = await encontrar_primera_clase_pendiente(page)

    # Hacer click en la clase (dispara E'ASIGNAR'.)
    await click_asignar_clase(page, fila_clase)

    # Seleccionar día y hora en wv0614a
    await seleccionar_dia_y_hora(page, hora_config["fila"], hora_config["label"])

    log(f"🎉 ¡Clase {hora_config['label']} agendada exitosamente!")


# ─── Main ──────────────────────────────────────────────────────────────────────

async def main():
    hora_col = datetime.now(ZONA_COL)
    log(f"🚀 Iniciando agendador — {hora_col.strftime('%A %d/%m/%Y %H:%M')} (Colombia)")

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
            # Paso 1: Login
            await hacer_login(page)

            # Paso 2: Seleccionar plan
            await seleccionar_plan(page)

            # Paso 3+4+5: Agendar cada hora
            errores = []
            for hora in HORAS:
                try:
                    await agendar_una_clase(page, hora)
                    # Volver al plan para la siguiente clase
                    await page.go_back()
                    await page.wait_for_load_state("networkidle")
                    await esperar(page, 500)
                except Exception as e:
                    log(f"⚠️  Error en {hora['label']}: {e}")
                    errores.append(f"{hora['label']}: {e}")
                    # Intentar volver a un estado limpio
                    try:
                        await page.goto(PLANES_URL, wait_until="networkidle")
                        await seleccionar_plan(page)
                    except:
                        pass

            if errores:
                log(f"\n⚠️  Proceso completado con errores:")
                for err in errores:
                    log(f"   - {err}")
                sys.exit(1)
            else:
                log("\n✅ Todas las clases agendadas correctamente")

        except Exception as e:
            log(f"❌ Error fatal: {e}")
            # Guardar screenshot para debug
            try:
                await page.screenshot(path="error_screenshot.png")
                log("   📸 Screenshot guardado: error_screenshot.png")
            except:
                pass
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
