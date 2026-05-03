"""CRUX-MK monitor phase stubs for DF-89."""

from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import Request

from pydantic import BaseModel, Field

from .knowledge import KnowledgeStore


class Paper(BaseModel):
    """Pydantic DTO exchanged across the MAPE-K pipeline."""

    id: str
    title: str
    abstract: str = ""
    venue: str = ""
    authors: list[str] = Field(default_factory=list)
    citations: int = 0
    year: int = 0
    source_type: str = "stub"
    source_url: str = ""
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Monitor:
    """Builds deterministic paper stubs without making network calls."""

    def __init__(self, knowledge: KnowledgeStore | None = None) -> None:
        self.knowledge = knowledge

    def search_arxiv(self, query: str, max_results: int = 10) -> list[Paper]:
        """Pre: query is non-empty. Post: returns arXiv-shaped paper stubs."""
        return self._search_stub(
            query,
            max_results,
            "arxiv",
            "https://export.arxiv.org/api/query",
            {"search_query": query, "max_results": max_results},
        )

    def search_semantic_scholar(self, query: str, max_results: int = 10) -> list[Paper]:
        """Pre: query is non-empty. Post: returns Semantic Scholar-shaped paper stubs."""
        return self._search_stub(
            query,
            max_results,
            "semantic_scholar",
            "https://api.semanticscholar.org/graph/v1/paper/search",
            {"query": query, "limit": max_results},
        )

    def search_websearch(self, query: str) -> list[Paper]:
        """Pre: query is non-empty. Post: returns an empty list until WebSearch is wired."""
        if not query.strip():
            raise ValueError("query must not be blank")
        return []

    def collect(self, query: str, max_results: int = 3) -> list[Paper]:
        """Pre: query is non-empty. Post: returns and persists collected stubs."""
        papers = self.search_arxiv(query, max_results)
        papers += self.search_semantic_scholar(query, max_results)
        papers += self.search_websearch(query)
        if self.knowledge is not None:
            for paper in papers:
                self.knowledge.add_paper(paper)
        return papers

    def _search_stub(
        self,
        query: str,
        max_results: int,
        source_type: str,
        base_url: str,
        params: dict[str, str | int],
    ) -> list[Paper]:
        """Pre: query is non-empty. Post: returns deterministic paper stubs."""
        if not query.strip():
            raise ValueError("query must not be blank")
        request = Request(f"{base_url}?{urlencode(params)}")
        safe_query = "-".join(query.lower().split())
        papers: list[Paper] = []
        for index in range(min(max_results, 3)):
            papers.append(
                Paper(
                    id=f"{source_type}:{safe_query}:{index}",
                    title=f"{query} method benchmark {index}",
                    abstract=f"TODO integrate real response parsing for {request.full_url}",
                    venue="arXiv" if source_type == "arxiv" else "Semantic Scholar",
                    authors=[f"Author {index}", f"{source_type} team"],
                    citations=20 * (index + 1),
                    year=2024 - index,
                    source_type=source_type,
                    source_url=f"{request.full_url}&offset={index}",
                )
            )
        return papers
