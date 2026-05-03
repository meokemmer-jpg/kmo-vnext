"""CRUX-MK command-line interface for DF-89."""
import argparse
from pathlib import Path
from df_89.config import DFConfig
from df_89.engine import MAPEKEngine
from df_89.knowledge import KnowledgeStore

def build_parser() -> argparse.ArgumentParser:
    """Pre: none. Post: parser with run/status/list-canon/dump-knowledge returned."""
    p = argparse.ArgumentParser(prog="python -m df_89"); sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run"); run.add_argument("--topic", required=True); run.add_argument("--config")
    sub.add_parser("status"); sub.add_parser("list-canon"); sub.add_parser("dump-knowledge"); return p
def load_config(path: str | None, topic: str | None = None) -> DFConfig:
    """Pre: optional path points to JSON. Post: validated config returned."""
    cfg = DFConfig.from_json_file(Path(path)) if path else DFConfig()
    return cfg.model_copy(update={"topic": topic}) if topic else cfg
def main(argv: list[str] | None = None) -> int:
    """Pre: argv CLI-compatible. Post: command executed and code returned."""
    a = build_parser().parse_args(argv); cfg = load_config(getattr(a, "config", None), getattr(a, "topic", None)); k = KnowledgeStore(cfg.state_dir / "knowledge.sqlite")
    if a.command == "run": print(MAPEKEngine(cfg, k).run_once(cfg.topic))
    elif a.command == "list-canon": print(k.list_canonical())
    elif a.command == "dump-knowledge": print({"db": str(k.db_path)})
    else: print({"status": "ok", "df_id": cfg.df_id})
    return 0
if __name__ == "__main__": raise SystemExit(main())
