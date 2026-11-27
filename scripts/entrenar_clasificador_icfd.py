"""Ajusta un clasificador binario sobre las copias traducidas por traducir_icfd_es_mx.py."""
import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, f1_score, precision_score, recall_score
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)


BASE_MODEL = 'dccuchile/bert-base-spanish-wwm-cased'


def leer_ejemplos(ruta_datos):
    ejemplos = []
    for archivo in sorted(Path(ruta_datos).glob('*.jsonl.es-mx.jsonl')):
        with archivo.open(encoding='utf-8') as entrada:
            for linea in entrada:
                fila = json.loads(linea)
                etiqueta = str(fila.get('final_verdict', '')).upper()
                if etiqueta not in {'YES', 'NO'}:
                    continue
                turnos = fila.get('transcript_es_mx') or []
                texto = '\n'.join(
                    f"{turno.get('speaker', 'Persona')}: {turno.get('text', '')}"
                    for turno in turnos if turno.get('text')
                ).strip()
                split = (fila.get('release_metadata') or {}).get('split', '')
                if texto and split in {'train', 'validation', 'test', 'cross_domain'}:
                    ejemplos.append({'text': texto, 'label': int(etiqueta == 'YES'), 'split': split})
    return ejemplos


class DatasetTexto:
    def __init__(self, registros, tokenizer, max_length=512):
        self.registros = registros
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.registros)

    def __getitem__(self, indice):
        fila = self.registros[indice]
        tokens = self.tokenizer(fila['text'], truncation=True, max_length=self.max_length)
        tokens['labels'] = fila['label']
        return tokens


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='datos/ICFD-31k/es_mx')
    parser.add_argument('--output-dir', default='modelos/icfd-es-mx')
    parser.add_argument('--base-model', default=BASE_MODEL)
    parser.add_argument('--epochs', type=float, default=3)
    parser.add_argument('--batch-size', type=int, default=8)
    args = parser.parse_args()

    registros = leer_ejemplos(args.data_dir)
    splits = {nombre: [r for r in registros if r['split'] == nombre]
              for nombre in ('train', 'validation', 'test', 'cross_domain')}
    if not splits['train'] or not splits['validation']:
        raise SystemExit('Se requieren ejemplos traducidos de train y validation.')
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    modelo = AutoModelForSequenceClassification.from_pretrained(
        args.base_model, num_labels=2,
        id2label={0: 'BENIGN', 1: 'FRAUD'}, label2id={'BENIGN': 0, 'FRAUD': 1},
    )
    argumentos = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        evaluation_strategy='epoch',
        save_strategy='epoch',
        load_best_model_at_end=True,
        metric_for_best_model='f1',
        greater_is_better=True,
        report_to='none',
        logging_steps=100,
        seed=42,
    )

    def metricas(eval_pred):
        logits, etiquetas = eval_pred
        predicciones = np.argmax(logits, axis=-1)
        return {
            'accuracy': accuracy_score(etiquetas, predicciones),
            'precision': precision_score(etiquetas, predicciones, zero_division=0),
            'recall': recall_score(etiquetas, predicciones, zero_division=0),
            'f1': f1_score(etiquetas, predicciones, zero_division=0),
        }

    entrenador = Trainer(
        model=modelo,
        args=argumentos,
        train_dataset=DatasetTexto(splits['train'], tokenizer),
        eval_dataset=DatasetTexto(splits['validation'], tokenizer),
        compute_metrics=metricas,
    )
    entrenador.train()
    salida = Path(args.output_dir)
    salida.mkdir(parents=True, exist_ok=True)
    entrenador.save_model(str(salida))
    tokenizer.save_pretrained(str(salida))

    resultados = {'validation': entrenador.evaluate(DatasetTexto(splits['validation'], tokenizer))}
    for nombre in ('test', 'cross_domain'):
        if splits[nombre]:
            pred = entrenador.predict(DatasetTexto(splits[nombre], tokenizer))
            etiquetas = np.array([r['label'] for r in splits[nombre]])
            clases = np.argmax(pred.predictions, axis=-1)
            resultados[nombre] = {
                'accuracy': accuracy_score(etiquetas, clases),
                'precision': precision_score(etiquetas, clases, zero_division=0),
                'recall': recall_score(etiquetas, clases, zero_division=0),
                'f1': f1_score(etiquetas, clases, zero_division=0),
                'classification_report': classification_report(
                    etiquetas, clases, target_names=['benigno', 'fraude'], zero_division=0,
                ),
                'n': len(etiquetas),
            }
    (salida / 'metricas.json').write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(resultados, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
