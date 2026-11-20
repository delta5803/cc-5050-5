"""默认语料与测试样本。

训练语料覆盖：连写词、带附加符号的基字、上下文才触发的替代形、字距。
预留样本：训练语料中从未整句出现的组合，用来检验两种裁剪方案的差异。
"""

DEFAULT_CORPUS = [
    {"text": "office", "note": "liga：ffi 连写"},
    {"text": "fluff", "note": "liga：fl 连写"},
    {"text": "café", "note": "ccmp/mark：e + 组合尖音符"},
    {"text": "á̈", "note": "mkmk：叠加附加符号"},
    {"text": "AVATAR", "note": "kern：AV 字距"},
    {"text": "سلام", "note": "init/medi/fina/rlig：阿拉伯文上下文形"},
    {"text": "שלום", "note": "hebr：从右向左书写"},
]

DEFAULT_HELDOUT = [
    {"text": "file", "note": "预留组合：语料中未整词出现，需要 fi 连字（语料只触发过 ffi/fl/ff）"},
    {"text": "مسلم", "note": "预留组合：字母都在语料里，但触发未出现过的上下文形"},
]

# 默认启用的排版特性
DEFAULT_FEATURES = [
    "ccmp", "locl", "rlig", "liga",
    "init", "medi", "fina",
    "kern", "mark", "mkmk",
]
