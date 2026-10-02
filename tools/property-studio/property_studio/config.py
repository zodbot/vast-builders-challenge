from dataclasses import dataclass
from pathlib import Path
import os


@dataclass
class Settings:
    data_dir: Path
    token: str
    cosmos_url: str
    cosmos_model: str
    gpu_token: str
    llm_url: str
    llm_key: str
    llm_model: str
    llm_project: str
    search_key: str
    s3_bucket: str
    s3_prefix: str
    node_bin: str
    artifact_module: str

    @classmethod
    def load(cls):
        bucket = os.getenv("PROPERTY_S3_BUCKET", "")
        if bucket and bucket in {os.getenv("S3_CHUNKS_BUCKET"), os.getenv("S3_SEGMENTS_BUCKET")}:
            raise ValueError("PROPERTY_S3_BUCKET must be an approved application bucket, not a watched ingest bucket")
        return cls(Path(os.getenv("PROPERTY_DATA_DIR", ".property-data")).resolve(),
                   os.getenv("PROPERTY_APP_TOKEN", ""), os.getenv("COSMOS3_REASON_URL", "").rstrip("/"),
                   os.getenv("COSMOS3_REASON_MODEL", ""), os.getenv("GPU_BEARER_TOKEN", ""),
                   os.getenv("PROPERTY_LLM_BASE_URL", "https://api.inference.wandb.ai/v1").rstrip("/"),
                   os.getenv("WANDB_API_KEY", ""), os.getenv("PROPERTY_LLM_MODEL", ""),
                   "/".join(filter(None, [os.getenv("WANDB_TEAM"), os.getenv("WANDB_PROJECT")])),
                   os.getenv("BRAVE_SEARCH_API_KEY", ""), bucket,
                   os.getenv("PROPERTY_S3_PREFIX", "property-studio"), os.getenv("PROPERTY_NODE_BIN", "node"),
                   os.getenv("PROPERTY_ARTIFACT_MODULE", "@oai/artifact-tool"))

    def capabilities(self):
        return {"cosmos": bool(self.cosmos_url), "language_model": bool(self.llm_key and self.llm_model),
                "web_search": bool(self.search_key), "vast_s3": bool(self.s3_bucket),
                # openpyxl is a required dependency and provides the portable fallback.
                "workbook": True, "authentication": bool(self.token),
                "note": "Configured does not mean live-verified."}
