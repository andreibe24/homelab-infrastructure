import hashlib
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


BASE_URL = os.environ["OPEN_WEBUI_URL"].rstrip("/")
API_KEY = os.environ["OPEN_WEBUI_API_KEY"]
KNOWLEDGE_BASE_NAME = os.environ["RAG_KNOWLEDGE_BASE_NAME"]
DOCUMENTS_DIR = Path("/documents")


def api_request(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": "Bearer " + API_KEY}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            content = response.read()
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"Open WebUI API returned HTTP {error.code}: {detail}") from None
    return json.loads(content) if content else None


def get_or_create_knowledge_base():
    page = 1
    seen = 0
    while True:
        result = api_request("GET", f"/api/v1/knowledge/?{urlencode({'page': page})}")
        items = result.get("items", [])
        for item in items:
            if item.get("name") == KNOWLEDGE_BASE_NAME:
                return item["id"]
        seen += len(items)
        if not items or seen >= result.get("total", seen):
            break
        page += 1
    knowledge = api_request(
        "POST",
        "/api/v1/knowledge/create",
        {
            "name": KNOWLEDGE_BASE_NAME,
            "description": "Documents synced from apps/openwebui/rag/documents in homelab-infrastructure.",
        },
    )
    return knowledge["id"]


def get_manifest():
    files = sorted(path for path in DOCUMENTS_DIR.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError("No RAG documents found; refusing to sync an empty document set.")
    manifest = []
    source_files = {}
    for path in files:
        relative_path = path.relative_to(DOCUMENTS_DIR)
        if relative_path.parent != Path("."):
            raise RuntimeError("RAG documents must be in the documents directory root.")
        content = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        key = ("", path.name)
        manifest.append(
            {
                "filename": path.name,
                "path": "",
                "checksum": checksum,
                "size": len(content),
            }
        )
        source_files[key] = (path, content, checksum)
    return manifest, source_files


def upload_file(path, content, checksum):
    boundary = f"----rag-sync-{uuid.uuid4().hex}"
    filename = path.name
    if any(character in filename for character in '\r\n"'):
        raise RuntimeError(f"Unsupported document filename: {filename!r}")
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    metadata = json.dumps({"file_hash": checksum})
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="metadata"\r\n\r\n',
            metadata.encode(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = Request(
        f"{BASE_URL}/api/v1/files/?process=true&process_in_background=false",
        data=body,
        headers={
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read())["id"]
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"Open WebUI file upload returned HTTP {error.code}: {detail}") from None


def main():
    knowledge_id = quote(get_or_create_knowledge_base(), safe="")
    manifest, source_files = get_manifest()
    diff = api_request(
        "POST",
        f"/api/v1/knowledge/{knowledge_id}/sync/diff",
        {"manifest": manifest},
    )
    uploaded = []
    for entry in diff["added"] + diff["modified"]:
        path, content, checksum = source_files[(entry["path"], entry["filename"])]
        uploaded.append(
            {
                "file_id": upload_file(path, content, checksum),
                "directory_id": diff["directory_map"].get(entry["path"]),
            }
        )

    stale_file_ids = [entry["file_id"] for entry in diff["deleted"]]
    stale_file_ids.extend(entry["stale_file_id"] for entry in diff["modified"])
    if stale_file_ids or diff["rmdir"]:
        api_request(
            "POST",
            f"/api/v1/knowledge/{knowledge_id}/sync/cleanup",
            {"file_ids": stale_file_ids, "dir_ids": diff["rmdir"]},
        )

    for entry in uploaded:
        api_request(
            "POST",
            f"/api/v1/knowledge/{knowledge_id}/file/add",
            {
                "file_id": entry["file_id"],
                "directory_id": entry["directory_id"],
            },
        )

    print(
        f"RAG sync complete: {len(diff['added'])} added, "
        f"{len(diff['modified'])} modified, {len(diff['deleted'])} deleted, "
        f"{diff['unmodified_count']} unchanged."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"RAG sync failed: {error}", file=sys.stderr)
        sys.exit(1)
