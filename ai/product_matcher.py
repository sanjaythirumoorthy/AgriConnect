"""
AI Product Recommendation / Search
-----------------------------------
Uses TF-IDF text embeddings over (name + category + description) so
buyers get relevant matches even with typos / partial / related terms
("tomatoes" matches "Fresh Tomato" or "Nadu Thakkali"), not just exact
keyword filtering. Falls back to a "no strong match" signal that
triggers the demand-sensing Request-a-Farmer flow.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

MATCH_THRESHOLD = 0.12  # below this, we treat it as "not found"


def rank_products(query: str, products: list[dict], top_k: int = 20):
    """products: list of dicts each with a 'text' key (searchable blob)
    and an 'id' key. Returns (ranked_list, best_score)."""
    if not products:
        return [], 0.0

    corpus = [p["text"] for p in products] + [query]
    vec = TfidfVectorizer(stop_words="english")
    tfidf = vec.fit_transform(corpus)
    query_vec = tfidf[-1]
    product_vecs = tfidf[:-1]

    sims = cosine_similarity(query_vec, product_vecs).flatten()
    ranked = sorted(zip(products, sims), key=lambda x: x[1], reverse=True)
    best_score = float(ranked[0][1]) if ranked else 0.0

    results = [{**p, "match_score": round(float(s), 3)} for p, s in ranked[:top_k] if s > 0.02]
    return results, best_score


def is_demand_gap(best_score: float) -> bool:
    """True => nothing on the platform genuinely matches; trigger the
    Product-Not-Found -> Request Farmers flow."""
    return best_score < MATCH_THRESHOLD


def suggest_farmers_for_request(request_text: str, farmer_products_history: list[dict], top_k: int = 10):
    """Given a buyer's unmet request, rank farmers whose past listings
    are textually closest to the request -- i.e. farmers who likely
    grow / can supply this even though nothing is live right now."""
    return rank_products(request_text, farmer_products_history, top_k=top_k)
