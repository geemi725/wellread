import asyncio
import hashlib
import json
from typing import List, Dict, Any

import numpy as np
from openai import OpenAI
from anthropic import Anthropic
from tqdm import tqdm
from diskcache import Cache
from prompts import LLM_SELECT_PROMPT


class ContentCurator:
    def __init__(self, openai_api_key: str, anthropic_api_key: str = None, cache_dir: str = "cache/embeddings"):
        self.client = OpenAI(api_key=openai_api_key)
        self.anthropic_client = Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None
        self.embedding_model = "text-embedding-3-large"
        self.cache = Cache(cache_dir)
        self.cache_hits = 0
        self.cache_misses = 0

    async def load_topics(self, topics_file: str = 'topics.txt') -> List[str]:
        """Load topics from a text file."""
        with open(topics_file, 'r', encoding='utf-8') as f:
            content = f.read()

        return [
            line.strip()
            for line in content.split('\n')
            if line.strip() and not line.strip().startswith('#')
        ]

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key from text and model."""
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
        return f"{self.embedding_model}:{text_hash}"

    def get_embedding(self, text: str) -> List[float]:
        """Get OpenAI embedding for a text string, with caching."""
        cache_key = self._get_cache_key(text)

        # Check cache first
        cached_embedding = self.cache.get(cache_key)
        if cached_embedding is not None:
            self.cache_hits += 1
            return cached_embedding

        # Cache miss - call API
        self.cache_misses += 1
        response = self.client.embeddings.create(
            model=self.embedding_model,
            input=text
        )
        embedding = response.data[0].embedding

        # Store in cache
        self.cache.set(cache_key, embedding, expire=None)  # Never expire

        return embedding

    async def get_embedding_async(self, text: str) -> List[float]:
        """Get OpenAI embedding asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_embedding, text)

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        vec1_np = np.array(vec1)
        vec2_np = np.array(vec2)

        dot_product = np.dot(vec1_np, vec2_np)
        norm1 = np.linalg.norm(vec1_np)
        norm2 = np.linalg.norm(vec2_np)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    async def calculate_relevance_score(self, item: Dict[str, Any], topic_embeddings: List[tuple[str, List[float]]]) -> float:
        """Calculate relevance score using semantic similarity."""
        # Get item text (title is most important)
        item_text = item.get('title', '')
        if not item_text:
            return 0.0

        # Get embedding for the item (cached)
        item_embedding = await self.get_embedding_async(item_text)

        # Calculate maximum similarity to any topic
        max_similarity = 0.0
        for topic, topic_embedding in topic_embeddings:
            similarity = self.cosine_similarity(item_embedding, topic_embedding)
            max_similarity = max(max_similarity, similarity)

        # Convert similarity (0-1) to a score (0-100)
        return max_similarity * 100

    async def curate_items(
        self,
        items: List[Dict[str, Any]],
        topics: List[str],
        min_score: float = 0.1,
        max_items_to_post: int = None
    ) -> List[Dict[str, Any]]:
        """Curate items by scoring based on semantic similarity to topics."""
        if not topics:
            return []

        # Reset cache stats
        self.cache_hits = 0
        self.cache_misses = 0

        # Get embeddings for all topics (cached)
        print(f"Getting embeddings for {len(topics)} topics...")
        topic_embeddings = []
        for topic in topics:
            embedding = await self.get_embedding_async(topic)
            topic_embeddings.append((topic, embedding))

        print(f"Topic embeddings: {self.cache_hits} cached, {self.cache_misses} new")

        # Reset for article embeddings
        article_cache_hits = self.cache_hits
        article_cache_misses = self.cache_misses

        # Calculate relevance scores for all items
        print(f"Calculating relevance scores for {len(items)} items...")
        scored_items = []
        for item in tqdm(items, desc="Scoring items"):
            item_copy = item.copy()
            score = await self.calculate_relevance_score(item, topic_embeddings)
            item_copy['relevanceScore'] = score
            scored_items.append(item_copy)
            print(f"Item: {item.get('title', 'No title')}, Score: {score:.2f}")

        article_cache_hits = self.cache_hits - article_cache_hits
        article_cache_misses = self.cache_misses - article_cache_misses
        print(f"Article embeddings: {article_cache_hits} cached, {article_cache_misses} new")
        print(f"Total API calls saved: {self.cache_hits}")

        # Filter by minimum score
        filtered_items = [
            item for item in scored_items
            if item['relevanceScore'] >= min_score
        ]

        # Sort by relevance score (highest first)
        filtered_items.sort(key=lambda x: x['relevanceScore'], reverse=True)

        # Limit to max_items_to_post if specified
        if max_items_to_post and len(filtered_items) > max_items_to_post:
            filtered_items = filtered_items[:max_items_to_post]

        return filtered_items

    def group_by_relevance(self, curated_items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group items by relevance level (high, medium, low)."""
        # Using semantic similarity scores (0-100)
        high_relevance = [item for item in curated_items if item['relevanceScore'] >= 70]
        medium_relevance = [item for item in curated_items if 40 <= item['relevanceScore'] < 70]
        low_relevance = [item for item in curated_items if item['relevanceScore'] < 40]

        return {
            'high': high_relevance,
            'medium': medium_relevance,
            'low': low_relevance
        }

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'size': len(self.cache),
            'hits': self.cache_hits,
            'misses': self.cache_misses,
            'hit_rate': self.cache_hits / (self.cache_hits + self.cache_misses) if (self.cache_hits + self.cache_misses) > 0 else 0
        }

    async def llm_select_items(
        self,
        shortlist: List[Dict[str, Any]],
        guidance_prompt: str,
        max_items: int,
        model: str = "claude-sonnet-4-5-20250929"
    ) -> List[Dict[str, Any]]:
        """Use an LLM to select the best items from a shortlist based on topics and guidance."""
        if not self.anthropic_client:
            raise ValueError("Anthropic client not initialized. Please provide anthropic_api_key.")

        if not shortlist:
            return []

        if len(shortlist) <= max_items:
            return shortlist

        # Prepare the shortlist for the LLM
        items_summary = []
        for idx, item in enumerate(shortlist):
            items_summary.append({
                'index': idx,
                'title': item.get('title', 'No title'),
                'source': item.get('feed_source', 'Unknown source'),
                'description': item.get('description', '')
            })

        # Create the selection prompt
        prompt = LLM_SELECT_PROMPT.format(
            guidance_prompt=guidance_prompt,
            shortlist_size=len(shortlist),
            items_summary=json.dumps(items_summary, indent=2),
            max_items=max_items
        )


        # Call the LLM
        loop = asyncio.get_event_loop()
        message = await loop.run_in_executor(
            None,
            lambda: self.anthropic_client.messages.create(
                model=model,
                max_tokens=5000,
                messages=[{
                    'role': 'user',
                    'content': prompt
                }]
            )
        )

        # Parse the response
        response_text = message.content[0].text.strip()

        # Extract JSON from response (handle cases where LLM adds extra text)
        try:
            selection_results = json.loads(response_text)
        except json.JSONDecodeError:
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                selection_results = json.loads(json_str)
            else:
                print(f"Error parsing JSON from response: {response_text}")
                selection_results = []

        # Extract selected items and attach explanations
        selected_items = []
        for result in selection_results:
            if not isinstance(result, dict):
                continue

            idx = result.get('index')
            is_selected = result.get('selected', False)

            original_item = shortlist[idx]
            print(f"{original_item.get('title')} selected: {is_selected}")

            if is_selected and isinstance(idx, int) and 0 <= idx < len(shortlist):
                selected_items.append(original_item)

            if len(selected_items) >= max_items:
                break

        # If we didn't get enough valid selections, fill with remaining top items
        if len(selected_items) < max_items:
            print(f"⚠️  LLM selected {len(selected_items)}/{max_items} items. Filling with remaining items.")
            for item in shortlist:
                if item not in selected_items:
                    selected_items.append(item)
                if len(selected_items) >= max_items:
                    break

        return selected_items
