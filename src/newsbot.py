#!/usr/bin/env python3

import os
import sys
import json
import asyncio
import traceback
from rss_parser import RSSFeedParser
from curator import ContentCurator
from slack_poster import SlackPoster
from article_cache import ArticleCache


async def main():
    print('🤖 AI News Digest Bot Starting...')

    # Load environment variables
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    SLACK_TOKEN = os.environ.get('SLACK_BOT_TOKEN')
    SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL')
    SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK')

    if not ANTHROPIC_API_KEY:
        print('❌ ANTHROPIC_API_KEY environment variable is required')
        sys.exit(1)

    if not OPENAI_API_KEY:
        print('❌ OPENAI_API_KEY environment variable is required')
        sys.exit(1)

    if not SLACK_TOKEN or not SLACK_CHANNEL:
        print('❌ SLACK_BOT_TOKEN and SLACK_CHANNEL environment variables are required')
        sys.exit(1)

    # Load configuration
    with open('config.json', 'r') as f:
        config = json.load(f)

    TIMEFRAME_HOURS = config['timeframe_hours']
    MAX_ITEMS_TO_POST = config['max_items_to_post']
    EMBEDDING_CACHE_DIR = config['embedding_cache_dir']
    SELECTION_GUIDANCE_PROMPT = config['selection_guidance_prompt']

    # Article cache configuration
    CACHE_POSTED_ARTICLES = config['cache_posted_articles']
    POSTED_ARTICLES_CACHE_FILE = config['posted_articles_cache_file']

    # Get LLM model configurations
    llm_models = config.get('llm_models', {})
    SUMMARIZATION_MODEL = llm_models['summarization']
    SELECTION_MODEL = llm_models.get('selection', SUMMARIZATION_MODEL)

    print(f'⏰ Looking for posts from the last {TIMEFRAME_HOURS} hours')
    print(f'📊 Maximum items to post: {MAX_ITEMS_TO_POST}')
    print(f'🤖 Using model: {SUMMARIZATION_MODEL}')
    if CACHE_POSTED_ARTICLES:
        print(f'💾 Article cache enabled')

    # Initialize components
    feed_parser = RSSFeedParser()
    curator = ContentCurator(OPENAI_API_KEY, anthropic_api_key=ANTHROPIC_API_KEY, cache_dir=EMBEDDING_CACHE_DIR)

    # Initialize article cache if enabled
    article_cache = None
    if CACHE_POSTED_ARTICLES:
        article_cache = ArticleCache(POSTED_ARTICLES_CACHE_FILE)
        print(f'📚 Loaded article cache with {article_cache.get_cache_size()} previously posted articles')

    try:
        # Step 1: Load feeds and topics
        print('📡 Loading RSS feeds...')
        feed_urls = await feed_parser.load_feeds('news_feeds.txt')
        print(f'Found {len(feed_urls)} feeds to monitor')

        if len(feed_urls) == 0:
            print('❌ No feeds configured in feeds.txt')
            sys.exit(1)

        # Step 2: Fetch all RSS feeds
        print('🔍 Fetching RSS feeds...')
        recent_items = []
        for feed_url in feed_urls:
            feed_items = feed_parser.parse_rss_newsfeed(feed_url)
            recent_items.extend(feed_items)

        print(f'Found {len(recent_items)} news items')

        if article_cache:
            print('🔍 Filtering out previously posted articles...')
            unposted_items = article_cache.filter_unposted(recent_items)
            already_posted = len(recent_items) - len(unposted_items)
            print(f'{len(unposted_items)} unposted items ({already_posted} already posted)')
            recent_items = unposted_items

            if len(recent_items) == 0:
                print('✅ All recent items have been posted before')
                sys.exit(0)


        print(f'🤖 Using LLM to select top {MAX_ITEMS_TO_POST} items from retrived news items...')
        curated_items = await curator.llm_select_items(
            shortlist=recent_items,
            guidance_prompt=SELECTION_GUIDANCE_PROMPT,
            max_items=MAX_ITEMS_TO_POST,
            model=SELECTION_MODEL
        )
        print(f'Selected {len(curated_items)} items for posting')

        if len(curated_items) == 0:
            print('✅ No items selected by LLM')
            sys.exit(0)

 
        slack_poster = SlackPoster(SLACK_TOKEN, SLACK_WEBHOOK)

        # Post to Slack
        print('📤 Posting to Slack...')
        await slack_poster.post_news_items(SLACK_CHANNEL, curated_items)

        # Cache posted article URLs (if cache enabled)
        if article_cache:
            posted_urls = [item.get('link') for item in curated_items if item.get('link')]
            article_cache.mark_batch_as_posted(posted_urls)
            print(f'💾 Cached {len(posted_urls)} posted article URLs')

        print('✅ WellRead Bot completed successfully!')

    except Exception as error:
        print(f'❌ Error: {str(error)}')
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
