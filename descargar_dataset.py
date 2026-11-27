from huggingface_hub import snapshot_download

ruta = snapshot_download(
    repo_id="rishia2220/icfd-31k",
    repo_type="dataset",
    local_dir="datos/ICFD-31k"
)

print("Dataset descargado en:", ruta)