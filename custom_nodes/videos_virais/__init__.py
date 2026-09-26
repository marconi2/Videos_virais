# -*- coding: utf-8 -*-
"""
Videos Virais — custom nodes do ComfyUI.

O ComfyUI procura NODE_CLASS_MAPPINGS e NODE_DISPLAY_NAME_MAPPINGS neste
__init__.py ao carregar a pasta custom_nodes/videos_virais/.

Papel destes nos: o ComfyUI (maquina local, sem GPU forte) so ORGANIZA e
DISPARA. A geracao de video roda no Modal (A100), sob demanda, e a GPU desliga
sozinha depois. Ver nodes.py para detalhes.
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

# Opcional: se um dia adicionarmos assets JS de frontend, apontar aqui.
# WEB_DIRECTORY = "./web"
