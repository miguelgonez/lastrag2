#!/bin/bash
echo "Empaquetando Py_LastRAG_Index_v2_triple..."
rm -f Py_LastRAG_Index_v2_triple.zip
zip -r Py_LastRAG_Index_v2_triple.zip . -x "*/__pycache__/*" -x "*.venv/*" -x "venv/*" -x "*.git/*" -x ".env" -x "*.DS_Store"
echo "Empaquetado completado: Py_LastRAG_Index_v2_triple.zip"
