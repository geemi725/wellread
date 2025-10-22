import feedparser
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
import asyncio
import re


class RSSFeedParser:
    def __init__(self):
        pass

    async def load_feeds(self, feeds_file: str = 'feeds.txt') -> List[str]:
        """Load RSS feed URLs from a text file."""
        with open(feeds_file, 'r', encoding='utf-8') as f:
            content = f.read()

        return [
            line.strip()
            for line in content.split('\n')
            if line.strip() and not line.strip().startswith('#')
        ]

    def fetch_feed(self, url: str) -> Dict[str, Any]:
        """Fetch and parse a single RSS feed."""
        try:
            feed = feedparser.parse(url)

            if feed.bozo and not feed.entries:
                # Feed parsing failed
                raise Exception(f"Failed to parse feed: {getattr(feed, 'bozo_exception', 'Unknown error')}")

            feed_title = feed.feed.get('title', 'Unknown Feed')

            items = []
            for entry in feed.entries:
                # Extract creator/author
                creator = None
                if hasattr(entry, 'author'):
                    creator = entry.author
                elif hasattr(entry, 'dc_creator'):
                    creator = entry.dc_creator

                # Extract description
                description = None
                if hasattr(entry, 'summary'):
                    description = entry.summary
                elif hasattr(entry, 'description'):
                    description = entry.description

                # Extract content
                content = None
                if hasattr(entry, 'content') and entry.content:
                    content = entry.content[0].get('value', '')
                elif hasattr(entry, 'content_encoded'):
                    content = entry.content_encoded

                items.append({
                    'title': entry.get('title', 'No title'),
                    'link': entry.get('link', ''),
                    'pubDate': entry.get('published', entry.get('updated', '')),
                    'creator': creator,
                    'description': description,
                    'content': content,
                    'feedSource': feed_title
                })

            return {
                'success': True,
                'feedTitle': feed_title,
                'items': items
            }
        except Exception as error:
            print(f"Error fetching feed {url}: {str(error)}")
            return {
                'success': False,
                'error': str(error)
            }

    async def fetch_all_feeds(self, feed_urls: List[str]) -> List[Dict[str, Any]]:
        """Fetch all RSS feeds concurrently."""
        # Run feed parsing in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            *[loop.run_in_executor(None, self.fetch_feed, url) for url in feed_urls]
        )

        # Flatten all items from successful feeds
        all_items = []
        for result in results:
            if result['success']:
                all_items.extend(result['items'])

        return all_items

    def deduplicate_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate items based on link URL, keeping the first occurrence."""
        seen_links = set()
        deduplicated = []

        for item in items:
            link = item.get('link', '')
            if link and link not in seen_links:
                seen_links.add(link)
                deduplicated.append(item)
            elif not link:
                # If there's no link, keep the item (don't deduplicate)
                deduplicated.append(item)

        return deduplicated

    def filter_by_timeframe(self, items: List[Dict[str, Any]], hours_ago: int = 24) -> List[Dict[str, Any]]:
        """Filter items to only those published within the specified timeframe."""
        # Use timezone-aware UTC time for comparison
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)

        filtered_items = []
        for item in items:
            if not item.get('pubDate'):
                continue

            try:
                # Parse various date formats
                pub_date_str = item['pubDate']
                # feedparser typically provides struct_time, but handle string too
                if isinstance(pub_date_str, str):
                    from dateutil import parser as date_parser
                    pub_date = date_parser.parse(pub_date_str)
                else:
                    # It's likely a time.struct_time from feedparser
                    import time
                    pub_date = datetime.fromtimestamp(time.mktime(pub_date_str), tz=timezone.utc)

                # If pub_date is naive, assume UTC
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)

                if pub_date > cutoff_time:
                    filtered_items.append(item)
            except Exception as e:
                print(f"Error parsing date for item '{item.get('title', 'Unknown')}': {str(e)}")
                continue

        return filtered_items


class RSSNewsParser:
    def __init__(self,url: str):
        self.url = url

    def parse_rss_feed(rss_content):
        """
        Parse RSS feed and extract article information
        
        Args:
            rss_content: RSS feed as string or URL
        
        Returns:
            List of dictionaries containing article info
        """
        # Parse the feed (works with both URLs and strings)
        feed = feedparser.parse(rss_content)
        feed_name = rss_content.split("/")[2]
        articles = []
        for entry in feed.entries:
            desc = entry.get('description', '')
            date = entry.get('published', '')

            # override description for Hacker News
            if feed_name == 'hnrss.org':
                desc = ''
            # remove html tags, markdown links, markdown images for other feeds
            else:
                #remove html tags
                desc = re.sub(r'<[^>]*>', '', desc)
                #remove markdown links
                desc = re.sub(r'\[.*?\]\((.*?)\)', '', desc)
                #remove markdown images
                desc = re.sub(r'!\[.*?\]\((.*?)\)', '', desc)
            if date != '':
                try:    
                    date = datetime.strptime(date, '%a, %d %b %Y %H:%M:%S %z')
                    formatted_date = date.strftime("%a, %d %b %Y")
                except ValueError:
                    formatted_date = date
            else:
                formatted_date = "unknown date"
                
            article = {
                'title': entry.get('title', 'No title'),
                'link': entry.get('link', ''),
                'description': desc,
                'published': formatted_date,
                'feed_source': feed_name,
            }
            articles.append(article)
        
        return articles