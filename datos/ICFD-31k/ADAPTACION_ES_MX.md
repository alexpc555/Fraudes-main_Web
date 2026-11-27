# Uso de ICFD-31k en el detector de llamadas

ICFD-31k contiene conversaciones sintéticas en inglés/Hinglish. Sus anotaciones
sirven para estudiar fraude conversacional, pero el contenido no está traducido
al español mexicano ni representa por sí solo la forma en que se habla en México.
Por eso el detector de este proyecto conserva las transcripciones originales y
usa un catálogo local de expresiones mexicanas en `llamadas/migrations/0012_patrones_es_mx.py`.

## Aplicar los patrones locales

```bash
python manage.py migrate
```

El catálogo busca solicitudes de NIP, contraseñas, CVV, códigos SMS/token,
CLABE, transferencias, depósitos, instalación de aplicaciones y acceso remoto.
La urgencia y la suplantación aportan señales de apoyo. Una palabra clave sola
no debe determinar que alguien cometió fraude; la puntuación se interpreta como
una alerta para verificar por un canal oficial.

## Interpretación del riesgo

- **Verde (0–29):** sin señales importantes en el texto disponible. No prueba
  que la llamada sea legítima.
- **Amarillo (30–69):** señales incompletas, presión, evasivas o varias señales
  moderadas; verificar identidad y motivo por un canal independiente.
- **Rojo (70 o más):** solicitud de credenciales/códigos/dinero o amenaza
  explícita; no compartir datos ni realizar acciones durante la llamada.

Los puntajes son una política del proyecto, no una probabilidad estadística de
fraude. Para estimar probabilidades y medir precisión/recobrado se requiere un
conjunto de evaluación etiquetado en español mexicano y revisado por personas.

## Traducción y entrenamiento local

Instala las dependencias opcionales (PyTorch puede ocupar varios GB y una GPU
reduce mucho el tiempo de traducción):

```bash
pip install -r requirements-ml.txt
python scripts/traducir_icfd_es_mx.py
python scripts/entrenar_clasificador_icfd.py
```

El traductor usa NLLB local y guarda copias en `datos/ICFD-31k/es_mx/`; no
sobrescribe las fuentes. Se puede reanudar por shard. El clasificador ajusta un
modelo de español sobre las transcripciones traducidas y guarda el artefacto y
las métricas en `modelos/icfd-es-mx/`. La aplicación lo carga localmente cuando
se configura `FRAUD_MODEL_PATH=modelos/icfd-es-mx`; si no se configura o no está
instalado `requirements-ml.txt`, opera con las reglas existentes.

La traducción automática de NLLB se configura con inglés como idioma de origen.
Hinglish, nombres propios, referencias culturales y frases ambiguas pueden quedar
mal traducidos; los resultados llevan `automatic_unreviewed` y requieren una
revisión manual antes de usarse para conclusiones. El modelo binario da una
señal adicional: su probabilidad no equivale a la puntuación 0–100 de la app.

## Cómo aprovechar los datos de ICFD-31k

1. Usa `train` para investigación/desarrollo y conserva `validation` y `test`
   separados para medir desempeño. No uses `cross_domain` como entrenamiento si
   se quiere medir generalización a tipos de fraude no vistos.
2. Alinea el veredicto original con una etiqueta binaria de fraude solo después
   de revisar sus valores exactos. No conviertas directamente ese veredicto en
   verde/amarillo/rojo: el nivel requiere una política de severidad aparte.
3. Conserva texto, idioma, etiqueta original, partición e identificador de
   origen. El script crea columnas `transcript_es_mx` y `*_es_mx` sin reemplazar
   el contenido original. Revisa manualmente una muestra de traducciones
   Hinglish y de casos con negación, citas, ironía, urgencia legítima y palabras
   bancarias.
4. No publiques ni entrenes con una traducción automática como si fuera una
   conversación mexicana real. Añade conversaciones mexicanas consentidas,
   desidentificadas y revisadas para evaluar modismos y falsos positivos.

El dataset declara uso defensivo/educativo. Sus métricas publicadas no garantizan
el mismo desempeño en español mexicano ni en llamadas reales. La app debe mostrar
las señales y el texto que originaron cada alerta para que la persona pueda
verificarlas.
