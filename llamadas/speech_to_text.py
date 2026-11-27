import math
import os
import pathlib
import struct
import tempfile
import wave
from functools import lru_cache
from abc import ABC, abstractmethod

try:
    import audioop
except ModuleNotFoundError:  # Python 3.14+ removed audioop from stdlib.
    audioop = None


class AudioValidationError(ValueError):
    pass


class AudioNoInteligibleError(ValueError):
    pass


class SpeechToTextError(RuntimeError):
    pass


def _duracion_audio(ruta_archivo):
    with wave.open(ruta_archivo, 'rb') as audio:
        frames = audio.getnframes()
        rate = audio.getframerate()
        return frames / float(rate) if rate else 0.0


def _nivel_silencio(ruta_archivo):
    with wave.open(ruta_archivo, 'rb') as audio:
        frames = audio.readframes(audio.getnframes())
        if not frames:
            return 1.0

        sampwidth = audio.getsampwidth()
        if sampwidth == 1:
            valores = [((byte - 128) if byte < 128 else (byte - 128)) for byte in frames]
        elif sampwidth == 2:
            valores = struct.unpack('<' + 'h' * (len(frames) // 2), frames)
        elif sampwidth == 4:
            valores = struct.unpack('<' + 'i' * (len(frames) // 4), frames)
        else:
            return 1.0

        rms = math.sqrt(sum(v * v for v in valores) / len(valores)) if valores else 0.0
        max_value = float(2 ** (sampwidth * 8 - 1))
        return float(rms) / max_value if max_value else 0.0


class BaseSpeechToTextEngine(ABC):
    @abstractmethod
    def transcribir(self, archivo):
        raise NotImplementedError


class WhisperSpeechToTextEngine(BaseSpeechToTextEngine):
    def transcribir(self, archivo):
        if archivo is None:
            raise AudioValidationError('Se requiere un archivo de audio.')

        if hasattr(archivo, 'seek'):
            archivo.seek(0)

        extension = pathlib.Path(getattr(archivo, 'name', '') or '').suffix.lower()
        if extension not in {'.wav', '.webm', '.ogg', '.mp3', '.m4a', '.mp4'}:
            extension = '.wav'
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temp_file:
            temp_path = temp_file.name
            for chunk in archivo.chunks() if hasattr(archivo, 'chunks') else [archivo.read()]:
                if chunk:
                    temp_file.write(chunk)

        try:
            try:
                import whisper
            except ImportError as exc:
                raise SpeechToTextError('La dependencia Whisper no está instalada.') from exc

            try:
                duracion = _duracion_audio(temp_path)
                nivel = _nivel_silencio(temp_path)
            except (wave.Error, EOFError):
                # MediaRecorder suele producir WebM/Opus en Android y Chrome.
                # Whisper usa ffmpeg para decodificar esos formatos.
                audio = whisper.load_audio(temp_path, sr=16000)
                duracion = len(audio) / 16000.0
                nivel = float((audio ** 2).mean() ** 0.5) if len(audio) else 0.0
            if duracion <= 0:
                raise AudioNoInteligibleError('El audio está vacío o no tiene duración suficiente.')
            if nivel < 0.02:
                raise AudioNoInteligibleError('El audio no contiene voz inteligible.')

            # tiny es rápido, pero suele producir texto muy impreciso en español.
            # base mejora la transcripción sin el costo de small/medium. Se puede
            # cambiar con WHISPER_MODEL si el equipo dispone de más recursos.
            nombre_modelo = os.environ.get('WHISPER_MODEL', 'base').strip() or 'base'
            modelo = _obtener_modelo_whisper(whisper, nombre_modelo)
            resultado = modelo.transcribe(
                temp_path,
                fp16=False,
                language='es',
                task='transcribe',
                temperature=0,
                condition_on_previous_text=False,
                initial_prompt=(
                    'Conversación telefónica en español de México. Posibles términos: '
                    'BBVA, Banorte, Santander, Citibanamex, HSBC, Scotiabank, '
                    'código de verificación, NIP, contraseña, transferencia, depósito.'
                ),
            )
            texto = (resultado.get('text') or '').strip()
            if not texto:
                raise AudioNoInteligibleError('No se pudo extraer texto inteligible del audio.')

            confianza = 0.0
            segmentos = resultado.get('segments') or []
            if segmentos and 'avg_logprob' in segmentos[0]:
                logprob = float(segmentos[0]['avg_logprob'])
                confianza = max(0.0, min(1.0, 1.0 / (1.0 + abs(logprob))))

            return {
                'texto': texto,
                'confianza': confianza,
                'duracion_audio': duracion,
            }
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


@lru_cache(maxsize=2)
def _obtener_modelo_whisper(whisper, nombre_modelo):
    """Mantiene el modelo cargado entre turnos para evitar recargarlo cada vez."""
    return whisper.load_model(nombre_modelo)


def transcribir_audio(archivo):
    """Servicio desacoplado para convertir audio a texto usando Whisper."""
    try:
        resultado = WhisperSpeechToTextEngine().transcribir(archivo)
        return {
            'texto': resultado['texto'],
            'confianza': float(resultado.get('confianza', 0.0)),
            'duracion_audio': float(resultado.get('duracion_audio', 0.0)),
            'estado': 'COMPLETADO',
        }
    except AudioNoInteligibleError as exc:
        return {
            'texto': '',
            'confianza': 0.0,
            'duracion_audio': 0.0,
            'estado': 'AUDIO_NO_INTELIGIBLE',
            'error': str(exc),
        }
    except (AudioValidationError, ValueError) as exc:
        return {
            'texto': '',
            'confianza': 0.0,
            'duracion_audio': 0.0,
            'estado': 'ERROR',
            'error': str(exc),
        }
    except Exception as exc:
        return {
            'texto': '',
            'confianza': 0.0,
            'duracion_audio': 0.0,
            'estado': 'ERROR',
            'error': str(exc),
        }
