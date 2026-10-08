import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["video", "reference", "analysis", "prompt", "motion", "edit", "output"]
Provider = Literal["openrouter", "fal", "replicate", "gpu", "custom", "local"]


class NodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Kind
    label: str = Field(min_length=1, max_length=120)
    provider: Provider
    model: str = Field(max_length=300)
    prompt: str = Field(default="", max_length=20000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    seed: str = Field(default="", max_length=20)
    resolution: Literal["480p", "580p", "720p", "1080p"] = "720p"
    endpoint: str | None = Field(default=None, max_length=500)
    assetName: str | None = Field(default=None, max_length=300)
    assetType: str | None = Field(default=None, max_length=100)
    assetId: str | None = Field(default=None, max_length=36)
    providerInput: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def safe_fields(self):
        if len(json.dumps(self.providerInput, allow_nan=False)) > 10000 or any(
            k.lower() in {"api_key", "authorization", "headers", "token", "secret"}
            for k in self.providerInput
        ):
            raise ValueError(
                "Provider input is too large or contains credential fields"
            )
        if not self.label.strip():
            raise ValueError("Node name must not be blank")
        return self


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    type: Literal["studio"] = "studio"
    position: dict[str, float]
    data: NodeData

    @model_validator(mode="after")
    def position_valid(self):
        if set(self.position) != {"x", "y"} or not all(
            math.isfinite(v) for v in self.position.values()
        ):
            raise ValueError("Invalid position")
        return self


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    type: Literal["smoothstep"] = "smoothstep"


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=120)
    nodes: list[Node] = Field(max_length=100)
    edges: list[Edge] = Field(max_length=300)

    @model_validator(mode="after")
    def valid_graph(self):
        if not self.title.strip():
            raise ValueError("Title must not be blank")
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("Duplicate node ID")
        if len({e.id for e in self.edges}) != len(self.edges):
            raise ValueError("Duplicate edge ID")
        pairs = set()
        by_id = {n.id: n for n in self.nodes}
        for e in self.edges:
            if (
                e.source not in ids
                or e.target not in ids
                or e.source == e.target
                or (e.source, e.target) in pairs
            ):
                raise ValueError("Invalid or duplicate connection")
            if by_id[e.source].data.kind == "output" or by_id[e.target].data.kind in {
                "video",
                "reference",
            }:
                raise ValueError("Invalid port direction")
            pairs.add((e.source, e.target))
        if len(self.ordered()) != len(self.nodes):
            raise ValueError("Cyclic workflow")
        return self

    def ordered(self):
        counts = {n.id: sum(e.target == n.id for e in self.edges) for n in self.nodes}
        ready = [n for n in self.nodes if counts[n.id] == 0]
        result = []
        while ready:
            n = ready.pop(0)
            result.append(n)
            for e in self.edges:
                if e.source == n.id:
                    counts[e.target] -= 1
                    if counts[e.target] == 0:
                        ready.append(next(x for x in self.nodes if x.id == e.target))
        return result


class SaveWorkflow(BaseModel):
    graph: Graph
    revision: int = Field(ge=0)


class SubmitJob(BaseModel):
    revision: int = Field(ge=1)
    request_key: str = Field(min_length=8, max_length=100)
    confirm_paid: bool = False


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class UserCreate(Login):
    password: str = Field(min_length=12, max_length=200)


class KeyInput(BaseModel):
    endpoint: str = Field(default="", max_length=500)
    key: str = Field(min_length=8, max_length=4096)


class Reconcile(BaseModel):
    node_id: str
    provider_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


class CloseReview(BaseModel):
    confirm_external_resolved: Literal[True]
    reason: str = Field(min_length=8, max_length=1000)
