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
import urllib.request
import urllib.parse

def enviar_whatsapp(mensaje: str):
    """Envía mensaje de WhatsApp via Twilio Sandbox (gratis)."""
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token  = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = os.environ.get("TWILIO_FROM", "")   # whatsapp:+14155238886
    to_number   = os.environ.get("TWILIO_TO", "")     # whatsapp:+57XXXXXXXXX

    if not all([account_sid, auth_token, from_number, to_number]):
        log("   ⚠️  WhatsApp no configurado — omitiendo notificación")
        return

    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        data = urllib.parse.urlencode({
            "From": from_number,
            "To": to_number,
            "Body": mensaje
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        import base64
        creds = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            log(f"   📱 WhatsApp enviado (status {resp.status})")
    except Exception as e:
        log(f"   ⚠️  Error enviando WhatsApp: {e}")

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
      
    await page.fill("#vUSUCOD", "")
    await page.fill("#vPASS", "")
    await page.locator("#vUSUCOD").press_sequentially(USUARIO, delay=80)
    await page.locator("#vPASS").press_sequentially(PASSWORD, delay=80)
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

    # Buscar la primera clase pendiente que NO sea SMART ZONE
    count = await filas.count()
    for i in range(count):
        fila = filas.nth(i)
        texto = await fila.text_content()
        if "SMART ZONE" in texto.upper():
            log(f"   Saltando SMART ZONE: {texto[:60].strip()}")
            continue
        log(f"   Clase encontrada: {texto[:80].strip()}")
        return fila, wv0613

    raise Exception("No hay clases pendientes por programar (todas son SMART ZONE)")


async def seleccionar_dia_y_hora(page, label_hora, fecha_objetivo, hora_config=None):
    log(f"   Configurando {label_hora}...")
    hora_config = hora_config or {}

    # Buscar el frame wv0614a
    dia_frame = None
    for _ in range(15):
        for f in page.frames:
            if "wv0614" in f.url:
                dia_frame = f
                break
        if dia_frame:
            break
        await esperar(1000)

    if not dia_frame:
        for f in page.frames:
            try:
                if await f.query_selector("#vDIA"):
                    dia_frame = f
                    break
            except:
                continue

    if not dia_frame:
        raise Exception("No se encontró frame wv0614a")

    await dia_frame.wait_for_selector("#vDIA", timeout=10000)
    await esperar(800)

    # Obtener opciones de día
    opciones_dia = await dia_frame.eval_on_selector(
        "#vDIA",
        "sel => Array.from(sel.options).map(o => ({value: o.value, text: o.text}))"
    )
    log(f"   Días disponibles: {[o['text'] for o in opciones_dia]}")

    # Buscar el valor del día objetivo
    valor_dia = None
    for op in opciones_dia:
        if fecha_objetivo.strftime("%d/%m") in op["text"]:
            valor_dia = op["value"]
            log(f"   Día: {op['text']} (value={valor_dia})")
            break
    if not valor_dia:
        valor_dia = opciones_dia[-1]["value"]
        log(f"   Día (último): {opciones_dia[-1]['text']} (value={valor_dia})")

    # Determinar la sede
    sede_values = {"SAN MARTIN": "17", "SANTAFE": "32"}
    sede_nombre = hora_config.get("sede", "SANTAFE")
    valor_sede = sede_values.get(sede_nombre, "32")
    log(f"   Sede: {sede_nombre} (value={valor_sede})")

    # Determinar la fila de la hora en la grilla
    # Las filas tienen hora inicio en HORSEDHIN — buscar la que corresponde
    hora_fila_map = {
        "06:00": "0001", "07:30": "0002", "09:00": "0003",
        "10:30": "0004", "12:00": "0005", "13:30": "0006",
        "15:00": "0007", "16:30": "0008", "18:00": "0009", "19:30": "0010"
    }
    fila_id = hora_fila_map.get(label_hora, "0009")
    log(f"   Fila de hora: {fila_id}")

    # Cambiar sede via Playwright (más confiable que JS puro para GeneXus)
    sede_actual = await dia_frame.eval_on_selector("#vREGCONREG", "s => s.value")
    if sede_actual != valor_sede:
        log(f"   Cambiando sede {sede_actual} -> {valor_sede}...")
        await dia_frame.select_option("#vREGCONREG", valor_sede)
        # Disparar el onblur que GeneXus usa para procesar el cambio
        await dia_frame.evaluate("() => { const s = document.querySelector('#vREGCONREG'); s.blur(); }")
        await dia_frame.evaluate("() => { if(typeof gx!='undefined') gx.evt.onchange(document.querySelector('#vREGCONREG'), {}); }")
        await esperar(3000)

    # Cambiar día via Playwright
    dia_actual = await dia_frame.eval_on_selector("#vDIA", "s => s.value")
    if dia_actual != valor_dia:
        log(f"   Cambiando día {dia_actual} -> {valor_dia}...")
        await dia_frame.select_option("#vDIA", valor_dia)
        await dia_frame.evaluate("() => { const s = document.querySelector('#vDIA'); s.blur(); }")
        await dia_frame.evaluate("() => { if(typeof gx!='undefined') gx.evt.onchange(document.querySelector('#vDIA'), {}); }")
        await esperar(3000)

    # Verificar valores actuales
    dia_final = await dia_frame.eval_on_selector("#vDIA", "s => s.value")
    sede_final = await dia_frame.eval_on_selector("#vREGCONREG", "s => s.value")
    log(f"   Valores tras cambios — día={dia_final}, sede={sede_final}")

    # Seleccionar la fila de la hora buscando por texto
    horas_disponibles = await dia_frame.eval_on_selector_all(
        "span[id^='span_HORSEDHIN_']",
        "spans => spans.map(s => s.textContent.trim())"
    )
    log(f"   Horas en grilla: {horas_disponibles}")

    fila_encontrada = False
    for intento in range(5):
        filas = dia_frame.locator("tr[data-gxrow]")
        count = await filas.count()
        for i in range(count):
            fila = filas.nth(i)
            hora_celda = fila.locator("span[id^='span_HORSEDHIN_']").first
            if await hora_celda.count() > 0:
                texto = (await hora_celda.text_content()).strip()
                if texto == label_hora:
                    log(f"   Haciendo click en fila con hora {texto}...")
                    await fila.click()
                    await esperar(600)
                    fila_encontrada = True
                    break
        if fila_encontrada:
            break
        log(f"   Intento {intento+1}: hora {label_hora} no encontrada, reintentando...")
        await esperar(1000)

    # Verificar selección
    sel = await dia_frame.query_selector("tr[data-gxselected]")
    if sel:
        hora_sel = await sel.query_selector("span[id^='span_HORSEDHIN_']")
        txt = (await hora_sel.text_content()).strip() if hora_sel else "?"
        log(f"   Fila seleccionada: {txt}")
    else:
        log("   ⚠️  Ninguna fila quedó seleccionada")

    resultado = {
        "dia": dia_final,
        "sede": sede_final,
        "horaSeleccionada": txt if sel else "ninguna",
        "horasDisponibles": horas_disponibles
    }

    log(f"   Estado JS — día={resultado['dia']}, sede={resultado['sede']}, hora={resultado['horaSeleccionada']}")
    log(f"   Horas disponibles en grilla: {resultado.get('horasDisponibles', [])}")
    await esperar(500)

    # Verificar que hay una hora seleccionada antes de confirmar
    sel_check = await dia_frame.query_selector("tr[data-gxselected]")
    if not sel_check:
        # Verificar si la grilla está vacía (no hay horarios disponibles ese día)
        filas_grilla = await dia_frame.query_selector_all("tr[data-gxrow]")
        if len(filas_grilla) == 0:
            msg = (f"⚠️ No hay horarios disponibles para el "
                   f"{fecha_objetivo.strftime('%d/%m/%Y')} en {hora_config.get('sede','la sede')}. "
                   f"Posiblemente hay una actividad institucional ese día.")
            log(f"   {msg}")
            enviar_whatsapp(f"Smart Idiomas Bot:\n{msg}")
            raise Exception(f"Sin horarios disponibles para {label_hora} el {fecha_objetivo.strftime('%d/%m/%Y')}")
        else:
            log(f"   ⚠️  Hay {len(filas_grilla)} filas pero ninguna seleccionada")
            raise Exception(f"No se pudo seleccionar la hora {label_hora}")

    # Click en Confirmar
    log(f"   Confirmando...")
    await dia_frame.click("#BUTTON1")
    await esperar(2000)

    # Verificar que no apareció mensaje de error
    error_msg = await dia_frame.query_selector(".gx-warning-message, .ErrorViewer")
    if error_msg:
        txt_error = await error_msg.text_content()
        if txt_error and txt_error.strip():
            log(f"   ❌ Error de plataforma: {txt_error.strip()}")
            raise Exception(f"Error al confirmar: {txt_error.strip()}")

    log(f"   ✅ {label_hora} confirmada")
    await cerrar_modal_614(page)
    await esperar(500)


async def validar_clase_programada(page, fecha_objetivo, label_hora):
    """Verifica que la clase quedó realmente programada en la fecha y hora correctas."""
    log(f"   🔎 Validando que {label_hora} quedó programada para {fecha_objetivo.strftime('%d/%m/%Y')}...")
    
    wv0613 = await get_wv0613_frame(page)
    if not wv0613:
        log("   ⚠️  No se pudo validar — frame wv0613 no encontrado")
        return False

    # Filtrar por Programadas
    await wv0613.select_option("#vTPEAPROBO", "3")
    await esperar(2000)

    html = await wv0613.content()
    fecha_str = fecha_objetivo.strftime("%d/%m/%y")
    fecha_str2 = fecha_objetivo.strftime("%-d/%-m/%y")

    # Buscar la fecha y hora en el HTML
    fecha_ok = fecha_str in html or fecha_str2 in html
    hora_ok = label_hora in html

    if fecha_ok and hora_ok:
        log(f"   ✅ Confirmado: clase {label_hora} programada para {fecha_objetivo.strftime('%d/%m/%Y')}")
        resultado = True
    else:
        log(f"   ❌ NO se encontró la clase programada (fecha={fecha_ok}, hora={hora_ok})")
        resultado = False

    # Volver a "Todos los estados"
    await wv0613.select_option("#vTPEAPROBO", "0")
    await esperar(500)
    return resultado


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

    await seleccionar_dia_y_hora(page, label, fecha_objetivo, hora_config)
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

        # Login con reintentos
        for intento_login in range(3):
            try:
                await hacer_login(page)
                break
            except Exception as e:
                log(f"⚠️  Login intento {intento_login+1}/3 fallido: {e}")
                if intento_login == 2:
                    raise Exception(f"Login fallido tras 3 intentos: {e}")
                log("   Reintentando en 10 segundos...")
                await esperar(10000)
                
                # Destruir la página actual y crear una nueva
                await page.close()
                page = await (await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    locale="es-CO",
                )).new_page()

        try:
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
                    # Validar que realmente quedó programada
                    ok = await validar_clase_programada(page, fecha_objetivo, hora_config["label"])
                    if not ok:
                        raise Exception(f"Clase {hora_config['label']} NO quedó programada en la plataforma")
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
                enviar_whatsapp(
                    f"✅ Smart Idiomas Bot:\n"
                    f"Clases agendadas para el {fecha_objetivo.strftime('%d/%m/%Y')}:\n" +
                    "\n".join([f"  • {h['label']} en {h.get('sede','')}" for h in horas])
                )

        except Exception as e:
            log(f"❌ Fatal: {e}")
            await screenshot(page)
            raise
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
