"""Isolated optional RapidLaTeXOCR worker; receives one local formula crop."""
import json
import sys
from pathlib import Path
from rapid_latex_ocr import LaTeXOCR
from rapid_latex_ocr import utils_load

# Bound CPU use without patching the installed third-party package.
original_init = utils_load.OrtInferSession.__init__
def bounded_init(self, model_path, num_threads=4):
    original_init(self, model_path, num_threads=4)
utils_load.OrtInferSession.__init__ = bounded_init
root = Path(sys.argv[1])
engine = LaTeXOCR(**{key: root / name for key, name in {
    'image_resizer_path':'image_resizer.onnx', 'encoder_path':'encoder.onnx',
    'decoder_path':'decoder.onnx','tokenizer_json':'tokenizer.json'}.items()})
latex, elapsed = engine(sys.argv[2])
print(json.dumps({'latex':latex, 'elapsed':elapsed}, ensure_ascii=False))
