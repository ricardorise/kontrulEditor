#!/usr/bin/env bash
# Detecta se o Docker consegue entregar GPU NVIDIA aos contêineres.
#   scripts/gpu.sh          -> imprime "yes" ou "no" (uso do Makefile)
#   scripts/gpu.sh --explain -> imprime o diagnóstico e o que falta
host_gpu=no; command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1 && host_gpu=yes
rt=no; docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia && rt=yes
cdi=no; docker info --format '{{json .CDISpecDirs}}' 2>/dev/null | grep -q '/' && [ -n "$(ls /etc/cdi /var/run/cdi 2>/dev/null | grep -i nvidia)" ] && cdi=yes
# Docker Desktop (Windows/WSL2) entrega a GPU sem listar o runtime "nvidia": se há GPU no host e o runtime não
# apareceu, testa de verdade pedindo a GPU a um contêiner mínimo.
probe=skip
if [ "$rt" != yes ] && [ "$cdi" != yes ] && [ "$host_gpu" = yes ]; then
  if docker run --rm --gpus all alpine:3 true >/dev/null 2>&1; then probe=yes; else probe=no; fi
fi
{ [ "$rt" = yes ] || [ "$cdi" = yes ] || [ "$probe" = yes ]; } && ok=yes || ok=no
if [ "${1:-}" = "--explain" ]; then
  echo "GPU NVIDIA no host (nvidia-smi): $host_gpu"
  echo "Docker com runtime nvidia:       $rt (CDI: $cdi, teste --gpus all: $probe)"
  if [ "$ok" = yes ]; then echo "=> o worker-asr subirá na GPU do host (large-v3)."
  elif [ "$host_gpu" = yes ]; then
    echo "=> há GPU no host, mas o Docker não a expõe. Instale o nvidia-container-toolkit e rode:"
    echo "   sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
  else echo "=> sem GPU NVIDIA detectada: o worker-asr rodará em CPU (modelo small)."; fi
else echo "$ok"; fi
