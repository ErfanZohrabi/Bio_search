"""
STITCH database integration module for BioSearch.
Provides functionality to query and visualize drug-target interaction networks.
"""

import aiohttp
import logging
from typing import List, Dict, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# STITCH API base URL
STITCH_BASE_URL = "https://stitch.embl.de/api"
STITCH_NETWORK_URL = "https://stitch.embl.de/cgi/network.pl"

async def get_drug_network_url(
    identifiers: List[str],
    species: str = "human",
    network_type: str = "full",
    required_score: float = 0.4
) -> str:
    """
    Generate a STITCH network visualization URL for drugs.
    
    Args:
        identifiers: List of drug identifiers
        species: Species name or code (default: "human")
        network_type: Type of network ("full" or "physical")
        required_score: Minimum interaction score (0.15-0.9)
    
    Returns:
        URL for the STITCH network visualization
    """
    species_code = "9606" if species.lower() == "human" else "auto"
    identifiers_str = "%0D".join(identifiers)
    
    params = {
        "identifiers": identifiers_str,
        "species": species_code,
        "network_type": network_type,
        "required_score": str(required_score)
    }
    
    query_string = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"{STITCH_NETWORK_URL}?{query_string}"

async def search_stitch(
    session: aiohttp.ClientSession,
    query: str,
    species: str = "human",
    limit: int = 10
) -> List[Dict]:
    """
    Search STITCH database for drugs.
    
    Args:
        session: aiohttp ClientSession
        query: Search query
        species: Species name or code
        limit: Maximum number of results
    
    Returns:
        List of matching drugs
    """
    species_code = "9606" if species.lower() == "human" else "auto"
    
    params = {
        "identifier": query,
        "species": species_code,
        "limit": str(limit),
        "format": "json"
    }
    
    url = f"{STITCH_BASE_URL}/json/resolve"
    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.json()
        else:
            logger.error(f"STITCH API error: {response.status}")
            return []

async def get_drug_interactions(
    session: aiohttp.ClientSession,
    identifiers: List[str],
    species: str = "human"
) -> Dict:
    """
    Get drug-target interactions from STITCH.
    
    Args:
        session: aiohttp ClientSession
        identifiers: List of drug identifiers
        species: Species name or code
    
    Returns:
        Dictionary containing interaction data
    """
    species_code = "9606" if species.lower() == "human" else "auto"
    
    params = {
        "identifiers": "%0D".join(identifiers),
        "species": species_code,
        "format": "json"
    }
    
    url = f"{STITCH_BASE_URL}/json/interactions"
    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.json()
        else:
            logger.error(f"STITCH API error: {response.status}")
            return {} 