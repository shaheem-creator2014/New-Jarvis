"""Read-only knowledge indexing. Document text is data, never instructions."""
import os
import importlib.util
import io
import multiprocessing
import stat
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from .data import DataSource

MAX_FILE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {".git", "node_modules"}
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

def _pdf_worker(raw, connection):
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024,512*1024*1024))
            resource.setrlimit(resource.RLIMIT_CPU, (6,6))
        except ImportError:
            pass  # Windows uses the parent timeout; no Unix resource module exists.
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw),strict=True)
        if reader.is_encrypted or len(reader.pages)>100:
            raise ValueError('Encrypted PDF or more than 100 pages')
        parts=[]
        total=0
        for number,page in enumerate(reader.pages,1):
            text=page.extract_text() or ''
            total+=len(text)
            if total>200000:
                raise ValueError('Extracted text exceeds 200000 characters')
            parts.append(f'[PDF page {number}]\n'+text)
        connection.send(('ok','\n'.join(parts)))
    except Exception:
        connection.send(('error','PDF extraction failed or exceeded safe limits'))
    finally:
        connection.close()


def extract_pdf(raw):
    if not raw.startswith(b'%PDF-'):
        raise ValueError('Invalid PDF signature')
    if importlib.util.find_spec('pypdf') is None:
        raise ValueError('Optional pypdf extractor is not installed; installation needs approval')
    context=multiprocessing.get_context('spawn')
    receive,send=context.Pipe(duplex=False)
    process=context.Process(target=_pdf_worker,args=(raw,send),daemon=True)
    try:
        process.start()
        send.close()
        if not receive.poll(8):
            raise ValueError('PDF extraction exceeded eight seconds')
        try:
            status,text=receive.recv()
        except EOFError as error:
            raise ValueError('PDF extractor stopped without a result') from error
        if status!='ok':
            raise ValueError(text)
        return text
    finally:
        receive.close()
        send.close()
        if process.is_alive():
            process.terminate()
        if process.pid is not None:
            process.join(timeout=1)


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    kind: str
    text: str

class KnowledgeIndex:
    def __init__(self, source: DataSource):
        self.source = source
        self.documents = {}
        self.edges = set()
        self.skipped = []
        self.warnings = []

    def build(self):
        self.documents.clear()
        self.edges.clear()
        self.skipped.clear()
        self.warnings.clear()
        root = self.source.root
        if root.is_symlink() or getattr(root,"is_junction",lambda:False)():
            raise PermissionError("Knowledge root must not be a symbolic link")
        root = root.resolve()
        if not root.is_dir():
            self.warnings.append("Knowledge directory does not exist; no files read")
            return self
        def walk_error(error):
            self.warnings.append(f"Cannot enumerate directory: {error.filename}")
        for folder, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                              and not (Path(folder) / d).is_symlink()
                              and not getattr(Path(folder) / d, "is_junction", lambda: False)())
            for name in sorted(names):
                path = Path(folder) / name
                relative = path.relative_to(root).as_posix()
                try:
                    if path.is_symlink() or getattr(path,"is_junction",lambda:False)() or not path.resolve().is_relative_to(root):
                        self.skipped.append((relative, "symbolic link or outside root"))
                        continue
                    if path.suffix.lower() not in {".txt", ".md", ".pdf"}:
                        self.skipped.append((relative, "unsupported format"))
                        continue
                    if path.stat().st_size > MAX_FILE_BYTES:
                        self.skipped.append((relative, "larger than 2 MB"))
                        continue
                    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
                    with os.fdopen(descriptor,'rb') as stream:
                        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                            raise ValueError('Not a regular file')
                        raw=stream.read(MAX_FILE_BYTES+1)
                    if len(raw)>MAX_FILE_BYTES:
                        self.skipped.append((relative,"larger than 2 MB"))
                        continue
                    if path.suffix.lower()=='.pdf':
                        text=extract_pdf(raw)
                        self.documents[relative]=Document(relative,path.stem,'pdf',text)
                        continue
                    if b"\x00" in raw:
                        self.skipped.append((relative, "oversized or binary file"))
                        continue
                    text = raw.decode("utf-8-sig")
                    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                        self.skipped.append((relative, "binary control characters"))
                        continue
                    self.documents[relative] = Document(relative, path.stem, path.suffix.lower()[1:], text)
                except (OSError, UnicodeError, ValueError) as error:
                    self.skipped.append((relative, str(error) if isinstance(error,ValueError) and not isinstance(error,UnicodeError) else type(error).__name__))
        aliases = defaultdict(set)
        for key, doc in self.documents.items():
            for alias in {key.casefold(), str(Path(key).with_suffix("")).casefold(), doc.title.casefold()}:
                aliases[alias].add(key)
        for key, doc in self.documents.items():
            for target in WIKILINK.findall(doc.text):
                target = target.split("|", 1)[0].split("#", 1)[0].strip().replace("\\", "/")
                candidates = aliases.get(target.casefold(), set())
                local = (Path(key).parent / target).as_posix().casefold()
                if len(candidates) != 1:
                    candidates = aliases.get(local, set())
                if len(candidates) == 1:
                    other = next(iter(candidates))
                    if other != key:
                        self.edges.add(tuple(sorted((key, other))))
        return self

    def neighbors(self):
        graph = {key: set() for key in self.documents}
        for a, b in self.edges:
            graph[a].add(b)
            graph[b].add(a)
        return graph

    def hubs(self, limit=10):
        return sorted(((key, len(links)) for key, links in self.neighbors().items()),
                      key=lambda item: (-item[1], item[0]))[:limit]

    def search(self, query, limit=10):
        terms = re.findall(r"\w+", query.casefold())
        if not terms:
            return []
        results = []
        for key, doc in self.documents.items():
            if not all(term in (key + " " + doc.text).casefold() for term in terms):
                continue
            lines = [(i, line) for i, line in enumerate(doc.text.splitlines(), 1)
                     if any(term in line.casefold() for term in terms)]
            line_no, snippet = lines[0] if lines else (1, doc.text[:240])
            score = sum(doc.text.casefold().count(term) + 3 * key.casefold().count(term) for term in terms)
            results.append({"filename": key, "line": line_no, "citation": f"{key}:{line_no}",
                            "snippet": snippet[:240], "score": score})
        return sorted(results, key=lambda row: (-row["score"], row["filename"]))[:max(0, min(limit, 100))]

    def shortest_path(self, start, end):
        graph = self.neighbors()
        if start not in graph or end not in graph:
            return []
        queue = deque([start])
        previous = {start: None}
        while queue:
            current = queue.popleft()
            if current == end:
                path = []
                while current is not None:
                    path.append(current)
                    current = previous[current]
                return path[::-1]
            for neighbor in sorted(graph[current]):
                if neighbor not in previous:
                    previous[neighbor] = current
                    queue.append(neighbor)
        return []
