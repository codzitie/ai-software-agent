
"""Meaning-based code search using local embeddings and Pinecone Cloud.

Chunks repository files, embeds them locally, and searches by similarity.

Each repository gets its own Pinecone namespace.
A manifest vector stores the repository fingerprint.
When files change, only that repository's namespace is rebuilt.

If Pinecone or the embedding model is unavailable, search returns [].
"""

import hashlib
import time
from pathlib import Path

from config import settings
from src.tools import filesystem
from src.tools.models import Hit
from src.utils.logging import get_logger

log = get_logger("semantic_search")

INDEXABLE = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb",
    ".php", ".c", ".cpp", ".h", ".cs", ".md", ".txt", ".json", ".yaml",
    ".yml", ".toml", ".html", ".css", ".sql", ".sh",
}

_embedder = None
_pinecone_index = None

MANIFEST_ID = "__repository_manifest__"


def _embedding_model():
    """Load the local Sentence Transformer model lazily."""
    global _embedder

    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(settings.EMBEDDING_MODEL)

    return _embedder


def _embed(texts: list[str]) -> list[list[float]]:
    """Generate normalized embeddings locally."""
    model = _embedding_model()

    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    return vectors.tolist()


def _get_index():
    """Connect to Pinecone and create the index if necessary."""
    global _pinecone_index

    if _pinecone_index is not None:
        return _pinecone_index

    if not settings.PINECONE_API_KEY:
        raise ValueError("PINECONE_API_KEY is not configured")

    from pinecone import Pinecone, ServerlessSpec

    pc = Pinecone(api_key=settings.PINECONE_API_KEY)

    index_name = settings.PINECONE_INDEX_NAME

    if index_name not in pc.list_indexes().names():
        log.info("Creating Pinecone index: %s", index_name)

        pc.create_index(
            name=index_name,
            dimension=settings.EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=settings.PINECONE_CLOUD,
                region=settings.PINECONE_REGION,
            ),
        )

    # Wait until the index is ready.
    deadline = time.monotonic() + 120

    while not pc.describe_index(index_name).status["ready"]:
        if time.monotonic() > deadline:
            raise TimeoutError("Pinecone index did not become ready")

        time.sleep(1)

    _pinecone_index = pc.Index(index_name)

    return _pinecone_index


def _files(base: Path) -> list[str]:
    """Find indexable files in the repository."""
    out = []

    for rel in filesystem.iter_files(base):
        p = base / rel

        if (
            p.suffix.lower() in INDEXABLE
            and p.stat().st_size <= settings.MAX_FILE_BYTES
        ):
            out.append(rel)

    return sorted(out)


def _fingerprint(base: Path, files: list[str]) -> str:
    """Calculate repository fingerprint."""
    h = hashlib.sha1()

    for rel in files:
        st = (base / rel).stat()

        h.update(
            f"{rel}:{st.st_size}:{st.st_mtime_ns}".encode()
        )

    return h.hexdigest()


def _namespace(base: Path) -> str:
    """Generate a stable namespace for each repository."""
    return "repo_" + hashlib.sha1(
        str(base).encode()
    ).hexdigest()[:20]


def _repository_is_indexed(index, namespace: str, fingerprint: str) -> bool:
    """Check the remote repository fingerprint."""
    result = index.fetch(
        ids=[MANIFEST_ID],
        namespace=namespace,
    )

    manifest = result.vectors.get(MANIFEST_ID)

    if manifest is None:
        return False

    metadata = manifest.metadata or {}

    return metadata.get("fingerprint") == fingerprint


def _index(index, base: Path, files: list[str], namespace: str,
           fingerprint: str) -> None:
    """Chunk files, generate embeddings and upload to Pinecone."""

    batch = []
    total = 0

    step = settings.CHUNK_LINES - settings.CHUNK_OVERLAP

    if step <= 0:
        raise ValueError("CHUNK_LINES must be greater than CHUNK_OVERLAP")

    for rel in files:
        try:
            lines = (base / rel).read_text(
                encoding="utf-8"
            ).splitlines()

        except (UnicodeDecodeError, OSError):
            continue

        for start in range(0, max(len(lines), 1), step):

            chunk = "\n".join(
                lines[start:start + settings.CHUNK_LINES]
            ).strip()

            if not chunk:
                continue

            document = f"{rel}\n{chunk}"

            batch.append({
                "id": f"{rel}:{start + 1}",
                "document": document,
                "metadata": {
                    "kind": "chunk",
                    "path": rel,
                    "line": start + 1,
                    "snippet": chunk.splitlines()[0][:300],
                },
            })

            total += 1

            if len(batch) >= 256:
                _upload_batch(index, batch, namespace)
                batch = []

            if total >= settings.MAX_INDEX_CHUNKS:
                log.warning(
                    "Index limit reached (%d chunks)",
                    total,
                )
                break

        if total >= settings.MAX_INDEX_CHUNKS:
            break

    if batch:
        _upload_batch(index, batch, namespace)

    # Store repository fingerprint separately from searchable chunks.
    # This also supports repositories with zero indexable chunks.
    index.upsert(
        vectors=[{
            "id": MANIFEST_ID,
            "values": [1.0] + [0.0] * (
                settings.EMBEDDING_DIMENSION - 1
            ),
            "metadata": {
                "kind": "manifest",
                "fingerprint": fingerprint,
            },
        }],
        namespace=namespace,
    )

    log.info(
        "Indexed %d chunks from %d files into namespace %s",
        total,
        len(files),
        namespace,
    )


def _upload_batch(index, batch: list[dict], namespace: str) -> None:
    """Embed and upload a batch of code chunks."""
    documents = [item["document"] for item in batch]

    embeddings = _embed(documents)

    vectors = []

    for item, embedding in zip(batch, embeddings):
        vectors.append({
            "id": item["id"],
            "values": embedding,
            "metadata": item["metadata"],
        })

    index.upsert(
        vectors=vectors,
        namespace=namespace,
    )

def _repository_index(root):
    """Get repository namespace, rebuilding when files change."""

    base = Path(root).resolve()

    files = _files(base)
    fingerprint = _fingerprint(base, files)

    namespace = _namespace(base)

    index = _get_index()

    # Check whether namespace already exists
    stats = index.describe_index_stats()
    namespaces = stats.namespaces or {}

    namespace_exists = namespace in namespaces

    # Check manifest only if namespace exists
    if namespace_exists:
        if _repository_is_indexed(index, namespace, fingerprint):
            return index, namespace

    log.info(
        "Repository changed. Rebuilding semantic index: %s",
        base,
    )

    # Delete only if namespace already exists
    if namespace_exists:
        index.delete(
            delete_all=True,
            namespace=namespace,
        )

    _index(
        index=index,
        base=base,
        files=files,
        namespace=namespace,
        fingerprint=fingerprint,
    )

    return index, namespace


def search(root, query: str, k: int = 5) -> list[Hit]:
    """Search repository code by semantic similarity."""

    if not query.strip() or k <= 0:
        return []

    try:
        index, namespace = _repository_index(root)

        query_embedding = _embed([query])[0]

        result = index.query(
            vector=query_embedding,
            top_k=k,
            namespace=namespace,
            include_metadata=True,
            filter={
                "kind": {"$eq": "chunk"}
            },
        )

    except Exception:
        log.exception(
            "Semantic search unavailable; continuing without it"
        )
        return []

    hits = []

    for match in result.matches:
        meta = match.metadata or {}

        if not meta.get("path"):
            continue

        hits.append(
            Hit(
                meta["path"],
                int(meta["line"]),
                meta.get("snippet", ""),
            )
        )

    return hits
