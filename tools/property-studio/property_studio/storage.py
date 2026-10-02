"""Atomic, versioned manifests. No user-supplied paths are accepted."""
import json
import os
import re
import threading
from pathlib import Path
from .models import Run, now


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def folder(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run ID")
        p = self.root / run_id
        p.mkdir(exist_ok=True)
        return p

    def save(self, run: Run):
        with self.lock:
            run.updated_at = now()
            folder = self.folder(run.id)
            raw = run.model_dump_json(indent=2)
            tmp = folder / "manifest.tmp"
            tmp.write_text(raw)
            os.replace(tmp, folder / "manifest.json")
            history = folder / "versions"
            history.mkdir(exist_ok=True)
            (history / f"{run.version}.json").write_text(raw)

    def get(self, run_id):
        p = self.folder(run_id) / "manifest.json"
        if not p.exists():
            raise FileNotFoundError("Run not found")
        return Run.model_validate_json(p.read_text())

    def list(self):
        rows = []
        for p in self.root.glob("*/manifest.json"):
            try:
                r = Run.model_validate_json(p.read_text())
                rows.append({"id": r.id, "address": r.property.address, "state": r.state,
                             "created_at": r.created_at, "mode": r.request.mode})
            except (ValueError, OSError):
                continue
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    def recover(self):
        for row in self.list():
            run = self.get(row["id"])
            if run.state in {"running", "pending"}:
                run.state = "interrupted"
                for stage in run.stages.values():
                    if stage["state"] == "running":
                        stage["state"] = "interrupted"
                self.save(run)

    def sync(self, run):
        if not self.settings.s3_bucket:
            return "Local persistence; VAST storage is not configured."
        import boto3
        client = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"],
                              aws_access_key_id=os.environ["ACCESS_KEY"],
                              aws_secret_access_key=os.environ["SECRET_KEY"])
        folder = self.folder(run.id)
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix != ".tmp":
                key = f"{self.settings.s3_prefix}/{run.id}/{path.relative_to(folder)}"
                client.upload_file(str(path), self.settings.s3_bucket, key)
        return "Artifacts copied to the configured VAST application bucket."
