"""
Database Configuration for BioSearch Application

This module contains configuration for various biological databases 
including API endpoints, rate limits, and API key management.
"""

import os
import logging
from dataclasses import dataclass
from typing import Dict, Optional, List, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# NCBI API key settings
NCBI_API_KEY = os.environ.get('NCBI_API_KEY')
if NCBI_API_KEY:
    logger.info(f"API key for NCBI loaded from environment")
else:
    logger.warning(f"API key for NCBI not found in environment variable NCBI_API_KEY")

@dataclass
class DatabaseConfig:
    """Configuration for a biological database API."""
    name: str
    base_url: str
    search_endpoint: str
    fetch_endpoint: Optional[str] = None
    requires_api_key: bool = False
    api_key_env_var: Optional[str] = None
    api_key_param_name: Optional[str] = None
    rate_limit: Optional[int] = None  # requests per minute
    response_format: str = "json"
    timeout: int = 30  # seconds
    headers: Dict[str, str] = None
    query_param_name: str = "query"
    default_params: Dict[str, Any] = None
    
    def __post_init__(self):
        """Initialize headers if not provided."""
        if self.headers is None:
            self.headers = {"Accept": "application/json"}
            
        if self.default_params is None:
            self.default_params = {}
            
        # Get API key from environment if needed
        if self.requires_api_key and self.api_key_env_var:
            api_key = os.getenv(self.api_key_env_var)
            if not api_key:
                logger.warning(f"API key for {self.name} not found in environment variable {self.api_key_env_var}")
            else:
                logger.info(f"API key for {self.name} loaded from environment")
                
                # Store API key in appropriate location
                if self.api_key_param_name:
                    self.default_params[self.api_key_param_name] = api_key
                else:
                    self.headers["Authorization"] = f"Bearer {api_key}"

# Configuration for NCBI Entrez API
NCBI_CONFIG = DatabaseConfig(
    name="NCBI",
    base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    search_endpoint="/esearch.fcgi",
    fetch_endpoint="/efetch.fcgi",
    requires_api_key=True,
    api_key_env_var="NCBI_API_KEY",
    api_key_param_name="api_key",
    rate_limit=10 if not os.getenv("NCBI_API_KEY") else 30,  # 10 req/sec without API key, 30 with key
    query_param_name="term",
    default_params={
        "retmode": "json",
        "retmax": 10,
        "usehistory": "y"
    }
)

# Configuration for UniProt API
UNIPROT_CONFIG = DatabaseConfig(
    name="UniProt",
    base_url="https://rest.uniprot.org",
    search_endpoint="/uniprotkb/search",
    requires_api_key=False,
    rate_limit=150,  # Per minute
    default_params={
        "format": "json",
        "size": 10
    }
)

# Configuration for PDB API
PDB_CONFIG = DatabaseConfig(
    name="PDB",
    base_url="https://data.rcsb.org/rest/v1",
    search_endpoint="/search",
    fetch_endpoint="/entry",
    requires_api_key=False,
    rate_limit=50,  # Per minute
    default_params={
        "wt": "json",
        "rows": 10
    }
)

# Configuration for KEGG API
KEGG_CONFIG = DatabaseConfig(
    name="KEGG",
    base_url="https://rest.kegg.jp",
    search_endpoint="/find",
    fetch_endpoint="/get",
    requires_api_key=False,
    response_format="text",
    headers={"Accept": "text/plain"},
    rate_limit=20,  # Per minute
    default_params={
        "format": "json"
    }
)

# Configuration for Ensembl API
ENSEMBL_CONFIG = DatabaseConfig(
    name="Ensembl",
    base_url="https://rest.ensembl.org",
    search_endpoint="/lookup/symbol",
    requires_api_key=False,
    rate_limit=15,  # Per second
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json"
    },
    default_params={
        "expand": 1
    }
)

# Configuration for DrugBank (using PubChem as proxy)
DRUGBANK_CONFIG = DatabaseConfig(
    name="DrugBank",
    base_url="https://pubchem.ncbi.nlm.nih.gov/rest/pug",
    search_endpoint="/compound/name",
    fetch_endpoint="/compound/cid",
    requires_api_key=False,
    rate_limit=5,  # Per second
    query_param_name="name",
    default_params={
        "output": "JSON"
    }
)

# Configuration for ChEMBL API
CHEMBL_CONFIG = DatabaseConfig(
    name="ChEMBL",
    base_url="https://www.ebi.ac.uk/chembl/api/data",
    search_endpoint="/molecule",
    requires_api_key=False,
    rate_limit=30,  # Per minute
    default_params={
        "format": "json",
        "limit": 10
    }
)

# All available database configurations
DATABASE_CONFIGS = {
    "ncbi": NCBI_CONFIG,
    "ncbi_gene": NCBI_CONFIG,
    "pubmed": NCBI_CONFIG,
    "uniprot": UNIPROT_CONFIG,
    "pdb": PDB_CONFIG,
    "kegg": KEGG_CONFIG,
    "ensembl": ENSEMBL_CONFIG,
    "drugbank": DRUGBANK_CONFIG,
    "chembl": CHEMBL_CONFIG
}

def get_db_config(db_name: str) -> Optional[DatabaseConfig]:
    """
    Get configuration for a specific database.
    
    Args:
        db_name: Name of the database
        
    Returns:
        Database configuration object or None if not found
    """
    db_name = db_name.lower()
    if db_name in DATABASE_CONFIGS:
        return DATABASE_CONFIGS[db_name]
    
    logger.warning(f"Configuration for database '{db_name}' not found")
    return None

def init_api_keys_from_env():
    """Initialize all API keys from environment variables."""
    missing_keys = []
    
    for config in DATABASE_CONFIGS.values():
        if config.requires_api_key and config.api_key_env_var:
            if not os.getenv(config.api_key_env_var):
                missing_keys.append((config.name, config.api_key_env_var))
    
    if missing_keys:
        logger.warning(f"Missing API keys for: {', '.join([f'{db} ({env})' for db, env in missing_keys])}")
    
    return len(missing_keys) == 0 