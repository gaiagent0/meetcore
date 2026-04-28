import sys
from pathlib import Path

# backend/app elérhetővé tétele a teszteknek
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
