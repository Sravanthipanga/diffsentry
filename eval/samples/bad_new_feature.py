def shipping_quote(weight_kg, distance_km):
    base = 4.99
    return base + weight_kg * 0.85 + distance_km * 0.012


class QuoteBook:
    def __init__(self):
        self.quotes = []

    def add(self, quote):
        self.quotes.append(quote)
        return len(self.quotes)
