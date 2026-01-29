import asyncio
from datetime import datetime
from operator import ne
from typing import List, Dict, Any
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class SlackPoster:
    def __init__(self, token: str, webhook: str = None):
        self.client = WebClient(token=token)
        self.webhook = webhook

    async def post_header(self, channel: str) -> str:
        """Post a header message to separate from previous posts."""
        today = datetime.now().strftime('%B %d, %Y at %I:%M %p')

        message = {
            'channel': channel,
            'text': f"📰 WellRead Digest - {today}",
            'blocks': [
                {
                    'type': 'divider'
                },
                {
                    'type': 'header',
                    'text': {
                        'type': 'plain_text',
                        'text': f"📰 WellRead Digest"
                    }
                },
                {
                    'type': 'context',
                    'elements': [
                        {
                            'type': 'mrkdwn',
                            'text': f"_{today}_"
                        }
                    ]
                },
                {
                    'type': 'divider'
                }
            ]
        }

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.client.chat_postMessage(**message)
            )
            return result['ts']
        except SlackApiError as error:
            print(f"Error posting header: {error.response['error']}")
            raise error

    def format_summary_for_slack(self, summary: str) -> str:
        """Format summary text for proper Slack markdown display."""
        import re

        # First, convert markdown headers to bold text
        # Replace ## Header or # Header with *Header*
        summary = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', summary, flags=re.MULTILINE)

        # Convert **bold** to *bold* (Slack uses single asterisks for bold)
        summary = re.sub(r'\*\*(.+?)\*\*', r'*\1*', summary)

        # Ensure bullet points are properly formatted with line breaks
        lines = summary.strip().split('\n')
        formatted_lines = []

        for line in lines:
            # Preserve leading whitespace for indentation
            stripped = line.strip()
            if not stripped:
                continue

            # Count leading spaces for nested bullets
            leading_spaces = len(line) - len(line.lstrip())
            indent = ''
            if leading_spaces >= 2:
                # Nested bullet - add indentation
                indent = '    '

            # Replace bullet characters with Slack-compatible format
            if stripped.startswith('•'):
                formatted = indent + '• ' + stripped[1:].strip()
            elif stripped.startswith('-'):
                formatted = indent + '• ' + stripped[1:].strip()
            elif stripped.startswith('*') and not stripped.startswith('**') and not stripped.endswith('*'):
                # Only treat as bullet if it's a single asterisk at start (not bold markers)
                formatted = indent + '• ' + stripped[1:].strip()
            else:
                # No bullet character found, treat as regular text
                formatted = line.strip()

            formatted_lines.append(formatted)

        return '\n'.join(formatted_lines)

    async def post_paper_with_summary(self, channel: str, paper: Dict[str, Any], index: int, total: int) -> str:
        """Post a single paper as a top-level message with summary included."""
        try:
            # Format publication date
            pub_date = 'Unknown date'
            if paper.get('pubDate'):
                try:
                    if isinstance(paper['pubDate'], str):
                        from dateutil import parser as date_parser
                        parsed_date = date_parser.parse(paper['pubDate'])
                        pub_date = parsed_date.strftime('%m/%d/%Y')
                    else:
                        import time
                        parsed_date = datetime.fromtimestamp(time.mktime(paper['pubDate']))
                        pub_date = parsed_date.strftime('%m/%d/%Y')
                except Exception:
                    pub_date = 'Unknown date'

            # Get and format summary
            summary = paper.get('summary', 'No summary available')
            formatted_summary = self.format_summary_for_slack(summary)

            # Post the paper with summary as top-level message
            paper_message = {
                'channel': channel,
                'text': paper.get('title', 'No title'),
                'blocks': [
                    {
                        'type': 'section',
                        'text': {
                            'type': 'mrkdwn',
                            'text': f"*<{paper.get('link', '')}|{paper.get('title', 'No title')}>*\n\n{formatted_summary}"
                        }
                    },
                    {
                        'type': 'context',
                        'elements': [
                            {
                                'type': 'mrkdwn',
                                'text': f"*{index}/{total}* • {paper.get('feedSource', 'Unknown')} • {pub_date}"
                            }
                        ]
                    }
                ]
            }

            loop = asyncio.get_event_loop()
            paper_result = await loop.run_in_executor(
                None,
                lambda: self.client.chat_postMessage(**paper_message)
            )

            return paper_result['ts']
        except SlackApiError as error:
            print(f"Error posting paper \"{paper.get('title', 'Unknown')}\": {error.response['error']}")
            raise error

    async def post_all_papers(self, channel: str, papers: List[Dict[str, Any]]) -> List[str]:
        """Post all papers as top-level messages."""
        total = len(papers)
        timestamps = []

        for i, paper in enumerate(papers):
            ts = await self.post_paper_with_summary(channel, paper, i + 1, total)
            timestamps.append(ts)

            # Rate limiting between papers
            if i < len(papers) - 1:
                await asyncio.sleep(1)

        return timestamps

    async def post_papers(self, channel: str, papers: List[Dict[str, Any]]):
        """Post header, then all papers."""
        print(f"Posting header to channel {channel}...")
        await self.post_header(channel)

        # Small delay after header
        await asyncio.sleep(1)

        print(f"Posting {len(papers)} papers...")

        # Post each paper as a top-level message
        await self.post_all_papers(channel, papers)

        print('All papers posted!')

    async def post_news_item(self, channel: str, news_item: Dict[str, Any], index: int, total: int):
        try:
            message = {
                'channel': channel,
                'text': news_item.get('title', 'No title'),
                'blocks': [
                    {
                        'type': 'section',
                        'text': {
                            'type': 'mrkdwn',
                            'text': f"*<{news_item.get('link', '')}|{news_item.get('title', 'No title')}>*\n\n{news_item.get('description', '')}"
                        }
                    },
                    {
                        'type': 'context',
                        'elements': [
                            {
                                'type': 'mrkdwn',
                                'text': f"*{index}/{total}* • {news_item.get('feed_source', 'Unknown')} • {news_item.get('published', 'Unknown date')}"
                            }
                        ]
                    }
                ]
            }

            loop = asyncio.get_event_loop()
            paper_result = await loop.run_in_executor(
                None,
                lambda: self.client.chat_postMessage(**message)
            )

            return paper_result['ts']
        except SlackApiError as error:
            print(f"Error posting paper \"{news_item.get('title', 'Unknown')}\": {error.response['error']}")
            raise error

    async def post_news_items(self, channel: str, news_items: List[Dict[str, Any]]):
        """Post header, then links to news items."""
        print(f"Posting header to channel {channel}...")
        today = datetime.now().strftime('%B %d, %Y at %I:%M %p')

        message = {
            'channel': channel,
            'text': f"📰 AI News Digest - {today}",
            'blocks': [
                {
                    'type': 'divider'
                },
                {
                    'type': 'header',
                    'text': {
                        'type': 'plain_text',
                        'text': f"📰 AI News Digest"
                    }
                },
                {
                    'type': 'context',
                    'elements': [
                        {
                            'type': 'mrkdwn',
                            'text': f"_{today}_"
                        }
                    ]
                },
                {
                    'type': 'divider'
                }
            ]
        }

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.chat_postMessage(**message)
            )
        
        except SlackApiError as error:
            print(f"Error posting header: {error.response['error']}")
            raise error

        # Small delay after header
        await asyncio.sleep(1)

        print(f"Posting {len(news_items)} news items...")

        # Post each news item as a top-level message
        timestamps = []
        for i, news_item in enumerate(news_items):
            ts = await self.post_news_item(channel, news_item, i + 1, len(news_items))
            timestamps.append(ts)

            # Rate limiting between news items
            if i < len(news_items) - 1:
                await asyncio.sleep(1)

        print('All news items posted!')