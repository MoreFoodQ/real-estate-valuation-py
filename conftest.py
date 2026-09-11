import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 只把專案根目錄放上 path：`parser` / `api` 以套件名 import。
# kernel 仍由 `kernel/conftest.py` 自己把 `kernel/` 放上 path（提供 `src`），
# 兩邊不重疊，才不會出現兩個同名 `src` 互相蓋掉。
sys.path.insert(0, str(ROOT))
