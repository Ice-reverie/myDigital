"""Small, local lexical retriever for reviewed SERVICE documents, not diagnoses.

Chinese bigram TF-IDF retrieval; no embedding/Chroma claims and no network calls.
Only .md files directly below the configured directory are read. File names and
chunk IDs, not arbitrary model-provided paths, identify citations.
"""
from collections import Counter
import math
from pathlib import Path
import re


def tokens(text):
    parts = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", text.lower())
    return [word[i:i+2] for word in parts for i in range(max(1,len(word)-1))] 


class KnowledgeIndex:
    def __init__(self, directory: Path):
        self.chunks = []
        for path in sorted(Path(directory).glob("*.md"))[:50]:
            if path.is_symlink() or path.stat().st_size > 100000:
                continue
            text = path.read_text(encoding="utf-8-sig")
            title = text.splitlines()[0].lstrip("# ") if text else path.stem
            for index, start in enumerate(range(0, len(text), 450)):
                chunk = text[start:start+500].strip()
                if chunk:
                    self.chunks.append({"source_id":f"{path.name}#chunk-{index+1}",
                                        "title":title, "text":chunk, "terms":Counter(tokens(chunk))})
        self.df = Counter(t for c in self.chunks for t in c["terms"])

    def search(self, query, limit=3):
        query_terms = set(tokens(query))
        n = len(self.chunks)
        ranked = []
        for chunk in self.chunks:
            overlap = query_terms & chunk["terms"].keys()
            if not overlap:
                continue
            score = sum((1+math.log(chunk["terms"][t])) * math.log(1+n/(1+self.df[t])) for t in overlap)
            score /= math.sqrt(max(1,sum(chunk["terms"].values())))
            if score >= .035:
                ranked.append((score,chunk))
        ranked.sort(key=lambda item:(-item[0],item[1]["source_id"]))
        return [{k:v for k,v in c.items() if k!='terms'} | {"score":round(s,4)} for s,c in ranked[:limit]]
