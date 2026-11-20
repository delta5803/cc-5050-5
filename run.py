#!/usr/bin/env python3
"""启动字体子集排版工作台。"""
import sys

from workbench.server import run

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8370
    run(port=port)
