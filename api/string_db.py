"""
STRING database integration module for BioSearch.
Provides functionality to query and visualize protein-protein interaction networks.
"""

import aiohttp
import logging
from typing import List, Dict, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# STRING API base URL
STRING_BASE_URL = "https://string-db.org/api"
STRING_NETWORK_URL = "https://string-db.org/cgi/network.pl"

# Common species codes
SPECIES_CODES = {
    "human": "9606",
    "mouse": "10090",
    "rat": "10116",
    "yeast": "4932",
    "e.coli": "83333",
    "auto-detect": "auto"
}

async def get_network_url(
    identifiers: List[str],
    species: str = "human",
    network_type: str = "full",
    required_score: float = 0.4
) -> str:
    """
    Generate a STRING network visualization URL.
    
    Args:
        identifiers: List of protein/gene identifiers
        species: Species name or code (default: "human")
        network_type: Type of network ("full" or "physical")
        required_score: Minimum interaction score (0.15-0.9)
    
    Returns:
        URL for the STRING network visualization
    """
    species_code = SPECIES_CODES.get(species.lower(), "9606")
    identifiers_str = "%0D".join(identifiers)
    
    params = {
        "identifiers": identifiers_str,
        "species": species_code,
        "network_type": network_type,
        "required_score": str(required_score)
    }
    
    query_string = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"{STRING_NETWORK_URL}?{query_string}"

async def search_string(
    session: aiohttp.ClientSession,
    query: str,
    species: str = "human",
    limit: int = 10
) -> List[Dict]:
    """
    Search STRING database for proteins/genes.
    
    Args:
        session: aiohttp ClientSession
        query: Search query
        species: Species name or code
        limit: Maximum number of results
    
    Returns:
        List of matching proteins/genes
    """
    species_code = SPECIES_CODES.get(species.lower(), "9606")
    
    params = {
        "identifier": query,
        "species": species_code,
        "limit": str(limit),
        "format": "json"
    }
    
    url = f"{STRING_BASE_URL}/json/resolve"
    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.json()
        else:
            logger.error(f"STRING API error: {response.status}")
            return []

async def get_interactions(
    session: aiohttp.ClientSession,
    identifiers: List[str],
    species: str = "human"
) -> Dict:
    """
    Get protein-protein interactions from STRING.
    
    Args:
        session: aiohttp ClientSession
        identifiers: List of protein/gene identifiers
        species: Species name or code
    
    Returns:
        Dictionary containing interaction data
    """
    species_code = SPECIES_CODES.get(species.lower(), "9606")
    
    params = {
        "identifiers": "%0D".join(identifiers),
        "species": species_code,
        "format": "json"
    }
    
    url = f"{STRING_BASE_URL}/json/interactions"
    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.json()
        else:
            logger.error(f"STRING API error: {response.status}")
            return {} 