"""
Database Helper Functions for BioSearch Application

This module contains helper functions for interacting with various biological databases APIs.
"""
import aiohttp
import asyncio
import json
import logging
import ssl
import time
import random
import os
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create a custom SSL context that doesn't verify certificates (for development only)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Environment variables and settings
env_mock_mode = os.environ.get('BIOSEARCH_MOCK_MODE', 'false').lower()
MOCK_MODE = env_mock_mode in ('true', '1', 't', 'yes')

# FORCE DISABLE MOCK MODE FOR DEBUGGING
MOCK_MODE = False

logger.info(f"Environment BIOSEARCH_MOCK_MODE value: '{env_mock_mode}'")
logger.info(f"Mock mode: {'ENABLED' if MOCK_MODE else 'DISABLED'}")

# NCBI API settings
NCBI_API_KEY = os.environ.get('NCBI_API_KEY')
if NCBI_API_KEY:
    logger.info(f"NCBI API key is configured: {NCBI_API_KEY[:4]}...{NCBI_API_KEY[-4:]}")
else:
    logger.warning(f"NCBI API key not found in environment variables")

# Rate limiting retry settings
MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds

# Mock data for testing without API access
MOCK_DATA = {
    'ncbi_gene': {
        'id_list': ['7157', '672', '675'],
        'summary_data': {
            'result': {
                '7157': {
                    'name': 'TP53',
                    'description': 'tumor protein p53',
                    'organism': {'scientificname': 'Homo sapiens'},
                    'chromosome': '17',
                    'genomicinfo': []
                },
                '672': {
                    'name': 'BRCA1',
                    'description': 'BRCA1 DNA repair associated',
                    'organism': {'scientificname': 'Homo sapiens'},
                    'chromosome': '17',
                    'genomicinfo': []
                },
                '675': {
                    'name': 'BRCA2',
                    'description': 'BRCA2 DNA repair associated',
                    'organism': {'scientificname': 'Homo sapiens'},
                    'chromosome': '13',
                    'genomicinfo': []
                }
            }
        }
    },
    'ncbi_pubmed': {
        'id_list': ['34528509', '34529953', '34530140'],
        'summary_data': {
            'result': {
                '34528509': {
                    'title': 'TP53 mutations and survival in osteosarcoma patients: a meta-analysis of published data',
                    'authors': [{'name': 'Chen Z'}, {'name': 'Guo J'}, {'name': 'Zhang K'}],
                    'fulljournalname': 'Disease Markers',
                    'pubdate': '2021 Sep 23',
                    'abstract': 'TP53 mutations have been reported to be associated with survival in patients with osteosarcoma, but the results remain controversial.'
                },
                '34529953': {
                    'title': 'Revisiting the role of p53 in cancer',
                    'authors': [{'name': 'Lee D'}, {'name': 'Kim H'}, {'name': 'Park J'}],
                    'fulljournalname': 'Journal of Biomedical Science',
                    'pubdate': '2021 Aug 16',
                    'abstract': 'The p53 protein plays a crucial role in tumor suppression by regulating cell cycle arrest, apoptosis, senescence, and DNA repair.'
                },
                '34530140': {
                    'title': 'Targeting p53 for cancer therapy',
                    'authors': [{'name': 'Wang X'}, {'name': 'Zhang Y'}, {'name': 'Liu S'}],
                    'fulljournalname': 'Cancer Research',
                    'pubdate': '2021 Jul 28',
                    'abstract': 'Given the high frequency of p53 inactivation in human cancers, reactivation of p53 is an attractive strategy for cancer therapy.'
                }
            }
        }
    },
    'uniprot': {
        'results': [
            {
                'primaryAccession': 'P04637',
                'proteinDescription': {
                    'recommendedName': {
                        'fullName': {'value': 'Cellular tumor antigen p53'}
                    }
                },
                'genes': [{'value': 'TP53'}],
                'organism': {'scientificName': 'Homo sapiens'},
                'sequence': {'length': 393}
            },
            {
                'primaryAccession': 'P38398',
                'proteinDescription': {
                    'recommendedName': {
                        'fullName': {'value': 'Breast cancer type 1 susceptibility protein'}
                    }
                },
                'genes': [{'value': 'BRCA1'}],
                'organism': {'scientificName': 'Homo sapiens'},
                'sequence': {'length': 1863}
            },
            {
                'primaryAccession': 'P51587',
                'proteinDescription': {
                    'recommendedName': {
                        'fullName': {'value': 'Breast cancer type 2 susceptibility protein'}
                    }
                },
                'genes': [{'value': 'BRCA2'}],
                'organism': {'scientificName': 'Homo sapiens'},
                'sequence': {'length': 3418}
            }
        ]
    },
    'drugbank': {
        'results': [
            {
                'cid': '2244',
                'name': 'Aspirin',
                'formula': 'C9H8O4',
                'synonyms': ['Acetylsalicylic acid', 'ASA', '2-Acetoxybenzoic acid'],
                'description': 'A non-steroidal anti-inflammatory drug (NSAID) with analgesic, antipyretic, and antiplatelet properties.',
                'url': 'https://pubchem.ncbi.nlm.nih.gov/compound/2244'
            },
            {
                'cid': '3672',
                'name': 'Ibuprofen',
                'formula': 'C13H18O2',
                'synonyms': ['(RS)-2-(4-(2-methylpropyl)phenyl)propanoic acid', 'IBU', 'Brufen'],
                'description': 'A non-steroidal anti-inflammatory drug (NSAID) with analgesic and antipyretic properties.',
                'url': 'https://pubchem.ncbi.nlm.nih.gov/compound/3672'
            },
            {
                'cid': '1983',
                'name': 'Paracetamol',
                'formula': 'C8H9NO2',
                'synonyms': ['Acetaminophen', 'APAP', 'N-(4-hydroxyphenyl)acetamide'],
                'description': 'A mild analgesic and antipyretic drug commonly used for the relief of mild to moderate pain and fever.',
                'url': 'https://pubchem.ncbi.nlm.nih.gov/compound/1983'
            }
        ]
    }
}

async def retry_with_backoff(func, *args, **kwargs):
    """
    Retry a function with exponential backoff when rate limited.
    
    Args:
        func: Async function to retry
        *args: Positional arguments for the function
        **kwargs: Keyword arguments for the function
        
    Returns:
        The result of the function call
    """
    retries = 0
    last_exception = None
    
    while retries < MAX_RETRIES:
        try:
            return await func(*args, **kwargs)
        except aiohttp.ClientResponseError as e:
            if e.status == 429:  # Too Many Requests
                wait_time = INITIAL_BACKOFF * (2 ** retries) + random.uniform(0, 1)
                logger.warning(f"Rate limited (429). Retrying in {wait_time:.2f} seconds...")
                await asyncio.sleep(wait_time)
                retries += 1
                last_exception = e
            else:
                raise e
    
    # If we've exhausted all retries
    logger.error(f"Max retries ({MAX_RETRIES}) reached. Giving up.")
    raise last_exception if last_exception else RuntimeError("Max retries reached")

async def search_ncbi(session, db, term, retmax=10):
    """
    Search NCBI databases (Gene, Protein, PubMed, etc.)
    
    Args:
        session (aiohttp.ClientSession): Session object for HTTP requests
        db (str): NCBI database to search (gene, protein, pubmed, etc.)
        term (str): Search term
        retmax (int): Maximum number of results to return
        
    Returns:
        dict: Search results containing IDs and summary data
    """
    # If mock mode is enabled, return mock data
    if MOCK_MODE:
        logger.info(f"Using mock data for NCBI {db} search")
        # Choose the appropriate mock data based on the database
        if db == 'gene':
            # Filter mock data if needed based on term
            if 'tp53' in term.lower():
                return {'id_list': ['7157'], 'summary_data': {'result': {'7157': MOCK_DATA['ncbi_gene']['summary_data']['result']['7157']}}}
            elif 'brca' in term.lower():
                return {'id_list': ['672', '675'], 'summary_data': {'result': {
                    '672': MOCK_DATA['ncbi_gene']['summary_data']['result']['672'],
                    '675': MOCK_DATA['ncbi_gene']['summary_data']['result']['675']
                }}}
            return MOCK_DATA['ncbi_gene']
        elif db == 'pubmed':
            # Filter mock data if needed based on term
            if 'tp53' in term.lower() or 'p53' in term.lower():
                return MOCK_DATA['ncbi_pubmed']
            return {'id_list': [], 'summary_data': {'result': {}}}
        return {'id_list': [], 'summary_data': {'result': {}}}
    
    logger.info(f"Searching NCBI {db} for '{term}' (real API call)")
    
    try:
        # Base URLs for NCBI E-utilities
        base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
        search_url = f'{base_url}esearch.fcgi'
        summary_url = f'{base_url}esummary.fcgi'
        
        # First search for IDs
        params = {
            'db': db,
            'term': term,
            'retmode': 'json',
            'retmax': retmax
        }
        
        # Add API key if available
        if NCBI_API_KEY:
            params['api_key'] = NCBI_API_KEY
            logger.info(f"Using NCBI API key for search: {NCBI_API_KEY[:4]}...{NCBI_API_KEY[-4:]}")
        else:
            # Add a delay to avoid rate limiting if no API key
            await asyncio.sleep(0.34)  # Ensures we don't exceed 3 requests per second
            logger.warning("No API key - using delay to avoid rate limits")
        
        # Debug log the request
        logger.info(f"NCBI API Request: GET {search_url} - params: {params}")
        
        async with session.get(search_url, params=params, ssl=ssl_context) as response:
            # Check for rate limiting
            if response.status == 429:
                logger.warning("NCBI rate limit exceeded. Implementing retry with backoff.")
                # Use retry with backoff for rate limited requests
                response.raise_for_status()  # This will trigger the retry mechanism
            
            if response.status != 200:
                logger.error(f"NCBI search error: {response.status} for term '{term}' in db '{db}'")
                return {'error': f"NCBI API error: {response.status}"}
            
            # Debug log the response
            logger.info(f"NCBI API Response: {response.status}")
            
            search_data = await response.json()
            
            if 'esearchresult' not in search_data or 'idlist' not in search_data['esearchresult']:
                logger.warning(f"No results found in NCBI for term '{term}' in db '{db}'")
                logger.debug(f"Response data: {search_data}")
                return []
            
            id_list = search_data['esearchresult'].get('idlist', [])
            if not id_list:
                logger.info(f"Empty ID list for term '{term}' in db '{db}'")
                return []
            
            logger.info(f"Found {len(id_list)} IDs for term '{term}' in db '{db}'")
            
            # Then get summaries for the IDs
            summary_params = {
                'db': db,
                'id': ','.join(id_list),
                'retmode': 'json'
            }
            
            # Add API key if available
            if NCBI_API_KEY:
                summary_params['api_key'] = NCBI_API_KEY
            else:
                # Add a small delay before the second request if no API key
                await asyncio.sleep(0.34)  # Ensures we don't exceed 3 requests per second
            
            # Debug log the summary request
            logger.info(f"NCBI Summary API Request: GET {summary_url} - params: {summary_params}")
            
            async with session.get(summary_url, params=summary_params, ssl=ssl_context) as summary_response:
                # Check for rate limiting again
                if summary_response.status == 429:
                    logger.warning("NCBI rate limit exceeded. Implementing retry with backoff.")
                    summary_response.raise_for_status()  # This will trigger the retry mechanism
                
                if summary_response.status != 200:
                    logger.error(f"NCBI summary error: {summary_response.status}")
                    return {'error': f"NCBI API error: {summary_response.status}"}
                
                # Debug log the summary response
                logger.info(f"NCBI Summary API Response: {summary_response.status}")
                
                summary_data = await summary_response.json()
                
                logger.info(f"Successfully retrieved summary data for {len(id_list)} IDs")
                
                return {
                    'id_list': id_list,
                    'summary_data': summary_data
                }
    
    except aiohttp.ClientResponseError as e:
        if e.status == 429:
            logger.error(f"Rate limit exceeded even after retries: {str(e)}")
        else:
            logger.error(f"Error in search_ncbi: {str(e)}")
        return {'error': str(e)}
    except Exception as e:
        logger.error(f"Error in search_ncbi: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': str(e)}

async def search_uniprot(session, query, size=10):
    """
    Search UniProt protein database
    
    Args:
        session (aiohttp.ClientSession): Session object for HTTP requests
        query (str): Search term
        size (int): Maximum number of results to return
        
    Returns:
        dict: Search results
    """
    # If mock mode is enabled, return mock data
    if MOCK_MODE:
        logger.info(f"Using mock data for UniProt search")
        # Filter mock data if needed based on query
        if 'tp53' in query.lower() or 'p53' in query.lower() or 'p04637' in query.lower():
            return {'results': [MOCK_DATA['uniprot']['results'][0]]}
        elif 'brca1' in query.lower():
            return {'results': [MOCK_DATA['uniprot']['results'][1]]}
        elif 'brca2' in query.lower():
            return {'results': [MOCK_DATA['uniprot']['results'][2]]}
        elif 'brca' in query.lower():
            return {'results': [MOCK_DATA['uniprot']['results'][1], MOCK_DATA['uniprot']['results'][2]]}
        return MOCK_DATA['uniprot']
    
    try:
        # UniProt REST API
        logger.info(f"Searching UniProt for '{query}' (real API call)")
        search_url = 'https://rest.uniprot.org/uniprotkb/search'
        
        params = {
            'query': query,
            'format': 'json',
            'size': size
        }
        
        logger.info(f"UniProt API Request: GET {search_url} - params: {params}")
        
        async with session.get(search_url, params=params, ssl=ssl_context) as response:
            logger.info(f"UniProt API Response: {response.status}")
            
            if response.status != 200:
                logger.error(f"UniProt search error: {response.status} for query '{query}'")
                return {'error': f"UniProt API error: {response.status}"}
            
            try:
                search_data = await response.json()
                logger.info(f"UniProt returned {len(search_data.get('results', []))} results")
                return search_data
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse UniProt response: {str(e)}")
                response_text = await response.text()
                logger.debug(f"Response content: {response_text[:500]}...")
                return {'error': 'Failed to parse UniProt response'}
    
    except aiohttp.ClientError as e:
        logger.error(f"Network error in search_uniprot: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': f"Network error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error in search_uniprot: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': str(e)}

async def search_drugbank(session, query, size=10):
    """
    Search DrugBank database for drug information
    
    Args:
        session (aiohttp.ClientSession): Session object for HTTP requests
        query (str): Search term (drug name, disease, target, etc.)
        size (int): Maximum number of results to return
        
    Returns:
        dict: Search results
    """
    # If mock mode is enabled, return mock data
    if MOCK_MODE:
        logger.info(f"Using mock data for DrugBank search")
        # Filter mock data if needed based on query
        if 'aspirin' in query.lower():
            return {'results': [MOCK_DATA['drugbank']['results'][0]]}
        elif 'ibuprofen' in query.lower():
            return {'results': [MOCK_DATA['drugbank']['results'][1]]}
        elif 'paracetamol' in query.lower() or 'acetaminophen' in query.lower():
            return {'results': [MOCK_DATA['drugbank']['results'][2]]}
        # For non-drug queries, return empty results
        if any(term in query.lower() for term in ['tp53', 'p53', 'brca']):
            return {'results': []}
        return MOCK_DATA['drugbank']
    
    try:
        logger.info(f"Searching DrugBank/PubChem for '{query}' (real API call)")
        
        # Since DrugBank doesn't have a public API, we use the PubChem API to get drug information
        # PubChem has data from DrugBank and serves as a good proxy
        search_url = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name'
        encoded_query = query.replace(' ', '%20')
        full_url = f"{search_url}/{encoded_query}/cids/JSON"
        
        logger.info(f"DrugBank/PubChem API Request: GET {full_url}")
        
        # First search for the compound by name
        async with session.get(full_url, ssl=ssl_context) as response:
            logger.info(f"DrugBank/PubChem API Response: {response.status}")
            
            search_data = None
            if response.status != 200:
                # If not found by exact name, try a more flexible search
                logger.info(f"Trying alternative search for '{query}'")
                search_url_alt = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name'
                alt_query = query.replace(' ', '%20')
                full_alt_url = f"{search_url_alt}/{alt_query}/cids/JSON?name_type=word"
                
                logger.info(f"DrugBank/PubChem Alternative API Request: GET {full_alt_url}")
                
                async with session.get(full_alt_url, ssl=ssl_context) as alt_response:
                    logger.info(f"DrugBank/PubChem Alternative API Response: {alt_response.status}")
                    
                    if alt_response.status != 200:
                        logger.error(f"DrugBank search error: {response.status} for query '{query}'")
                        return {'results': []}  # Return empty results instead of error
                    
                    try:
                        search_data = await alt_response.json()
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse DrugBank/PubChem alternative response")
                        return {'results': []}
            else:
                try:
                    search_data = await response.json()
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse DrugBank/PubChem response")
                    return {'results': []}
            
            if not search_data or 'IdentifierList' not in search_data or 'CID' not in search_data['IdentifierList']:
                logger.warning(f"No results found in DrugBank for query '{query}'")
                return {'results': []}
            
            cids = search_data['IdentifierList']['CID'][:size]  # Limit to size
            logger.info(f"Found {len(cids)} compounds for '{query}'")
            
            results = []
            
            # Get details for each compound
            for cid in cids:
                details_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/JSON"
                logger.info(f"Fetching details for compound {cid}")
                
                async with session.get(details_url, ssl=ssl_context) as details_response:
                    if details_response.status != 200:
                        logger.warning(f"Failed to get details for compound {cid}: {details_response.status}")
                        continue
                    
                    try:
                        details_data = await details_response.json()
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse compound details for {cid}")
                        continue
                    
                    if 'PC_Compounds' in details_data and len(details_data['PC_Compounds']) > 0:
                        compound = details_data['PC_Compounds'][0]
                        
                        # Mock a DrugBank-like structure
                        drug_data = {
                            'cid': cid,
                            'name': '',
                            'formula': '',
                            'synonyms': [],
                            'description': '',
                            'url': f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                            'source_db': 'DrugBank'  # Explicitly mark as DrugBank even though from PubChem
                        }
                        
                        # Extract compound name
                        if 'props' in compound:
                            for prop in compound['props']:
                                if prop['urn']['label'] == 'IUPAC Name':
                                    drug_data['name'] = prop['value']['sval']
                                elif prop['urn']['label'] == 'Molecular Formula':
                                    drug_data['formula'] = prop['value']['sval']
                        
                        # Extract synonyms
                        for key in compound.get('synonyms', {}):
                            if key == 'Depositor-Supplied Synonyms':
                                drug_data['synonyms'] = compound['synonyms'][key][:5]  # Limit to 5 synonyms
                                break
                        
                        results.append(drug_data)
            
            return {'results': results}
    
    except aiohttp.ClientError as e:
        logger.error(f"Network error in search_drugbank: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': f"Network error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error in search_drugbank: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': str(e)}

async def format_ncbi_gene_results(data):
    """
    Format NCBI Gene search results into a standardized format
    
    Args:
        data (dict): Raw search results from NCBI Gene database
        
    Returns:
        list: Formatted results
    """
    if 'error' in data:
        return data
    
    if not data or not isinstance(data, dict):
        return []
    
    try:
        id_list = data.get('id_list', [])
        summary_data = data.get('summary_data', {})
        
        if not summary_data or 'result' not in summary_data:
            return []
        
        results = []
        for uid in id_list:
            if uid in summary_data['result']:
                item = summary_data['result'][uid]
                
                # Sometimes the name is stored in different fields
                gene_name = item.get('description', '')
                gene_symbol = item.get('name', 'Unknown')
                
                results.append({
                    'id': uid,
                    'symbol': gene_symbol,  # Add gene symbol for display
                    'name': gene_name,
                    'description': item.get('description', ''),
                    'organism': item.get('organism', {}).get('scientificname', ''),
                    'genomic_info': {
                        'chromosome': item.get('chromosome', ''),
                        'genomic_ranges': item.get('genomicinfo', [])
                    },
                    'url': f"https://www.ncbi.nlm.nih.gov/gene/{uid}",
                    'type': 'gene'  # Add type for categorization
                })
        
        return results
    
    except Exception as e:
        logger.error(f"Error in format_ncbi_gene_results: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': str(e)}

async def format_pubmed_results(data):
    """
    Format PubMed search results into a standardized format
    
    Args:
        data (dict): Raw search results from PubMed database
        
    Returns:
        list: Formatted results
    """
    if 'error' in data:
        return data
    
    if not data or not isinstance(data, dict):
        return []
    
    try:
        id_list = data.get('id_list', [])
        summary_data = data.get('summary_data', {})
        
        if not summary_data or 'result' not in summary_data:
            return []
        
        results = []
        for uid in id_list:
            if uid in summary_data['result']:
                item = summary_data['result'][uid]
                
                # Extract authors
                authors = []
                if 'authors' in item:
                    for author in item.get('authors', []):
                        if 'name' in author:
                            authors.append(author['name'])
                
                # Extract year from pubdate
                year = ""
                if 'pubdate' in item:
                    # Try to extract year from pubdate (format varies)
                    pubdate = item['pubdate']
                    year_match = re.search(r'\d{4}', pubdate)
                    if year_match:
                        year = year_match.group(0)
                
                results.append({
                    'id': uid,
                    'title': item.get('title', 'Unknown'),
                    'authors': authors,
                    'journal': item.get('fulljournalname', ''),
                    'pubdate': item.get('pubdate', ''),
                    'year': year,
                    'abstract': item.get('abstract', ''),
                    'url': f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    'type': 'publication'  # Add type for categorization
                })
        
        return results
    
    except Exception as e:
        logger.error(f"Error in format_pubmed_results: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': str(e)}

async def format_uniprot_results(data):
    """
    Format UniProt search results into a standardized format
    
    Args:
        data (dict): Raw search results from UniProt database
        
    Returns:
        list: Formatted results
    """
    if 'error' in data:
        return data
    
    if not data or not isinstance(data, dict):
        logger.warning("UniProt returned empty or invalid data")
        return []
    
    try:
        logger.info(f"Formatting UniProt results: {str(data)[:100]}...")
        
        # New UniProt API structure handling
        results = []
        
        # Handle both old and new API response formats
        if 'results' in data:
            items = data.get('results', [])
        elif 'items' in data:  # handle alternative format
            items = data.get('items', [])
        else:
            logger.warning(f"Unexpected UniProt response structure: {list(data.keys())}")
            # Just use the data directly if we can't find expected keys
            items = data if isinstance(data, list) else []
        
        logger.info(f"Processing {len(items)} UniProt items")
        
        for item in items:
            try:
                # Extract primary accession - handle different formats
                if 'primaryAccession' in item:
                    accession = item.get('primaryAccession', '')
                elif 'accession' in item:
                    accession = item.get('accession', '')
                else:
                    accession = item.get('id', '')
                
                # Extract protein name - different possible locations
                protein_name = 'Unknown'
                # New API format (nested structure)
                if 'proteinDescription' in item:
                    protein_desc = item['proteinDescription']
                    if 'recommendedName' in protein_desc and 'fullName' in protein_desc['recommendedName']:
                        protein_name = protein_desc['recommendedName']['fullName'].get('value', 'Unknown')
                # Simple format
                elif 'protein_name' in item:
                    protein_name = item.get('protein_name', 'Unknown')
                elif 'name' in item:
                    protein_name = item.get('name', 'Unknown')
                
                # Extract gene information - different possible formats
                genes = []
                if 'genes' in item:
                    for gene in item.get('genes', []):
                        if isinstance(gene, dict) and 'value' in gene:
                            genes.append(gene['value'])
                        elif isinstance(gene, str):
                            genes.append(gene)
                elif 'gene' in item:
                    gene_value = item.get('gene', '')
                    if gene_value:
                        genes.append(gene_value)
                
                # Get organism - different possible locations
                organism = ''
                if 'organism' in item:
                    org = item['organism']
                    if isinstance(org, dict):
                        organism = org.get('scientificName', '')
                    elif isinstance(org, str):
                        organism = org
                elif 'taxonomy' in item:
                    organism = item.get('taxonomy', {}).get('name', '')
                
                # Get sequence length - handle different formats
                sequence_length = 0
                if 'sequence' in item:
                    seq = item['sequence']
                    if isinstance(seq, dict) and 'length' in seq:
                        try:
                            sequence_length = int(seq['length'])
                        except (ValueError, TypeError):
                            sequence_length = 0
                    elif isinstance(seq, str):
                        sequence_length = len(seq)
                elif 'length' in item:
                    try:
                        sequence_length = int(item['length'])
                    except (ValueError, TypeError):
                        sequence_length = 0
                
                results.append({
                    'id': accession,
                    'name': protein_name,
                    'gene': ', '.join(genes) if genes else '',
                    'organism': organism,
                    'length': sequence_length,
                    'url': f"https://www.uniprot.org/uniprotkb/{accession}/entry",
                    'type': 'protein'
                })
                
                logger.info(f"Processed UniProt entry: {accession} - {protein_name}")
                
            except Exception as e:
                logger.error(f"Error processing UniProt item: {str(e)}")
                logger.debug(f"Problematic item: {str(item)[:200]}...")
        
        logger.info(f"Returning {len(results)} formatted UniProt results")
        return results
    
    except Exception as e:
        logger.error(f"Error in format_uniprot_results: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': str(e)}

async def format_drugbank_results(data):
    """
    Format DrugBank search results into a standardized format
    
    Args:
        data (dict): Raw search results from DrugBank database
        
    Returns:
        list: Formatted results
    """
    if 'error' in data:
        return data
    
    if not data or not isinstance(data, dict) or 'results' not in data:
        return []
    
    try:
        results = []
        for item in data.get('results', []):
            drug_name = item.get('name', 'Unknown Drug')
            if not drug_name or drug_name == '':
                # Use first synonym as name if IUPAC name is not available
                if item.get('synonyms') and len(item['synonyms']) > 0:
                    drug_name = item['synonyms'][0]
                    # Remove the first synonym since we're using it as the name
                    item['synonyms'] = item['synonyms'][1:] if len(item['synonyms']) > 1 else []
            
            # Make sure to preserve the source_db field if it already exists
            source_db = item.get('source_db', 'DrugBank')
            
            results.append({
                'id': str(item.get('cid', '')),
                'name': drug_name,
                'formula': item.get('formula', ''),
                'synonyms': ', '.join(item.get('synonyms', [])[:3]),  # Limit to first 3 synonyms for display
                'description': item.get('description', 'No description available'),
                'url': item.get('url', f"https://pubchem.ncbi.nlm.nih.gov/compound/{item.get('cid', '')}"),
                'type': 'drug',  # Add type for categorization
                'source_db': source_db  # Preserve or set the source database
            })
        
        return results
    
    except Exception as e:
        logger.error(f"Error in format_drugbank_results: {str(e)}")
        logger.exception("Stack trace:")
        return {'error': str(e)} 