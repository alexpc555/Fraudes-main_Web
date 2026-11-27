"""Crea una copia paralela de ICFD-31k en español usando traducción local NLLB."""
import argparse
import copy
import json
import subprocess
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


MODEL_ID = 'facebook/nllb-200-distilled-600M'
TEXT_FIELDS = ('final_slow_thinking_rationale', 'policy', 'description')


def traducir_lotes(textos, tokenizer, modelo, dispositivo, tamano_lote=8):
    salidas = []
    tokenizer.src_lang = 'eng_Latn'
    for inicio in range(0, len(textos), tamano_lote):
        lote = textos[inicio:inicio + tamano_lote]
        entradas = tokenizer(lote, return_tensors='pt', padding=True, truncation=True, max_length=512).to(dispositivo)
        with torch.no_grad():
            tokens = modelo.generate(
                **entradas,
                forced_bos_token_id=tokenizer.convert_tokens_to_ids('spa_Latn'),
                max_new_tokens=512,
                num_beams=4,
            )
        salidas.extend(tokenizer.batch_decode(tokens, skip_special_tokens=True))
    return salidas


def traducir_registro(registro, tokenizer, modelo, dispositivo):
    copia = copy.deepcopy(registro)
    turnos = registro.get('transcript') or []
    textos = [str(turno.get('text') or '') for turno in turnos]
    ubicaciones = [('turno', indice) for indice in range(len(turnos))]
    for campo in TEXT_FIELDS:
        valor = registro.get(campo)
        if isinstance(valor, str) and valor.strip():
            textos.append(valor)
            ubicaciones.append((campo, None))
    traducidos = traducir_lotes(textos, tokenizer, modelo, dispositivo)
    copia['transcript_es_mx'] = copy.deepcopy(turnos)
    for traduccion, (tipo, indice) in zip(traducidos, ubicaciones):
        if tipo == 'turno':
            copia['transcript_es_mx'][indice]['text'] = traduccion
        else:
            copia[f'{tipo}_es_mx'] = traduccion
    copia['translation_metadata'] = {
        'model': MODEL_ID,
        'source_language': 'eng_Latn (Hinglish puede requerir revisión)',
        'target_language': 'spa_Latn',
        'review_status': 'automatic_unreviewed',
    }
    return copia


def id_registro(registro):
    metadata = registro.get('release_metadata') or {}
    return metadata.get('conversation_uid') or registro.get('session_id')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', default='datos/ICFD-31k')
    parser.add_argument('--output-dir', default='datos/ICFD-31k/es_mx')
    parser.add_argument('--model', default=MODEL_ID)
    parser.add_argument('--device', choices=('auto', 'cpu', 'cuda'), default='auto')
    parser.add_argument('--batch-size', type=int, default=8)
    args = parser.parse_args()

    raiz = Path(args.dataset_dir)
    salida = Path(args.output_dir)
    salida.mkdir(parents=True, exist_ok=True)
    dispositivo = 'cuda' if args.device == 'auto' and torch.cuda.is_available() else args.device
    if dispositivo == 'auto':
        dispositivo = 'cpu'
    tokenizer = AutoTokenizer.from_pretrained(args.model, src_lang='eng_Latn')
    modelo = AutoModelForSeq2SeqLM.from_pretrained(args.model).to(dispositivo)
    modelo.eval()

    shards = sorted((raiz / 'source_conversations').glob('*.jsonl.zst'))
    if not shards:
        raise SystemExit(f'No hay shards .jsonl.zst en {raiz / "source_conversations"}')
    for shard in shards:
        destino = salida / f'{shard.name.removesuffix(".zst")}.es-mx.jsonl'
        procesados = set()
        if destino.exists():
            with destino.open(encoding='utf-8') as existente:
                for linea in existente:
                    try:
                        procesados.add(id_registro(json.loads(linea)))
                    except json.JSONDecodeError:
                        continue
        comando = ['zstd', '-dc', str(shard)]
        with subprocess.Popen(comando, stdout=subprocess.PIPE, text=True, encoding='utf-8') as proceso:
            with destino.open('a', encoding='utf-8') as archivo_salida:
                assert proceso.stdout is not None
                for linea in proceso.stdout:
                    registro = json.loads(linea)
                    identificador = id_registro(registro)
                    if identificador in procesados:
                        continue
                    traducido = traducir_registro(registro, tokenizer, modelo, dispositivo)
                    archivo_salida.write(json.dumps(traducido, ensure_ascii=False) + '\n')
                    procesados.add(identificador)
                if proceso.wait() != 0:
                    raise RuntimeError(f'Falló zstd al leer {shard}')
        print(f'Traducido: {shard.name} -> {destino}')


if __name__ == '__main__':
    main()
