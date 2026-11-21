from app.errors import DomainError


def decode(source):
    if not source.content:
        raise DomainError("EMPTY_FILE", file=source.name)
    encodings = ("utf-8-sig",) if source.content.startswith(b"\xef\xbb\xbf") else ("utf-8", "gb18030")
    for encoding in encodings:
        try:
            return source.content.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            if encoding == encodings[-1]:
                line = source.content[:exc.start].count(b"\n") + 1
                raise DomainError("BAD_ENCODING", file=source.name, line=line) from exc
