"""
Smart Idiomas - Agendador automático de clases
Horario:
  Lunes, Miércoles, Viernes -> 1 clase a las 18:00 en San Martin
  Martes, Jueves            -> 2 clases: 18:00 y 19:30 en Santafe
  Sábado                    -> no ejecutar
  Domingo                   -> agenda clase del Lunes siguiente
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
import pytz

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

BASE_URL   = "https://schoolpack.smart.edu.co/idiomas"
LOGIN_URL  = f"{BASE_URL}/alumnos.aspx"
PLANES_URL = f"{BASE_URL}/wv0527.aspx?2UxxJsznnhFnikyCHt5r8u3UnECcT9qxNq7OemMxcG7Kag2xFv8lv6S4FQbMbYAEsD77lQVW8NPwj7DUz1OG8Q=="

USUARIO  = os.environ["SMART_USUARIO"]
PASSWORD = os.environ["SMART_PASSWORD"]
PLAN_COD = os.environ.get("SMART_PLAN", "INGA1B2")

ZONA_COL = pytz.timezone("America/Bogota")

# ─── Lógica de horario ────────────────────────────────────────────────────────

def calcular_clases_a_agendar():
    """
    Determina qué clases agendar basado en el día actual (Colombia).
    Retorna (horas_a_agendar, fecha_objetivo) o ([], None) si no hay nada que hacer.
    
    El programa corre a las 6:10am y agenda para el día siguiente,
    excepto el domingo que agenda para el lunes.
    """
    ahora = datetime.now(ZONA_COL)
    dia_semana = ahora.weekday()  # 0=Lun, 1=Mar, 2=Mie, 3=Jue, 4=Vie, 5=Sab, 6=Dom

    nombres = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    log(f"   Hoy es {nombres[dia_semana]}")

    # Sábado: no ejecutar
    if dia_semana == 5:
        log("   Es sábado — no se agenda nada.")
        return [], None

    # Calcular el día objetivo (mañana, salvo domingo que apunta al lunes)
    if dia_semana == 6:  # Domingo -> Lunes
        dias_adelante = 1
    else:
        dias_adelante = 1

    fecha_objetivo = ahora + timedelta(days=dias_adelante)
    dia_objetivo = fecha_objetivo.weekday()

    log(f"   Agendando para: {nombres[dia_objetivo]} {fecha_objetivo.strftime('%d/%m/%Y')}")

    # Definir clases según el día objetivo
    if dia_objetivo in [0, 2, 4]:  # Lun, Mie, Vie
        horas = [{"label": "18:00", "sede": "SAN MARTIN"}]
    elif dia_objetivo in [1, 3]:   # Mar, Jue
        horas = [
            {"label": "18:00",  "sede": "SANTAFE"},
            {"label": "19:30",  "sede": "SANTAFE"},
        ]
    else:  # Sábado o Domingo objetivo (no debería ocurrir)
        log("   El día objetivo es fin de semana — no se agenda.")
        return [], None

    # Verificar que estamos dentro del horario permitido (6am - 10pm Colombia)
    hora_actual = ahora.hour + ahora.minute / 60
    if hora_actual < 6.0 or hora_actual >= 22.0:
        log(f"   ⚠️  Fuera del horario permitido ({ahora.strftime('%H:%M')}). Sistema disponible 6:00am–10:00pm.")
        return [], None

    return horas, fecha_objetivo


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
                    log(f"   Modal — cerrando con {selector}...")
                    await btn.click()
                    await esperar(2000)
                    break
            except:
                continue

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

    log("   Esperando iframe wv0613...")
    try:
        await page.wait_for_selector("iframe[src*='wv0613']", timeout=20000)
    except PlaywrightTimeout:
        await screenshot(page, "error_sin_iframe.png")
        raise Exception("Iframe wv0613 no apareció")

    frame = page.frame_locator("iframe[src*='wv0613']")
    log("   Esperando contenido del iframe...")
    await frame.locator("#BUTTON1[value='Asignar']").wait_for(timeout=15000)
    log("✅ Iframe de clases listo")


# ─── Verificar si ya hay clase programada para mañana ────────────────────────

async def clases_ya_programadas(page, fecha_objetivo, horas):
    """
    Revisa si ya hay clases en estado 'Programada' para la fecha objetivo.
    Retorna True si TODAS las clases ya están programadas (nada que hacer).
    """
    log(f"🔎 Verificando clases ya programadas para {fecha_objetivo.strftime('%d/%m/%Y')}...")

    wv0613 = await get_wv0613_frame(page)
    if not wv0613:
        return False

    # Filtrar por "Programadas" (value=3)
    await wv0613.select_option("#vTPEAPROBO", "3")
    await esperar(2000)

    fecha_str = fecha_objetivo.strftime("%-d/%-m/%y")   # ej: "8/5/26"
    fecha_str2 = fecha_objetivo.strftime("%d/%m/%y")    # ej: "08/05/26"

    html = await wv0613.content()
    horas_encontradas = []
    for h in horas:
        hora_label = h["label"]
        if hora_label in html and (fecha_str in html or fecha_str2 in html):
            horas_encontradas.append(hora_label)
            log(f"   ✅ Clase {hora_label} ya programada para mañana")

    # Volver al filtro "Todos los estados"
    await wv0613.select_option("#vTPEAPROBO", "0")
    await esperar(1000)

    if len(horas_encontradas) == len(horas):
        log("   Todas las clases ya están programadas — nada que hacer.")
        return True

    log(f"   Clases pendientes de agendar: {[h['label'] for h in horas if h['label'] not in horas_encontradas]}")
    return False


# ─── Frame helpers ────────────────────────────────────────────────────────────

async def get_wv0613_frame(page):
    for f in page.frames:
        if "wv0613" in f.url:
            return f
    return None


async def cerrar_modal_614(page):
    """Cierra el popup wv0614a si está abierto."""
    for f in page.frames:
        if "wv0614" in f.url:
            log("   Cerrando modal wv0614a...")
            try:
                btn = await f.query_selector("input[value='Regresar'], input[value='Cancelar'], #BUTTON2")
                if btn:
                    await btn.click()
                    await esperar(1000)
                    return
            except:
                pass
            try:
                x_btn = page.locator(".gx-popup-close, [id*='gxp'][id$='_x']").first
                if await x_btn.count() > 0:
                    await x_btn.click()
                    await esperar(1000)
                    return
            except:
                pass
            try:
                await page.evaluate("() => { document.querySelectorAll('.gx-popup').forEach(p => p.style.display='none'); }")
                await esperar(500)
            except:
                pass
            return


# ─── Buscar y agendar clase ───────────────────────────────────────────────────

async def encontrar_primera_clase_pendiente(page):
    log("🔍 Filtrando por 'Pendientes por programar'...")
    wv0613 = await get_wv0613_frame(page)
    if not wv0613:
        raise Exception("Frame wv0613 no encontrado")

    await wv0613.select_option("#vTPEAPROBO", "2")
    await esperar(2000)

    filas = wv0613.locator("tr[id^='Grid1ContainerRow_']")
    if await filas.count() == 0:
        raise Exception("No hay clases pendientes por programar")

    primera = filas.first
    texto = await primera.text_content()
    log(f"   Clase: {texto[:80].strip()}")
    return primera, wv0613


async def seleccionar_dia_y_hora(page, label_hora, fecha_objetivo):
    log(f"   Configurando {label_hora}...")

    # Esperar a que aparezca el iframe wv0614a (puede tardar)
    dia_frame = None
    for intento in range(15):  # hasta 15 segundos
        frames_actuales = page.frames
        log(f"   [{intento+1}] Frames activos: {[f.url[:60] for f in frames_actuales]}")
        for f in frames_actuales:
            if "wv0614" in f.url:
                dia_frame = f
                log(f"   Frame wv0614a encontrado en intento {intento+1}")
                break
        if dia_frame:
            break
        await esperar(1000)

    if not dia_frame:
        # Buscar en cualquier frame que tenga #vDIA
        for f in page.frames:
            try:
                el = await f.query_selector("#vDIA")
                if el:
                    dia_frame = f
                    log(f"   #vDIA encontrado en frame: {f.url[:60]}")
                    break
            except:
                continue

    # Verificar si apareció la modal de error wv0232 (fuera de horario)
    for f in page.frames:
        if "wv0232" in f.url:
            try:
                msg = await f.query_selector("#vMENSAJE, span#span_vMENSAJE")
                if msg:
                    texto_error = await msg.text_content()
                    # Cerrar la modal
                    btn_aceptar = await f.query_selector("#BUTTON1")
                    if btn_aceptar:
                        await btn_aceptar.click()
                        await esperar(1000)
                    raise Exception(f"Sistema no disponible: {texto_error[:100].strip()}")
            except Exception as e:
                if "Sistema no disponible" in str(e):
                    raise
                pass

    if not dia_frame:
        await screenshot(page, f"error_vdia_{label_hora.replace(':','')}.png")
        raise Exception("No se encontró #vDIA en ningún frame")

    await dia_frame.wait_for_selector("#vDIA", timeout=10000)
    await esperar(500)

    opciones = await dia_frame.eval_on_selector(
        "#vDIA",
        "sel => Array.from(sel.options).map(o => ({value: o.value, text: o.text}))"
    )
    log(f"   Días disponibles: {[o['text'] for o in opciones]}")

    # Seleccionar la opción que corresponde a la fecha objetivo
    fecha_buscada = fecha_objetivo.strftime("%d/%m/%y").lstrip("0").replace("/0", "/")
    valor_elegido = None
    for op in opciones:
        if fecha_objetivo.strftime("%d/%m") in op["text"] or fecha_buscada in op["text"]:
            valor_elegido = op["value"]
            log(f"   Día elegido: {op['text']}")
            break

    if not valor_elegido:
        # Tomar el último (mañana)
        valor_elegido = opciones[-1]["value"]
        log(f"   Día (último disponible): {opciones[-1]['text']}")

    await dia_frame.select_option("#vDIA", valor_elegido)
    await esperar(1500)

    # Click en la fila de la hora
    fila_hora = dia_frame.locator("tr").filter(has_text=label_hora).first
    if await fila_hora.count() > 0:
        await fila_hora.click()
    else:
        celda = dia_frame.locator(f"td:has-text('{label_hora}')").first
        if await celda.count() > 0:
            await celda.click()
        else:
            raise Exception(f"Hora {label_hora} no encontrada en la tabla")

    await esperar(600)
    log(f"   Hora {label_hora} seleccionada — confirmando...")

    # Screenshot antes de confirmar para ver el estado
    try:
        await dia_frame.screenshot(path=f"antes_confirmar_{label_hora.replace(':','')}.png")
        log(f"   📸 antes_confirmar_{label_hora.replace(':','')}.png")
    except:
        pass

    # Log del HTML del frame para ver qué hay seleccionado
    html_frame = await dia_frame.content()
    import re
    # Buscar aulas disponibles en la tabla
    aulas = re.findall(r'<tr[^>]*data-gxrow[^>]*>.*?</tr>', html_frame, re.DOTALL)
    log(f"   Filas en tabla de horarios: {len(aulas)}")
    for a in aulas[:5]:
        texto = re.sub(r'<[^>]+>', ' ', a).strip()
        texto = ' '.join(texto.split())
        log(f"     Fila: {texto[:120]}")

    # Buscar el botón Confirmar
    btn_confirmar = await dia_frame.query_selector("#BUTTON1")
    btn_value = await btn_confirmar.get_attribute("value") if btn_confirmar else "NO ENCONTRADO"
    log(f"   Botón #BUTTON1 value: {btn_value}")

    await dia_frame.click("#BUTTON1")
    await esperar(2000)

    # Screenshot después de confirmar
    try:
        await page.screenshot(path=f"despues_confirmar_{label_hora.replace(':','')}.png", full_page=True)
        log(f"   📸 despues_confirmar_{label_hora.replace(':','')}.png")
    except:
        pass

    log(f"   ✅ {label_hora} confirmada")

    # Cerrar el popup para que no bloquee la siguiente clase
    await cerrar_modal_614(page)
    await esperar(500)


async def agendar_clase(page, hora_config, fecha_objetivo):
    label = hora_config["label"]
    log(f"\n━━━ Agendando {label} ━━━")

    # Asegurarse de que no haya popup bloqueando
    await cerrar_modal_614(page)

    primera_fila, wv0613 = await encontrar_primera_clase_pendiente(page)

    log("   Click en fila de la clase...")
    await primera_fila.click()
    await esperar(500)

    log("   Click en Asignar...")
    await wv0613.locator("#BUTTON1[value='Asignar']").click()
    await esperar(2000)

    await seleccionar_dia_y_hora(page, label, fecha_objetivo)
    log(f"🎉 {label} agendada")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    log(f"🚀 {datetime.now(ZONA_COL).strftime('%A %d/%m/%Y %H:%M')} Colombia")

    # Determinar qué hay que agendar hoy
    horas, fecha_objetivo = calcular_clases_a_agendar()

    if not horas:
        log("✅ No hay clases que agendar hoy. Fin.")
        return

    log(f"   Clases a agendar: {[h['label'] for h in horas]} para el {fecha_objetivo.strftime('%d/%m/%Y')}")

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

            # Verificar si las clases ya están programadas
            if await clases_ya_programadas(page, fecha_objetivo, horas):
                log("✅ Nada que hacer — clases ya programadas.")
                return

            errores = []
            for hora_config in horas:
                try:
                    await agendar_clase(page, hora_config, fecha_objetivo)
                except Exception as e:
                    log(f"⚠️  Error {hora_config['label']}: {e}")
                    errores.append(f"{hora_config['label']}: {e}")
                    await screenshot(page, f"error_{hora_config['label'].replace(':','')}.png")

            if errores:
                for err in errores:
                    log(f"   ❌ {err}")
                sys.exit(1)
            else:
                log("✅ Todas las clases agendadas correctamente")

        except Exception as e:
            log(f"❌ Fatal: {e}")
            await screenshot(page)
            raise
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
