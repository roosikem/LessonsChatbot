"""Index versions: <data_dir>/index/<version>/ plus a CURRENT file naming the live one.

The local folder is always the working copy. With STORAGE=s3 the versions and the
CURRENT pointer are mirrored to S3: publishing uploads the version first and moves the
pointer last; readers check the pointer every few seconds and download a new version
before switching to it. That's how several containers (e.g. Fargate tasks, whose disks
don't survive a restart) share one index.
"""
import json
import os
import shutil
import threading
import time
from pathlib import Path

import numpy as np

INDEX_FILES = ("meta.json", "lessons.jsonl", "context_items.jsonl", "vectors.npy", "mapping.json")


class S3Remote:
    def __init__(self, client, bucket, prefix, poll_seconds=30):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.poll_seconds = poll_seconds
        self.checked_at = 0.0
        self.lock = threading.Lock()

    def key(self, *parts):
        return "/".join([self.prefix, *parts]) if self.prefix else "/".join(parts)

    def put_file(self, path, *key_parts):
        self.client.upload_file(str(path), self.bucket, self.key(*key_parts))

    def put_bytes(self, data, *key_parts):
        self.client.put_object(Bucket=self.bucket, Key=self.key(*key_parts), Body=data)

    def get_file(self, path, *key_parts):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, self.key(*key_parts), str(path))

    def list_keys(self, *prefix_parts, start_after=None):
        keys, token = [], None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": self.key(*prefix_parts) + "/"}
            if start_after:
                kwargs["StartAfter"] = start_after  # keys are date/time ordered: only the new ones
            if token:
                kwargs["ContinuationToken"] = token
            page = self.client.list_objects_v2(**kwargs)
            keys += [o["Key"] for o in page.get("Contents", [])]
            token = page.get("NextContinuationToken")
            if not token:
                return keys

    def get_bytes_by_key(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def pointer(self):
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self.key("index", "CURRENT"))["Body"].read()
            return body.decode().strip() or None
        except self.client.exceptions.NoSuchKey:
            return None


class IndexStore:
    def __init__(self, data_dir, remote=None):
        self.root = Path(data_dir) / "index"
        self.remote = remote

    # --- pointer ---------------------------------------------------------

    def _local_pointer(self):
        pointer = self.root / "CURRENT"
        return pointer.read_text().strip() if pointer.exists() else None

    def _set_local_pointer(self, version):
        # write then rename, so readers never see a half-written pointer
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"CURRENT.{os.getpid()}.tmp"
        tmp.write_text(version)
        os.replace(tmp, self.root / "CURRENT")

    def current_version(self):
        if self.remote:
            self._sync()
        return self._local_pointer()

    def _sync(self, force=False):
        """Follow the S3 pointer: download a new version, then switch to it locally."""
        remote = self.remote
        if not force and time.monotonic() - remote.checked_at < remote.poll_seconds:
            return
        with remote.lock:
            remote.checked_at = time.monotonic()
            version = remote.pointer()
            if not version or version == self._local_pointer():
                return
            folder = self.root / version
            if not (folder / "meta.json").exists():
                part = self.root / f"{version}.download"
                for leftover in (part, folder):  # from an earlier, interrupted download
                    if leftover.exists():
                        shutil.rmtree(leftover)
                for name in INDEX_FILES:
                    try:
                        remote.get_file(part / name, "index", version, name)
                    except Exception:
                        if name in ("meta.json", "lessons.jsonl", "vectors.npy"):
                            raise
                os.replace(part, folder)
            self._set_local_pointer(version)

    # --- versions --------------------------------------------------------

    def new_version_dir(self, version):
        folder = self.root / version
        folder.mkdir(parents=True)
        return folder

    def publish(self, version):
        if self.remote:
            for path in sorted((self.root / version).iterdir()):
                self.remote.put_file(path, "index", version, path.name)
            self.remote.put_bytes(version.encode(), "index", "CURRENT")  # the pointer moves last
            self.remote.checked_at = time.monotonic()
        self._set_local_pointer(version)

    def current_folder(self):
        version = self.current_version()
        if version is None:
            raise FileNotFoundError(f"no index in {self.root}; run ingest first")
        return self.root / version

    def read_current(self):
        """meta, lesson dicts, context item dicts, vectors and mapping (or None) of the live index."""
        folder = self.current_folder()
        items = folder / "context_items.jsonl"
        mapping = folder / "mapping.json"
        return {
            "meta": json.loads((folder / "meta.json").read_text()),
            "lessons": read_jsonl(folder / "lessons.jsonl"),
            "items": read_jsonl(items) if items.exists() else [],
            "vectors": np.load(folder / "vectors.npy"),
            "mapping": json.loads(mapping.read_text()) if mapping.exists() else None,
        }

    def current_mapping(self):
        if self.current_version() is None:
            return None
        path = self.current_folder() / "mapping.json"
        return json.loads(path.read_text()) if path.exists() else None

    def current_meta(self):
        if self.current_version() is None:
            return None
        return json.loads((self.current_folder() / "meta.json").read_text())


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


_remotes = {}


def store_for(settings):
    """The index store for these settings, with the S3 mirror when STORAGE=s3."""
    if settings.storage != "s3":
        return IndexStore(settings.data_dir)
    key = (settings.s3_endpoint_url, settings.s3_bucket, settings.s3_prefix)
    if key not in _remotes:  # one remote per bucket/prefix, so all callers share the poll timer
        _remotes[key] = S3Remote(s3_client(settings), settings.s3_bucket, settings.s3_prefix,
                                 settings.index_poll_seconds)
    return IndexStore(settings.data_dir, _remotes[key])


def s3_client(settings):
    import boto3
    session = boto3.Session(profile_name=settings.s3_aws_profile or None, region_name=settings.s3_region)
    kwargs = {"endpoint_url": settings.s3_endpoint_url or None}
    if settings.s3_access_key:  # only for a local S3 stand-in (moto); on AWS use the task role
        kwargs.update(aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key)
    return session.client("s3", **kwargs)


def as_store(target):
    """Accept an IndexStore or a plain data folder (local only)."""
    return target if isinstance(target, IndexStore) else IndexStore(target)
