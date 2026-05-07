🤖 Smart Idiomas — Agendador automático de clases
Agenda automáticamente tus clases de inglés todos los días a las 8am.
Cómo funciona
Cada día a las 8am (hora Colombia), GitHub Actions ejecuta el script que:
Hace login en `schoolpack.smart.edu.co`
Entra a tu plan de inglés (`INGA1B2`)
Busca la primera clase pendiente
La agenda para el día siguiente a las 18:00 y 19:30
Setup (15 minutos, una sola vez)
1. Crear el repositorio en GitHub
Ve a github.com/new
Nombre: `smart-scheduler` (o el que quieras)
Privado ✅ (importante — contiene tus credenciales cifradas)
Click en "Create repository"
2. Subir los archivos
```bash
git clone https://github.com/TU_USUARIO/smart-scheduler
cd smart-scheduler

# Copiar los archivos de este proyecto
cp scheduler.py .github/workflows/agendar.yml requirements.txt .

git add .
git commit -m "Agendador inicial"
git push
```
3. Configurar los Secrets (credenciales)
En tu repositorio de GitHub:
Ve a Settings → Secrets and variables → Actions
Click en "New repository secret" y agrega estos 3:
Secret	Valor
`SMART_USUARIO`	Tu número de cédula
`SMART_PASSWORD`	Tu contraseña de Smart
`SMART_PLAN`	`INGA1B2` (o el código de tu plan)
4. Verificar que funciona
Ve a la pestaña Actions de tu repositorio
Click en el workflow "Agendar clases de inglés"
Click en "Run workflow" para probarlo manualmente ahora
Si el workflow se pone verde ✅, está funcionando.  
Si se pone rojo ❌, revisa los logs — hay un screenshot del error como artefacto.
Ajustar las horas
Las horas se configuran en `scheduler.py`:
```python
HORAS = [
    {"fila": "0009", "label": "18:00"},   # 18:00 - 19:30
    {"fila": "0010", "label": "19:30"},   # 19:30 - 21:00
]
```
El número de fila corresponde a la posición en la tabla de horarios de la plataforma:
Fila 0001 = 06:00–07:30
Fila 0002 = 07:30–09:00
...
Fila 0009 = 18:00–19:30
Fila 0010 = 19:30–21:00
Costo
$0 — GitHub Actions tiene 2,000 minutos gratis al mes.  
Este job usa ~2 minutos por día = ~60 minutos/mes. Sobra capacidad.
