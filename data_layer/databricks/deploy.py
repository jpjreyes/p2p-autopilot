"""Deploy the daily job to Databricks: upload the task scripts and the dbt project to the workspace, make sure the
checkpoint volume exists, and create or update the job from job.json (the job lives in the repo, not in the UI).

Usage: python data_layer/databricks/deploy.py [--run-now]   (profile `p2p` in ~/.databrickscfg; no charge on Free Edition)
"""

import argparse
import io
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ImportFormat

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ROOT = "/Workspace/Shared/p2p-autopilot"
WAREHOUSE = "Serverless Starter Warehouse"


def upload(w: WorkspaceClient, src: Path, dst: str) -> None:
    w.workspace.mkdirs(str(Path(dst).parent))
    w.workspace.upload(dst, io.BytesIO(src.read_bytes()), format=ImportFormat.AUTO, overwrite=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-now", action="store_true")
    a = ap.parse_args()
    w = WorkspaceClient(profile="p2p")
    for f in ("arrive.py", "ingest.py", "score.py", "drift.py", "brief.py"):
        upload(w, HERE / f, f"{ROOT}/pipeline/{f}")
    dbt = REPO / "dbt"
    n = 0
    for f in dbt.rglob("*"):
        rel = f.relative_to(dbt)
        if f.is_file() and rel.parts[0] not in ("target", "logs") and f.name not in ("profiles.yml", ".user.yml"):
            upload(w, f, f"{ROOT}/dbt/{rel}")
            n += 1
    if "checkpoints" not in [v.name for v in w.volumes.list(catalog_name="workspace", schema_name="p2p_autopilot_raw")]:
        w.api_client.do("POST", "/api/2.1/unity-catalog/volumes", body={
            "catalog_name": "workspace", "schema_name": "p2p_autopilot_raw", "name": "checkpoints",
            "volume_type": "MANAGED"})
    warehouse = next(x.id for x in w.warehouses.list() if x.name == WAREHOUSE)
    spec = (HERE / "job.json").read_text().replace("${ROOT}", ROOT).replace("${WAREHOUSE_ID}", warehouse) \
        .replace("${NOTIFY_EMAIL}", w.current_user.me().user_name)
    spec = json.loads(spec)
    existing = [j for j in w.jobs.list(name=spec["name"])]
    if existing:
        job_id = existing[0].job_id
        w.api_client.do("POST", "/api/2.2/jobs/reset", body={"job_id": job_id, "new_settings": spec})
    else:
        job_id = w.api_client.do("POST", "/api/2.2/jobs/create", body=spec)["job_id"]
    print(f"uploaded 5 task scripts + {n} dbt files; job {spec['name']} id {job_id}")
    if a.run_now:
        run = w.api_client.do("POST", "/api/2.2/jobs/run-now", body={"job_id": job_id})
        print(f"run started: {run['run_id']}")


if __name__ == "__main__":
    main()
