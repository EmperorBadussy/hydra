"""
╔══════════════════════════════════════════════════════════════════╗
║  HYDRA — Base Service Module                                     ║
║  All service plugins inherit from this base class                ║
║                                                                    ║
║  Each head of the HYDRA implements:                               ║
║  - search(query) → results                                       ║
║  - get_info(url) → metadata                                      ║
║  - download(url, output_dir, quality) → file_path                ║
║  - validate() → bool (health check)                              ║
╚══════════════════════════════════════════════════════════════════╝
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import os


# Module metadata — every service plugin must define MODULE_INFO
@dataclass
class ModuleInfo:
    name: str               # e.g. "Netflix"
    slug: str               # e.g. "netflix" (used for folder naming)
    version: str            # e.g. "1.0.0"
    description: str        # Short description
    author: str             # Who wrote/maintains this module
    min_hydra_version: str  # Minimum HYDRA core version required
    requires: list = field(default_factory=list)  # pip packages needed
    icon: str = ""          # Emoji or icon identifier


@dataclass
class MediaItem:
    """Represents a searchable/downloadable media item."""
    id: str
    title: str
    media_type: str         # "movie", "episode", "series", "season"
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    series_title: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[int] = None  # seconds
    image_url: Optional[str] = None
    quality: Optional[str] = None
    url: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class DownloadProgress:
    """Progress update during download."""
    percent: float          # 0-100
    speed: str = ""         # e.g. "2.5 MB/s"
    eta: str = ""           # e.g. "01:23"
    message: str = ""       # Current status message
    downloaded_bytes: int = 0
    total_bytes: int = 0


class BaseService(ABC):
    """
    Base class for all HYDRA service modules (heads).

    Each streaming service plugin must implement this interface.
    The self-healing system can hot-swap these modules at runtime.
    """

    @abstractmethod
    def get_info(self) -> ModuleInfo:
        """Return module metadata."""
        pass

    @abstractmethod
    def validate(self) -> dict:
        """
        Health check. Return dict with:
        - valid: bool
        - message: str (error message if not valid)
        - missing_deps: list (missing pip packages)
        """
        pass

    @abstractmethod
    def search(self, query: str, media_type: str = "all", limit: int = 20) -> list:
        """
        Search the service catalog.
        Returns list of MediaItem dicts.
        """
        pass

    @abstractmethod
    def get_metadata(self, url: str) -> dict:
        """
        Get detailed metadata for a URL.
        Returns MediaItem dict with full details.
        """
        pass

    @abstractmethod
    def download(self, url: str, output_dir: str, quality: str = "best",
                 progress_callback=None) -> dict:
        """
        Download content from URL.

        Args:
            url: Service URL or content ID
            output_dir: Where to save files
            quality: Quality preference ("best", "1080p", "720p", etc.)
            progress_callback: Function(DownloadProgress) called with updates

        Returns:
            dict with: status, file_path, file_size, message
        """
        pass

    def get_available_qualities(self) -> list:
        """Return list of available quality options for this service."""
        return ["best", "1080p", "720p", "480p"]

    def requires_auth(self) -> bool:
        """Whether this service requires authentication."""
        return True

    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        return False

    def authenticate(self, credentials: dict) -> dict:
        """
        Authenticate with the service.
        Returns dict with: success, message, user
        """
        return {"success": False, "message": "Not implemented"}

    def get_url_patterns(self) -> list:
        """
        Return URL patterns this service handles.
        Used for auto-detecting which service to use from a URL.
        e.g. ["netflix.com", "www.netflix.com"]
        """
        return []
