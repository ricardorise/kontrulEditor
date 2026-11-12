#!/usr/bin/env bash
# Detecta se o Docker consegue entregar GPU NVIDIA aos contêineres.
#   scripts/gpu.sh          -> imprime "yes" ou "no" (uso do Makefile)
#   scripts/gpu.sh --explain -> imprime o diagnóstico e o que falta
host_gpu=no; command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1 && host_gpu=yes
rt=no; docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia && rt=yes
cdi=no; docker info --format '{{json .CDISpecDirs}}' 2>/dev/null | grep -q '/' && [ -n "$(ls /etc/cdi /var/run/cdi 2>/dev/null | grep -i nvidia)" ] && cdi=yes
[ "$rt" = yes ] || [ "$cdi" = yes ] && ok=yes || ok=no
if [ "${1:-}" = "--explain" ]; then
  echo "GPU NVIDIA no host (nvidia-smi): $host_gpu"
  echo "Docker com runtime nvidia:       $rt (CDI: $cdi)"
  if [ "$ok" = yes ]; then echo "=> o worker-asr subirá na GPU (large-v3)."
  elif [ "$host_gpu" = yes ]; then
    echo "=> há GPU no host, mas o Docker não a expõe. Instale o nvidia-container-toolkit e rode:"
    echo "   sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
  else echo "=> sem GPU NVIDIA detectada: o worker-asr rodará em CPU (modelo small)."; fi
else echo "$ok"; fi
