from typing import List, Optional
from pydantic import BaseModel, Field

class Episode(BaseModel):
    number: int
    title: str
    playerUrl: str = ""
    downloadPageUrl: str = ""
    directDownloadUrl: Optional[str] = None
    subtitleUrl: Optional[str] = None
    version: str = "VOSTFR"
    synopsis: Optional[str] = None

class AnimeResult(BaseModel):
    id: str
    title: str
    imageUrl: str = ""
    url: str
    version: str = ""
    type: str = "Anime"
    episodeInfo: str = ""

class AnimeDetail(BaseModel):
    title: str
    originalTitle: Optional[str] = None
    synopsis: Optional[str] = None
    imageUrl: str = ""
    version: str = ""
    studio: Optional[str] = None
    url: str
    genres: List[str] = Field(default_factory=list)
    directors: List[str] = Field(default_factory=list)
    actors: List[str] = Field(default_factory=list)
    episodes: List[Episode] = Field(default_factory=list)
