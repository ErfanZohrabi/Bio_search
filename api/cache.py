"""
Cache Functionality for BioSearch Application

This module provides Redis-based caching functionality for search results
and API responses. It also includes fallback to a simple in-memory cache
when Redis is not available.
"""

import json
import time
import logging
import asyncio
from typing import Dict, Any, Optional, Union, List, Tuple
from functools import wraps
import hashlib
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Try to import Redis dependencies
try:
    import redis
    # Safely import Redis libraries
try:
    import aioredis
    REDIS_AVAILABLE = True
except (ImportError, TypeError):
    aioredis = None
    REDIS_AVAILABLE = False
    print("Redis dependencies not installed. Using in-memory cache as fallback.")
    REDIS_AVAILABLE = True


# Cache configuration
CACHE_TTL = int(os.getenv('CACHE_TTL', 3600))  # 1 hour default
CACHE_PREFIX = "biosearch:"
CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'true').lower() in ('true', '1', 't', 'yes')

# In-memory cache as fallback
_memory_cache: Dict[str, Tuple[Any, float]] = {}

class Cache:
    """Redis cache client wrapper."""
    
    def __init__(self, url: str = None):
        """
        Initialize the cache.
        
        Args:
            url: Redis connection URL (redis://user:password@host:port/db)
        """
        self.url = url or os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self.enabled = CACHE_ENABLED
        self.ttl = CACHE_TTL
        self._redis = None
        self._aioredis = None
        
        if REDIS_AVAILABLE and self.enabled:
            try:
                # Initialize synchronous Redis client
                self._redis = redis.from_url(self.url)
                self._redis.ping()  # Test connection
                logger.info("Connected to Redis cache server")
            except (redis.ConnectionError, redis.RedisError) as e:
                logger.warning(f"Failed to connect to Redis: {str(e)}. Using in-memory cache.")
                self._redis = None
        
    async def initialize_async(self):
        """Initialize the async Redis client."""
        if REDIS_AVAILABLE and self.enabled and not self._aioredis:
            try:
                # Initialize asynchronous Redis client
                self._aioredis = await aioredis.from_url(self.url)
                await self._aioredis.ping()  # Test connection
                logger.info("Connected to Redis cache server (async)")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis async client: {str(e)}. Using in-memory cache.")
                self._aioredis = None
    
    def _get_key(self, key: str) -> str:
        """
        Format a cache key with the prefix.
        
        Args:
            key: The original key
            
        Returns:
            Formatted cache key
        """
        return f"{CACHE_PREFIX}{key}"
    
    def _hash_key(self, key_data: Any) -> str:
        """
        Create a stable hash for complex objects to use as cache keys.
        
        Args:
            key_data: Data to hash (can be a string, dict, list, etc.)
            
        Returns:
            Hashed key string
        """
        if isinstance(key_data, str):
            data_str = key_data
        elif isinstance(key_data, (dict, list, tuple)):
            data_str = json.dumps(key_data, sort_keys=True)
        else:
            data_str = str(key_data)
            
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()
    
    def get(self, key: str) -> Any:
        """
        Get item from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        if not self.enabled:
            return None
            
        formatted_key = self._get_key(key)
        
        # Try Redis first
        if self._redis:
            try:
                data = self._redis.get(formatted_key)
                if data:
                    logger.debug(f"Cache hit for key: {key}")
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"Redis error in get(): {str(e)}")
        
        # Fall back to in-memory cache
        if formatted_key in _memory_cache:
            value, expiry = _memory_cache[formatted_key]
            if expiry > time.time():
                logger.debug(f"In-memory cache hit for key: {key}")
                return value
            else:
                # Remove expired item
                del _memory_cache[formatted_key]
        
        logger.debug(f"Cache miss for key: {key}")
        return None
    
    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """
        Set item in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses default if None)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
            
        ttl = ttl if ttl is not None else self.ttl
        formatted_key = self._get_key(key)
        
        try:
            serialized = json.dumps(value)
            
            # Try Redis first
            if self._redis:
                try:
                    self._redis.setex(formatted_key, ttl, serialized)
                    return True
                except Exception as e:
                    logger.warning(f"Redis error in set(): {str(e)}")
            
            # Fall back to in-memory cache
            _memory_cache[formatted_key] = (value, time.time() + ttl)
            return True
            
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize cache value: {str(e)}")
            return False
    
    async def aget(self, key: str) -> Any:
        """
        Asynchronously get item from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        if not self.enabled:
            return None
            
        formatted_key = self._get_key(key)
        
        # Try Redis first
        if self._aioredis:
            try:
                data = await self._aioredis.get(formatted_key)
                if data:
                    logger.debug(f"Async cache hit for key: {key}")
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"Redis error in aget(): {str(e)}")
        
        # Fall back to in-memory cache
        if formatted_key in _memory_cache:
            value, expiry = _memory_cache[formatted_key]
            if expiry > time.time():
                logger.debug(f"In-memory cache hit for key: {key}")
                return value
            else:
                # Remove expired item
                del _memory_cache[formatted_key]
        
        logger.debug(f"Async cache miss for key: {key}")
        return None
    
    async def aset(self, key: str, value: Any, ttl: int = None) -> bool:
        """
        Asynchronously set item in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses default if None)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
            
        ttl = ttl if ttl is not None else self.ttl
        formatted_key = self._get_key(key)
        
        try:
            serialized = json.dumps(value)
            
            # Try Redis first
            if self._aioredis:
                try:
                    await self._aioredis.setex(formatted_key, ttl, serialized)
                    return True
                except Exception as e:
                    logger.warning(f"Redis error in aset(): {str(e)}")
            
            # Fall back to in-memory cache
            _memory_cache[formatted_key] = (value, time.time() + ttl)
            return True
            
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize cache value: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        """
        Delete item from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted, False otherwise
        """
        if not self.enabled:
            return False
            
        formatted_key = self._get_key(key)
        
        # Try Redis first
        success = False
        if self._redis:
            try:
                success = bool(self._redis.delete(formatted_key))
            except Exception as e:
                logger.warning(f"Redis error in delete(): {str(e)}")
        
        # Also check in-memory cache
        if formatted_key in _memory_cache:
            del _memory_cache[formatted_key]
            success = True
            
        return success
    
    def clear_all(self, pattern: str = "*") -> int:
        """
        Clear all items matching a pattern from the cache.
        
        Args:
            pattern: Key pattern to match (default: all)
            
        Returns:
            Number of keys deleted
        """
        if not self.enabled:
            return 0
            
        formatted_pattern = self._get_key(pattern)
        count = 0
        
        # Try Redis first
        if self._redis:
            try:
                keys = self._redis.keys(formatted_pattern)
                if keys:
                    count = self._redis.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis error in clear_all(): {str(e)}")
        
        # Also clear in-memory cache
        mem_count = 0
        for k in list(_memory_cache.keys()):
            if k.startswith(CACHE_PREFIX):
                del _memory_cache[k]
                mem_count += 1
        
        return count + mem_count


# Create a global cache instance
cache = Cache()

# Define cache decorator for async functions
def cached(ttl: int = None, key_prefix: str = ""):
    """
    Decorator to cache function results.
    
    Args:
        ttl: Cache time-to-live in seconds
        key_prefix: Prefix for cache key
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not CACHE_ENABLED:
                return await func(*args, **kwargs)
                
            # Create a cache key from function name and arguments
            key_parts = [key_prefix, func.__name__]
            
            # Add positional and keyword arguments to the key
            if args:
                key_parts.append(cache._hash_key(args))
            
            if kwargs:
                sorted_kwargs = json.dumps(kwargs, sort_keys=True)
                key_parts.append(cache._hash_key(sorted_kwargs))
                
            cache_key = ':'.join(key_parts)
            
            # Try to get from cache first
            cached_result = await cache.aget(cache_key)
            if cached_result is not None:
                return cached_result
                
            # If not in cache, call the function
            result = await func(*args, **kwargs)
            
            # Cache the result if it's valid
            if result is not None:
                await cache.aset(cache_key, result, ttl)
                
            return result
            
        return wrapper
    return decorator 
