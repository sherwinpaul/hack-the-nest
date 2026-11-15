"""Major US airports: coordinates (for the map and weather) and IANA time zones.

Kiwi returns local, zone-less times, so the origin's zone anchors the UTC conversion.
"""

from zoneinfo import ZoneInfo

# code: (lat, lon, tz)
AIRPORTS: dict[str, tuple[float, float, str]] = {
    "ATL": (33.6407, -84.4277, "America/New_York"),
    "AUS": (30.1975, -97.6664, "America/Chicago"),
    "BNA": (36.1263, -86.6774, "America/Chicago"),
    "BOS": (42.3656, -71.0096, "America/New_York"),
    "BWI": (39.1754, -76.6683, "America/New_York"),
    "CLE": (41.4117, -81.8498, "America/New_York"),
    "CLT": (35.2140, -80.9431, "America/New_York"),
    "CMH": (39.9980, -82.8919, "America/New_York"),
    "CVG": (39.0489, -84.6678, "America/New_York"),
    "COS": (38.8058, -104.7008, "America/Denver"),
    "DAL": (32.8471, -96.8518, "America/Chicago"),
    "DCA": (38.8512, -77.0402, "America/New_York"),
    "DEN": (39.8561, -104.6737, "America/Denver"),
    "DFW": (32.8998, -97.0403, "America/Chicago"),
    "DTW": (42.2124, -83.3534, "America/Detroit"),
    "EWR": (40.6895, -74.1745, "America/New_York"),
    "FLL": (26.0742, -80.1506, "America/New_York"),
    "HOU": (29.6454, -95.2789, "America/Chicago"),
    "IAD": (38.9531, -77.4565, "America/New_York"),
    "IAH": (29.9902, -95.3368, "America/Chicago"),
    "IND": (39.7173, -86.2944, "America/Indiana/Indianapolis"),
    "JFK": (40.6413, -73.7781, "America/New_York"),
    "LAS": (36.0840, -115.1537, "America/Los_Angeles"),
    "LAX": (33.9416, -118.4085, "America/Los_Angeles"),
    "LGA": (40.7769, -73.8740, "America/New_York"),
    "MCI": (39.2976, -94.7139, "America/Chicago"),
    "MCO": (28.4312, -81.3081, "America/New_York"),
    "MDW": (41.7868, -87.7522, "America/Chicago"),
    "MIA": (25.7959, -80.2870, "America/New_York"),
    "MKE": (42.9476, -87.8966, "America/Chicago"),
    "MSP": (44.8848, -93.2223, "America/Chicago"),
    "MSY": (29.9934, -90.2580, "America/Chicago"),
    "OMA": (41.3032, -95.8941, "America/Chicago"),
    "ORD": (41.9742, -87.9073, "America/Chicago"),
    "PDX": (45.5898, -122.5951, "America/Los_Angeles"),
    "PHL": (39.8744, -75.2424, "America/New_York"),
    "PHX": (33.4352, -112.0101, "America/Phoenix"),
    "PIT": (40.4919, -80.2329, "America/New_York"),
    "RDU": (35.8801, -78.7880, "America/New_York"),
    "SAN": (32.7338, -117.1933, "America/Los_Angeles"),
    "SAT": (29.5337, -98.4698, "America/Chicago"),
    "SEA": (47.4502, -122.3088, "America/Los_Angeles"),
    "SFO": (37.6213, -122.3790, "America/Los_Angeles"),
    "SLC": (40.7899, -111.9791, "America/Denver"),
    "STL": (38.7499, -90.3748, "America/Chicago"),
    "TPA": (27.9755, -82.5332, "America/New_York"),
}

AIRPORT_COORDS = {code: (lat, lon) for code, (lat, lon, _) in AIRPORTS.items()}


def tz_for(code: str) -> ZoneInfo | None:
    entry = AIRPORTS.get(code)
    return ZoneInfo(entry[2]) if entry else None


# Short display names for the map labels
CITY = {
    "ATL": "Atlanta", "AUS": "Austin", "BNA": "Nashville", "BOS": "Boston", "BWI": "Baltimore",
    "CLE": "Cleveland", "CLT": "Charlotte", "CMH": "Columbus", "CVG": "Cincinnati",
    "COS": "Colorado Springs", "DAL": "Dallas Love", "DCA": "Washington", "DEN": "Denver",
    "DFW": "Dallas–Fort Worth", "DTW": "Detroit", "EWR": "Newark", "FLL": "Fort Lauderdale",
    "HOU": "Houston Hobby", "IAD": "Washington Dulles", "IAH": "Houston", "IND": "Indianapolis",
    "JFK": "New York JFK", "LAS": "Las Vegas", "LAX": "Los Angeles", "LGA": "New York LaGuardia",
    "MCI": "Kansas City", "MCO": "Orlando", "MDW": "Chicago Midway", "MIA": "Miami",
    "MKE": "Milwaukee", "MSP": "Minneapolis", "MSY": "New Orleans", "OMA": "Omaha",
    "ORD": "Chicago O'Hare", "PDX": "Portland", "PHL": "Philadelphia", "PHX": "Phoenix",
    "PIT": "Pittsburgh", "RDU": "Raleigh–Durham", "SAN": "San Diego", "SAT": "San Antonio",
    "SEA": "Seattle", "SFO": "San Francisco", "SLC": "Salt Lake City", "STL": "St. Louis",
    "TPA": "Tampa",
}


# Airline display names by IATA code (live Kiwi fares also carry their own names)
AIRLINES = {
    "AA": "American Airlines", "AC": "Air Canada", "AF": "Air France", "AM": "Aeroméxico",
    "AS": "Alaska Airlines", "B6": "JetBlue", "BA": "British Airways", "DL": "Delta Air Lines",
    "F9": "Frontier Airlines", "G4": "Allegiant Air", "HA": "Hawaiian Airlines", "KL": "KLM",
    "LH": "Lufthansa", "MX": "Breeze Airways", "NK": "Spirit Airlines", "QX": "Horizon Air",
    "SY": "Sun Country Airlines", "UA": "United Airlines", "WN": "Southwest Airlines",
    "WS": "WestJet", "XP": "Avelo Airlines", "YX": "Republic Airways", "OO": "SkyWest Airlines",
    "9E": "Endeavor Air", "MQ": "Envoy Air", "ZZ": "Duffel Airways",
}
