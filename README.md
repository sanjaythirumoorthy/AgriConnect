# AgriConnect — Farmer-Buyer Marketplace (MVP)

A bilingual (English/Tamil) web platform connecting farmers directly to
buyers (consumers, retailers, wholesalers), built from the project flow
diagram. Includes four working AI features and a shared-transport
optimizer.

## Features implemented

- **Auth & roles**: Farmer (private/public) and Buyer (consumer/retailer/
  wholesale), with a session-persisted EN/TA language switch.
- **Farmer dashboard**: crop listing, order tracking, notifications, rating.
- **AI Price Recommendation** (`ai/price_recommender.py`): a Gradient
  Boosting Regressor trained on `data/base_prices.csv`, personalized using
  the farmer's own historical average price per category.
- **AI Quality Check** (`ai/quality_checker.py`): heuristic image analysis
  (sharpness / brightness / saturation) on the uploaded product photo,
  producing a 0-100 score and A-D grade. Interface is designed to be
  swapped for a trained CNN later without touching the rest of the app.
- **AI Product Matching / Search** (`ai/product_matcher.py`): TF-IDF +
  cosine similarity search across listings, so buyers get relevant
  results even without exact keyword matches.
- **Demand-sensing loop**: when a buyer's search has no good match, they
  can broadcast a Request; farmers whose past listings are a good text
  match get notified automatically ("Product Not Found -> Request
  Farmers -> Notifies Farmers" from the flow diagram).
- **AI Shared Transportation** (`ai/transport_optimizer.py`): clusters
  pending shipments by geographic proximity and bin-packs them into
  truck-capacity loads, estimating cost savings vs. shipping solo.
- **Orders & payment**: Cash on Delivery or Online (mocked), buyer
  rating/feedback loop that updates the farmer's average rating.

## Setup

```bash
cd agrimarket
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000** in your browser. The SQLite database
(`agrimarket.db`) and uploads folder are created automatically on first run.

## Project structure

```
agrimarket/
  app.py                  # Flask routes (auth, farmer flow, buyer flow, transport)
  models.py                # SQLAlchemy models (User, Product, Order, Request, Rating, Notification)
  ai/
    price_recommender.py   # AI Feature 1: price suggestion
    quality_checker.py     # AI Feature 2: photo quality grading
    product_matcher.py     # AI Feature 3: search + demand-gap detection
    transport_optimizer.py # AI Feature 4: shared truck load optimization
  data/base_prices.csv     # training data for the price model
  templates/                # Jinja2 HTML templates
  static/css/style.css      # styling
  translations/en.json, ta.json  # all UI strings, bilingual
```

## Notes / next steps for a production version

- Replace the quality-check heuristic with a CNN trained on labelled
  produce photos once you have a dataset (interface won't need to change).
- Replace the price model's static CSV with a live mandi price API feed.
- Swap the greedy transport clustering for Google OR-Tools' CVRP solver
  once shipment volume is high enough to justify it.
- Add real payment gateway integration (Razorpay/Cashfree) in place of
  the mocked online-payment flow.
- Move from Flask's dev server to Gunicorn + Nginx, and SQLite to
  PostgreSQL, for deployment.
