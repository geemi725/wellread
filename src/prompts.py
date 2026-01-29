LLM_SELECT_PROMPT = """You are a content curator selecting the most relevant articles from a shortlist.

Selection guidance:
{guidance_prompt}

Here are the {shortlist_size} articles in the shortlist (with their embedding-based relevance scores):

{items_summary}

Please select the top {max_items} articles that best match the topics and guidance.

Respond with ONLY a JSON array containing ALL articles with the following format:
[
{{"index": 0, "selected": true}},
{{"index": 1, "selected": false}},
...
]"""