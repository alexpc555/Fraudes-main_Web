import os
import wave
from datetime import datetime
from pathlib import Path

from django.conf import settings


def _ruta_base():
    base = Path(settings.MEDIA_ROOT) / 'tts_agente'
    base.mkdir(parents=True, exist_ok=True)
    return base


def limpiar_audios_antiguos(max_archivos=50):
    base = _ruta_base()
    archivos = sorted(base.glob('*.wav'), key=lambda item: item.stat().st_mtime, reverse=True)
    for archivo in archivos[max_archivos:]:
        if archivo.exists():
            archivo.unlink(missing_ok=True)


def generar_audio(texto, idioma='es-MX', voz='es-ES-Standard-A', velocidad=1.0, volumen=1.0, formato='wav'):
    """Genera un archivo WAV sintético para simular un TTS de prueba en español mexicano."""
    texto_limpio = (texto or '').strip()
    if not texto_limpio:
        return {'estado': 'ERROR', 'error': 'El texto es obligatorio para generar audio.', 'ruta': ''}

    if formato.lower() != 'wav':
        formato = 'wav'

    base = _ruta_base()
    nombre_archivo = f"tts_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{abs(hash(texto_limpio)) % 10000}.wav"
    ruta = base / nombre_archivo

    try:
        sample_rate = 22050
        duracion = max(0.6, min(6.0, len(texto_limpio) * 0.06 * (2.0 / velocidad)))
        total_samples = int(sample_rate * duracion)

        with wave.open(str(ruta), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            frames = bytearray()
            for i in range(total_samples):
                t = i / sample_rate
                frecuencia = 220 + (i % 16) * 11
                amplitud = int(18000 * volumen * max(0.15, 0.9 - 0.2 * ((i % 45) / 45)))
                valor = int(amplitud * (0.6 * __import__('math').sin(2 * __import__('math').pi * frecuencia * t) + 0.2 * __import__('math').sin(2 * __import__('math').pi * (frecuencia * 2.5) * t)))
                frames.extend(__import__('struct').pack('<h', max(-32767, min(32767, valor))))
            wav_file.writeframes(bytes(frames))

        limpiar_audios_antiguos()
        return {
            'estado': 'OK',
            'archivo': nombre_archivo,
            'ruta': str(ruta),
            'idioma': idioma,
            'voz': voz,
            'velocidad': velocidad,
            'volumen': volumen,
            'formato': formato,
        }
    except Exception as exc:  # pragma: no cover - branch for engine errors
        return {'estado': 'ERROR', 'error': f'No fue posible generar el audio del agente: {exc}', 'ruta': ''}


def reproducir_texto_voz(texto, idioma='es-MX', voz='es-MX-Normal-A', velocidad=1.0, volumen=1.0, formato='wav'):
    """Genera y devuelve un audio para reproducir texto con TTS, separando la capa backend de la reproducción del navegador."""
    texto_limpio = (texto or '').strip()
    if not texto_limpio:
        return {'estado': 'ERROR', 'error': 'El texto es obligatorio para reproducir audio.', 'ruta': '', 'audio_url': ''}

    resultado = generar_audio(texto_limpio, idioma=idioma, voz=voz, velocidad=velocidad, volumen=volumen, formato=formato)
    if resultado.get('estado') != 'OK':
        return {'estado': 'ERROR', 'error': resultado.get('error', 'No fue posible generar el audio.'), 'ruta': '', 'audio_url': ''}

    nombre_archivo = os.path.basename(resultado['ruta'])
    media_url = getattr(settings, 'MEDIA_URL', '/media/')
    return {
        'estado': 'OK',
        'ruta': resultado['ruta'],
        'audio_url': f"{media_url.rstrip('/')}/tts_agente/{nombre_archivo}",
        'archivo': nombre_archivo,
        'idioma': idioma,
        'voz': voz,
        'velocidad': velocidad,
        'volumen': volumen,
        'formato': formato,
    }
