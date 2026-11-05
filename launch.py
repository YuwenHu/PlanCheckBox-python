"""双击即启动（开发态，需要本机 Python）。打包后直接双击 PlanCheckBox.exe。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.main import main  # noqa: E402

raise SystemExit(main())
