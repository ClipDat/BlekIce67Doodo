import json
import os
import hashlib
import feedparser


FEEDS = {
    "CoinDesk":
        "https://www.coindesk.com/arc/outboundfeeds/rss/",

    "BBC Business":
        "https://feeds.bbci.co.uk/news/business/rss.xml",

    "BBC World":
        "https://feeds.bbci.co.uk/news/world/rss.xml"
}


SEEN_FILE = "seen_news.json"


def make_id(source, title, link):
    text = source + title + link

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def load_seen():

    if not os.path.exists(SEEN_FILE):
        return set()

    with open(SEEN_FILE, "r") as file:
        return set(
            json.load(file)
        )


def save_seen(seen):

    # Prevent file growing forever
    seen = list(seen)[-3000:]

    with open(SEEN_FILE, "w") as file:
        json.dump(
            seen,
            file,
            indent=2
        )


def fetch_news():

    articles = []

    for source, url in FEEDS.items():

        feed = feedparser.parse(url)

        for entry in feed.entries[:20]:

            title = entry.get(
                "title",
                ""
            )

            link = entry.get(
                "link",
                ""
            )

            published = entry.get(
                "published",
                ""
            )

            article_id = make_id(
                source,
                title,
                link
            )

            articles.append({
                "id": article_id,
                "source": source,
                "title": title,
                "link": link,
                "published": published
            })

    return articles


def get_new_articles():

    seen = load_seen()

    articles = fetch_news()

    # FIRST EVER RUN:
    # mark existing stories as seen
    if not os.path.exists(SEEN_FILE):

        for article in articles:
            seen.add(article["id"])

        save_seen(seen)

        print(
            f"News initialized. "
            f"{len(articles)} existing stories ignored."
        )

        return []

    new_articles = []

    for article in articles:

        if article["id"] not in seen:

            new_articles.append(
                article
            )

            seen.add(
                article["id"]
            )

    save_seen(seen)

    return new_articles
