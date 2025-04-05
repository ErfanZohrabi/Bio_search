"""
Ensembl API Module for BioSearch Application

This module provides functions for interacting with the Ensembl API.
"""

import logging
import aiohttp
import json
from typing import Dict, List, Any, Optional
from .db_config import ENSEMBL_CONFIG
from .cache import cached
from .models import Gene

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import SSL context
from .db_helpers import ssl_context

@cached(ttl=3600, key_prefix="ensembl")
async def search_ensembl(session: aiohttp.ClientSession, query: str, species: str = "human", limit: int = 10) -> Dict[str, Any]:
    """
    Search for genes in Ensembl database.
    
    Args:
        session: aiohttp client session
        query: Search term (gene symbol or name)
        species: Species name (default: human)
        limit: Maximum number of results to return
        
    Returns:
        Dictionary with search results
    """
    try:
        # First try to search by gene symbol
        gene_data = await search_ensembl_by_symbol(session, query, species)
        
        # If no results, try a text search
        if not gene_data or "error" in gene_data:
            gene_data = await search_ensembl_by_text(session, query, species, limit)
        
        return gene_data
    
    except Exception as e:
        logger.error(f"Error in search_ensembl: {str(e)}")
        return {"error": str(e)}

@cached(ttl=3600, key_prefix="ensembl_symbol")
async def search_ensembl_by_symbol(session: aiohttp.ClientSession, symbol: str, species: str = "human") -> Dict[str, Any]:
    """
    Search for a gene by symbol in Ensembl.
    
    Args:
        session: aiohttp client session
        symbol: Gene symbol
        species: Species name (default: human)
        
    Returns:
        Dictionary with gene information
    """
    try:
        # Map species name to Ensembl species code
        species_map = {
            "human": "homo_sapiens",
            "mouse": "mus_musculus",
            "rat": "rattus_norvegicus",
            "zebrafish": "danio_rerio",
            "fly": "drosophila_melanogaster",
            "worm": "caenorhabditis_elegans",
            "yeast": "saccharomyces_cerevisiae"
        }
        
        species_code = species_map.get(species.lower(), "homo_sapiens")
        
        # Format the URL for Ensembl lookup by symbol
        lookup_url = f"{ENSEMBL_CONFIG.base_url}/lookup/symbol/{species_code}/{symbol}"
        params = {
            "expand": 1
        }
        
        async with session.get(lookup_url, params=params, ssl=ssl_context) as response:
            if response.status != 200:
                # 404 likely means gene not found, which is not an error
                if response.status == 404:
                    logger.info(f"Gene symbol '{symbol}' not found in Ensembl")
                    return {"error": "Gene not found"}
                else:
                    logger.error(f"Ensembl lookup error: {response.status} for symbol '{symbol}'")
                    return {"error": f"Ensembl API error: {response.status}"}
            
            data = await response.json()
            
            # Format the result into a standard structure
            gene_info = await format_ensembl_gene(data, species_code)
            
            # Get additional information about the gene
            if "id" in data:
                gene_id = data["id"]
                
                # Get phenotype information
                phenotypes = await get_ensembl_gene_phenotypes(session, gene_id, species_code)
                if phenotypes and "error" not in phenotypes:
                    gene_info["phenotypes"] = phenotypes
                
                # Get homologues
                homologues = await get_ensembl_gene_homologues(session, gene_id, species_code)
                if homologues and "error" not in homologues:
                    gene_info["homologues"] = homologues
            
            return {"results": [gene_info]}
    
    except Exception as e:
        logger.error(f"Error in search_ensembl_by_symbol: {str(e)}")
        return {"error": str(e)}

@cached(ttl=3600, key_prefix="ensembl_text")
async def search_ensembl_by_text(session: aiohttp.ClientSession, query: str, species: str = "human", limit: int = 10) -> Dict[str, Any]:
    """
    Search for genes by text in Ensembl.
    
    Args:
        session: aiohttp client session
        query: Search term
        species: Species name (default: human)
        limit: Maximum number of results to return
        
    Returns:
        Dictionary with search results
    """
    try:
        # Map species name to Ensembl species code
        species_map = {
            "human": "homo_sapiens",
            "mouse": "mus_musculus",
            "rat": "rattus_norvegicus",
            "zebrafish": "danio_rerio",
            "fly": "drosophila_melanogaster",
            "worm": "caenorhabditis_elegans",
            "yeast": "saccharomyces_cerevisiae"
        }
        
        species_code = species_map.get(species.lower(), "homo_sapiens")
        
        # Format the URL for Ensembl search
        search_url = f"{ENSEMBL_CONFIG.base_url}/search/genes/{species_code}"
        params = {
            "q": query,
            "limit": limit
        }
        
        async with session.get(search_url, params=params, ssl=ssl_context) as response:
            if response.status != 200:
                logger.error(f"Ensembl search error: {response.status} for query '{query}'")
                return {"error": f"Ensembl API error: {response.status}"}
            
            data = await response.json()
            
            results = []
            if "genes" in data and isinstance(data["genes"], list):
                for gene in data["genes"]:
                    gene_info = await format_ensembl_gene(gene, species_code)
                    results.append(gene_info)
            
            return {"results": results}
    
    except Exception as e:
        logger.error(f"Error in search_ensembl_by_text: {str(e)}")
        return {"error": str(e)}

@cached(ttl=86400, key_prefix="ensembl_gene_phenotypes")  # Cache for 24 hours
async def get_ensembl_gene_phenotypes(session: aiohttp.ClientSession, gene_id: str, species: str) -> List[Dict[str, Any]]:
    """
    Get phenotypes associated with a gene.
    
    Args:
        session: aiohttp client session
        gene_id: Ensembl gene ID
        species: Ensembl species code
        
    Returns:
        List of phenotypes
    """
    try:
        # Format the URL for phenotypes
        phenotypes_url = f"{ENSEMBL_CONFIG.base_url}/phenotypes/gene/{species}/{gene_id}"
        
        async with session.get(phenotypes_url, ssl=ssl_context) as response:
            if response.status != 200:
                if response.status == 404:
                    return []  # No phenotypes found
                logger.error(f"Ensembl phenotypes error: {response.status} for gene '{gene_id}'")
                return {"error": f"Ensembl API error: {response.status}"}
            
            data = await response.json()
            
            phenotypes = []
            for item in data:
                phenotype = {
                    "term": item.get("phenotype_name", ""),
                    "description": item.get("description", ""),
                    "source": item.get("source", {}).get("name", ""),
                    "attributes": {}
                }
                
                if "attributes" in item:
                    for attr in item["attributes"]:
                        phenotype["attributes"][attr["type"]] = attr["value"]
                
                phenotypes.append(phenotype)
            
            return phenotypes
    
    except Exception as e:
        logger.error(f"Error in get_ensembl_gene_phenotypes: {str(e)}")
        return {"error": str(e)}

@cached(ttl=86400, key_prefix="ensembl_gene_homologues")  # Cache for 24 hours
async def get_ensembl_gene_homologues(session: aiohttp.ClientSession, gene_id: str, species: str) -> List[Dict[str, Any]]:
    """
    Get homologues of a gene in other species.
    
    Args:
        session: aiohttp client session
        gene_id: Ensembl gene ID
        species: Ensembl species code
        
    Returns:
        List of homologues
    """
    try:
        # Format the URL for homologues
        homologues_url = f"{ENSEMBL_CONFIG.base_url}/homology/id/{gene_id}"
        params = {
            "type": "orthologues",
            "target_species": "human,mouse,rat,zebrafish"
        }
        
        async with session.get(homologues_url, params=params, ssl=ssl_context) as response:
            if response.status != 200:
                if response.status == 404:
                    return []  # No homologues found
                logger.error(f"Ensembl homologues error: {response.status} for gene '{gene_id}'")
                return {"error": f"Ensembl API error: {response.status}"}
            
            data = await response.json()
            
            homologues = []
            if "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    if "homologies" in item and isinstance(item["homologies"], list):
                        for homology in item["homologies"]:
                            if "target" in homology:
                                target = homology["target"]
                                homologue = {
                                    "id": target.get("id", ""),
                                    "species": target.get("species", ""),
                                    "display_id": target.get("display_id", ""),
                                    "description": target.get("description", ""),
                                    "homology_type": homology.get("type", ""),
                                    "similarity": homology.get("target_identity", "")
                                }
                                homologues.append(homologue)
            
            return homologues
    
    except Exception as e:
        logger.error(f"Error in get_ensembl_gene_homologues: {str(e)}")
        return {"error": str(e)}

async def format_ensembl_gene(gene_data: Dict[str, Any], species: str) -> Dict[str, Any]:
    """
    Format Ensembl gene data into a standardized structure.
    
    Args:
        gene_data: Raw gene data from Ensembl
        species: Ensembl species code
        
    Returns:
        Formatted gene data
    """
    # Create a basic gene info structure
    gene_info = {
        "id": gene_data.get("id", ""),
        "name": gene_data.get("display_name", gene_data.get("name", "")),
        "description": gene_data.get("description", ""),
        "biotype": gene_data.get("biotype", ""),
        "chromosome": gene_data.get("seq_region_name", ""),
        "start": gene_data.get("start", 0),
        "end": gene_data.get("end", 0),
        "strand": gene_data.get("strand", 0),
        "source": "Ensembl",
        "url": f"https://ensembl.org/{species}/Gene/Summary?g={gene_data.get('id', '')}",
        "version": gene_data.get("version", 0),
        "synonyms": gene_data.get("synonyms", []),
        "external_names": {}
    }
    
    # Extract external references
    if "external_name" in gene_data:
        gene_info["external_names"]["external_name"] = gene_data["external_name"]
    
    # Extract additional identifiers
    if "xrefs" in gene_data and isinstance(gene_data["xrefs"], list):
        for xref in gene_data["xrefs"]:
            db_name = xref.get("dbname", "")
            primary_id = xref.get("primary_id", "")
            if db_name and primary_id:
                gene_info["external_names"][db_name] = primary_id
    
    return gene_info

async def format_ensembl_results(data: Dict[str, Any]) -> List[Gene]:
    """
    Format Ensembl search results into Gene models.
    
    Args:
        data: Raw Ensembl API response
        
    Returns:
        List of Gene objects
    """
    genes = []
    
    if "error" in data:
        logger.error(f"Error in Ensembl results: {data['error']}")
        return genes
    
    results = data.get("results", [])
    
    for result in results:
        # Create Gene object
        gene = Gene(
            id=result.get("id", ""),
            name=result.get("name", "Unknown Gene"),
            source_db="Ensembl",
            url=result.get("url", ""),
            organism=result.get("species", "human"),
            symbol=result.get("name", ""),
            aliases=result.get("synonyms", []),
            description=result.get("description", ""),
            location=f"{result.get('chromosome', '')}:{result.get('start', '')}-{result.get('end', '')}"
        )
        
        # Add external references to metadata
        if "external_names" in result:
            gene.metadata["external_references"] = result["external_names"]
        
        # Add phenotypes if available
        if "phenotypes" in result:
            gene.metadata["phenotypes"] = result["phenotypes"]
        
        # Add homologues if available
        if "homologues" in result:
            gene.metadata["homologues"] = result["homologues"]
        
        genes.append(gene)
    
    return genes 